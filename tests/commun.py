"""Machine simulée pour les tests : racine temporaire, commandes enregistrées et simulées (sans root, sans effet réel)."""
import tempfile
import unittest

from sesame import config as cfg, himmelblau
from sesame.systeme import Resultat, Systeme

A, N = "charles-gamligo", "charles.gamligo@acmecorp.com"
U = G = 1000
H = "/home/" + A
NOM = "PC-CHARLES"
EMPREINTE = "$y$j9T$sel$empreinte-du-mot-de-passe-ubuntu"
PAQUETS_DIR = "/home/charles-gamligo/.local/share/sesame/himmelblau/packaging"
DOSSIER_COMPIL = PAQUETS_DIR.rsplit("/", 1)[0]
DOC = "document important\n"


class Machine(Systeme):
    """Système simulé : fichiers dans la racine temporaire, paquets et services en mémoire."""

    def __init__(self, racine, root=True):
        super().__init__(racine, env={})
        self.root = root
        self.uid = 4242
        self.appels = []
        self.forces = {}          # tuple(argv) -> Resultat
        self.domaines_joints = []
        self.paquets = set()
        self.versions = {"himmelblau": "4.0.1"}
        self.actifs, self.actives = set(), set()
        self.crontabs = {}
        self.mots_de_passe = {}
        self.empreintes = {}      # comptes dont l'empreinte a été copiée par chpasswd -e
        self.panne_a = None       # indice (parmi les commandes qui modifient) de la commande qui échoue
        self.nb_modif = 0
        self.pannes = []
        self.evenements = []
        self.apparmor_echoue = False
        self.apparmor_a_moitie = False  # l'installation de himmelblau-apparmor le laisse dépaqueté (« iU »)
        self.conffiles = {}       # paquet -> {chemin: contenu} (fichiers de configuration du .deb)
        self.etats = {}           # paquet -> état dpkg forcé (« iU », « iF »…)
        self.unites_absentes = set()
        self.proprietaires = {}   # chemin -> UID (sinon U)
        self.aad_ok = True
        self.aad_present = True

    # --- remplacements
    def est_root(self):
        return self.root

    def programme_present(self, nom):
        return self.aad_present if nom == "aad-tool" else True

    def proprietaire(self, p):
        return self.proprietaires.get(p, U) if self.existe(p) else None

    def lancer(self, argv, entree=None, direct=None):
        argv = [str(a) for a in argv]
        self.appels.append(argv)
        if tuple(argv) in self.forces:
            return self.forces[tuple(argv)]
        if not self._lecture(argv):
            i, self.nb_modif = self.nb_modif, self.nb_modif + 1
            if i == self.panne_a:
                self.pannes.append(argv)
                return Resultat(1, "", "panne simulée")
        fonction = getattr(self, "_" + argv[0].replace("-", "_"), None)
        return fonction(argv[1:], entree) if fonction else Resultat(0)

    @staticmethod
    def _lecture(argv):
        return (argv[0] in ("getent", "dpkg-query", "dpkg-deb") or argv[:2] in (["realm", "list"], ["aad-tool", "status"])
                or (argv[0] == "systemctl" and (argv[1].startswith("is-") or argv[1] == "list-unit-files")) or (argv[0] == "crontab" and "-l" in argv))

    def modifiantes(self):
        """Commandes lancées qui ne sont pas de simples lectures."""
        return [a for a in self.appels if not self._lecture(a)]

    def ecrit(self, type_, texte):
        self.evenements.append((type_, texte))

    # --- simulations
    def _lignes(self, chemin):
        return [l for l in self.lire(chemin).splitlines() if l]

    def _getent(self, a, entree):
        base, cle = a
        if base == "passwd":
            for u in self.comptes_locaux().values():
                if cle in (u.nom, str(u.uid)):
                    return Resultat(0, f"{u.nom}:x:{u.uid}:{u.gid}::{u.dossier}:/bin/bash\n")
        if base == "group":
            for g in self.groupes_locaux().values():
                if cle in (g.nom, str(g.gid)):
                    return Resultat(0, f"{g.nom}:x:{g.gid}:{','.join(g.membres)}\n")
        return Resultat(2)

    def _realm(self, a, entree):
        if a[0] == "list":
            return Resultat(0, "".join(d + "\n" for d in self.domaines_joints))
        if a[0] == "leave":
            self.domaines_joints = [d for d in self.domaines_joints if d != a[-1]]
        return Resultat(0)

    def _dpkg_query(self, a, entree):
        if a[-1] in self.etats and "-f=${Version}" not in a:
            return Resultat(0, self.etats[a[-1]] + " ")
        if a[-1] not in self.paquets:
            return Resultat(1, "", "pas installé")
        return Resultat(0, self.versions.get(a[-1], "1.0")) if "-f=${Version}" in a else Resultat(0, "ii ")

    def _poser(self, nom, garder):
        """Pose les fichiers de configuration du paquet comme dpkg : un fichier du poste différent fait poser une
        question, sans réponse possible sans `garder` (--force-confold) ; le paquet reste alors dépaqueté."""
        for chemin, texte in self.conffiles.get(nom, {}).items():
            if not self.existe(chemin):
                self.ecrire(chemin, texte)
            elif self.lire(chemin) != texte:
                if not garder:
                    self.etats[nom] = "iU"
                    self.paquets.discard(nom)
                    return False
                self.ecrire(chemin + ".dpkg-dist", texte)
        self.etats.pop(nom, None)
        self.paquets.add(nom)
        return True

    def _apt_get(self, a, entree):
        if a[0] == "install":
            noms, options, suite = [], [], iter(a[1:])
            for x in suite:
                if x == "-o":
                    options.append(next(suite, ""))
                elif not x.startswith("-"):
                    noms.append(x.rsplit("/", 1)[-1].split("_")[0] if x.endswith(".deb") else x)
            if "himmelblau-apparmor" in noms and self.apparmor_echoue:
                return Resultat(100, "", "E: himmelblau-apparmor introuvable")
            if "himmelblau-apparmor" in noms and self.apparmor_a_moitie:
                self.etats["himmelblau-apparmor"] = "iF"
                return Resultat(100, "", "E: Sub-process /usr/bin/dpkg returned an error code (1)")
            garder = "Dpkg::Options::=--force-confold" in options
            for nom in noms:
                if not self._poser(nom, garder):
                    return Resultat(100, "", "end of file on stdin at conffile prompt")
        return Resultat(0)

    def _dpkg(self, a, entree):
        if "--configure" in a:
            for nom in [n for n, e in self.etats.items() if e[1] != "i"]:
                if not self._poser(nom, "--force-confold" in a):
                    return Resultat(1, "", "end of file on stdin at conffile prompt")
        elif a[0] == "--remove":
            self.paquets.discard(a[-1])
            self.etats.pop(a[-1], None)
        return Resultat(0)

    def _dpkg_deb(self, a, entree):
        """dpkg-deb -f FICHIER Package : le fichier simulé contient le nom du paquet ; -I FICHIER conffiles et
        -x FICHIER DOSSIER utilisent `conffiles`."""
        if not self.existe(a[1]):
            return Resultat(1, "", "dpkg-deb : fichier illisible")
        nom = self.lire(a[1]).strip()
        if a[0] == "-f":
            return Resultat(0, nom + "\n")
        if a[0] == "-I" and a[2:] == ["conffiles"]:
            if not self.conffiles.get(nom):
                return Resultat(2, "", "ne contient pas de composant de contrôle « conffiles »")
            return Resultat(0, "".join(c + "\n" for c in self.conffiles[nom]))
        if a[0] == "-x":
            for chemin, texte in self.conffiles.get(nom, {}).items():
                self.ecrire(a[2] + chemin, texte)
            return Resultat(0)
        return Resultat(2, "", "option inconnue")

    def _hostnamectl(self, a, entree):
        if a[0] == "hostname":
            self.ecrire("/etc/hostname", a[1] + "\n")
        return Resultat(0)

    def _systemctl(self, a, entree):
        if a[0] == "is-active":
            return Resultat(0, "active\n") if a[1] in self.actifs else Resultat(3, "inactive\n")
        if a[0] == "is-enabled":
            return Resultat(0, "enabled\n") if a[1] in self.actives else Resultat(1, "disabled\n")
        noms = [x for x in a[1:] if not x.startswith("-")]
        if a[0] == "list-unit-files":
            return Resultat(0, "".join(f"{n} disabled enabled\n" for n in noms if n not in self.unites_absentes))
        if a[0] == "enable":
            self.actives.update(noms)
            if "--now" in a:
                self.actifs.update(noms)
        elif a[0] == "disable":
            self.actives.difference_update(noms)
            if "--now" in a:
                self.actifs.difference_update(noms)
        elif a[0] in ("start", "restart"):
            self.actifs.update(noms)
        elif a[0] == "stop":
            self.actifs.difference_update(noms)
        return Resultat(0)

    def _pam_auth_update(self, a, entree):
        if a[:1] == ["--enable"]:
            texte = self.lire("/etc/pam.d/common-auth")
            if "pam_himmelblau" not in texte:
                self.ecrire("/etc/pam.d/common-auth",
                            "auth [success=end default=ignore] pam_himmelblau.so ignore_unknown_user set_authtok\n" + texte)
        if a[:1] == ["--disable"]:
            self.ecrire("/etc/pam.d/common-auth", "\n".join(
                l for l in self.lire("/etc/pam.d/common-auth").splitlines() if a[1] not in l and "pam_himmelblau" not in l
            ) + "\n")
        return Resultat(0)

    def _aad_tool(self, a, entree):
        ok = self.aad_ok and "himmelblaud" in self.actifs
        return Resultat(0 if ok else 1, "working\n" if ok else "", "" if ok else "démon injoignable")

    def _chpasswd(self, a, entree):
        nom, mdp = entree.rstrip("\n").split(":", 1)
        if "-e" in a:
            self.empreintes[nom] = mdp
            lignes = [l for l in self._lignes("/etc/shadow") if l.split(":")[0] != nom]
            self.ecrire("/etc/shadow", "\n".join(lignes + [f"{nom}:{mdp}:19000:0:99999:7:::"]) + "\n", 0o640)
        else:
            self.mots_de_passe[nom] = mdp
        return Resultat(0)

    def _useradd(self, a, entree):
        nom = a[-1]
        uid = max([u.uid for u in self.comptes_locaux().values() if u.uid < 60000] + [999]) + 1
        self.ecrire("/etc/passwd", self.lire("/etc/passwd") + f"{nom}:x:{uid}:{uid}::/home/{nom}:/bin/bash\n")
        self.ecrire("/etc/group", self.lire("/etc/group") + f"{nom}:x:{uid}:\n")
        self._ajouter_a_groupe("sudo", nom)
        return Resultat(0)

    def _usermod(self, a, entree):
        if "--add-subuids" in a:
            for f in ("/etc/subuid", "/etc/subgid"):
                self.ecrire(f, self.lire(f) + f"{a[-1]}:100000:65536\n")
        else:
            self._ajouter_a_groupe(a[1], a[-1])
        return Resultat(0)

    def _ajouter_a_groupe(self, groupe, nom):
        lignes = []
        for l in self._lignes("/etc/group"):
            g = l.split(":")
            if g[0] == groupe and nom not in g[3].split(","):
                g[3] = ",".join([m for m in g[3].split(",") if m] + [nom])
            lignes.append(":".join(g))
        self.ecrire("/etc/group", "\n".join(lignes) + "\n")

    def _crontab(self, a, entree):
        compte = a[1] if a[0] == "-u" else "?"
        if "-l" in a:
            return Resultat(0, self.crontabs[compte]) if compte in self.crontabs else Resultat(1, "", "no crontab")
        return Resultat(0)


class Base(unittest.TestCase):
    """Cas de test avec une machine sur racine temporaire."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.m = Machine(self._tmp.name)

    def ecrire(self, chemin, texte, mode=None):
        self.m.ecrire(chemin, texte, mode)

    def lire(self, chemin):
        return self.m.lire(chemin)

    def existe(self, chemin):
        return self.m.existe(chemin)

    def peupler(self, secours=True):
        """Poste vierge d'Ubuntu 24.04 : compte local A (dossier, crontab, mot de passe), pas de Himmelblau."""
        m = self.m
        self.ecrire("/etc/passwd", f"root:x:0:0::/root:/bin/bash\n{A}:x:{U}:{G}::{H}:/bin/bash\n"
                                   + ("secours:x:1001:1001::/home/secours:/bin/bash\n" if secours else ""))
        self.ecrire("/etc/group", f"root:x:0:\nsudo:x:27:{A}" + (",secours" if secours else "")
                    + f"\ndocker:x:999:{A}\n{A}:x:{G}:\n")
        self.ecrire("/etc/shadow", f"root:*:19000::::::\n{A}:{EMPREINTE}:19000:0:99999:7:::\n", 0o640)
        self.ecrire("/etc/nsswitch.conf", "passwd:         files systemd\ngroup:          files systemd\n"
                                          "shadow:         files\nhosts:          files dns\n")
        self.ecrire("/etc/pam.d/common-auth", "auth\t[success=1 default=ignore]\tpam_unix.so nullok\n")
        self.ecrire("/etc/login.defs", "LOGIN_TIMEOUT\t\t60\n")
        self.ecrire("/etc/os-release", 'VERSION_ID="24.04"\n')
        self.ecrire("/etc/hostname", "ubuntu-pc\n")
        self.ecrire("/etc/hosts", "127.0.0.1\tlocalhost\n127.0.1.1\tubuntu-pc\n::1\tip6-localhost\n")
        self.ecrire(f"{H}/doc.txt", DOC)
        self.ecrire(f"/var/spool/cron/crontabs/{A}", "0 2 * * * sauvegarde\n", 0o600)
        m.crontabs[A] = "0 2 * * * sauvegarde\n"

    def installer_outils(self):
        self.m.paquets.update(himmelblau.OUTILS)
        self.ecrire("/etc/subuid", f"{A}:100000:65536\n")
        self.ecrire("/etc/subgid", f"{A}:100000:65536\n")

    def fabriquer_debs(self, dossier=PAQUETS_DIR, noms=None, version="4.0.1"):
        """Dossier de .deb simulés (le contenu est le champ Package) ; renvoie le dossier."""
        for nom in noms or himmelblau.PAQUETS:
            self.ecrire(f"{dossier}/{nom}_{version}_amd64.deb", nom + "\n")
        return dossier

    def installer_himmelblau(self, lier=True, compte=N):
        """État d'un poste où Himmelblau est installé (et relié à `compte` si `lier`)."""
        m = self.m
        m.paquets.update(himmelblau.PAQUETS)
        self.ecrire("/etc/nsswitch.conf", "passwd:         files systemd himmelblau\ngroup:          files systemd "
                                          "himmelblau\nshadow:         files\nhosts:          files dns\n")
        self.ecrire("/etc/pam.d/common-auth", "auth\t[success=2 default=ignore]\tpam_himmelblau.so ignore_unknown_user\n"
                                              "auth\t[success=1 default=ignore]\tpam_unix.so nullok\n")
        if lier:
            self.ecrire(himmelblau.CONFIG, himmelblau.texte_config("", himmelblau.domaine(compte), himmelblau.USER_MAP))
            self.ecrire(himmelblau.USER_MAP, f"{A}:{compte}\n")
            m.creer_lien(A, f"/home/{compte}")
            m.actifs.update(himmelblau.SERVICES)
            m.actives.update(himmelblau.SERVICES)

    def config(self, **extra):
        c = cfg.Config(N, A, U, G, H, "secours", NOM)
        for k, v in extra.items():
            setattr(c, k, v)
        cfg.ecrire(self.m, c)
        return c
