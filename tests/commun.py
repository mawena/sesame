"""Machine simulée pour les tests : racine temporaire, commandes enregistrées et simulées (sans root, sans effet réel)."""
import os
import tempfile
import unittest
from pathlib import Path

from sesame import config as cfg
from sesame.systeme import Resultat, Systeme

A, N = "charles-gamligo", "charles.gamligo@cofinacorp.com"
U = G = 1000
NU = NG = 60001
H, NH = "/home/" + A, "/home/" + N
LOCATAIRE = "11111111-2222-3333-4444-555555555555"
CLIENT = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
DOC = "document important\n"


class Machine(Systeme):
    """Système simulé : comptes locaux dans la racine, comptes Entra et état des services en mémoire."""

    def __init__(self, racine, root=True):
        super().__init__(racine, env={})
        self.root = root
        self.uid = 4242
        self.appels = []
        self.forces = {}          # tuple(argv) -> Resultat
        self.entra = {}           # nom -> {"uid", "gid", "home"}
        self.domaines_joints = []
        self.paquets, self.snaps = set(), set()
        self.versions = {"authd": "0.7.1~24.04", "authd-msentraid": "0.5.0"}   # versions installées
        self.mises_a_jour = {}    # versions qu'apporteraient apt-get install et snap refresh
        self.actifs, self.actives = set(), set()
        self.crontabs = {}
        self.mots_de_passe = {}
        self.panne_a = None       # indice (parmi les commandes qui modifient) de la commande qui échoue
        self.nb_modif = 0
        self.pannes = []
        self.authctl = []         # un dict par appel : commande et dossier courant du compte Entra
        self.authctl_cree_dossier = False
        self.groupe_reste = False
        self.authctl_present = True
        self.evenements = []

    # --- remplacements
    def est_root(self):
        return self.root

    def programme_present(self, nom):
        return self.authctl_present if nom == "authctl" else True

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
        return (argv[0] in ("getent", "dpkg-query") or argv[:2] in (["realm", "list"], ["snap", "list"])
                or (argv[0] == "systemctl" and argv[1].startswith("is-")) or (argv[0] == "crontab" and "-l" in argv))

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
            for nom, e in self.entra.items():
                if cle in (nom, str(e["uid"])):
                    return Resultat(0, f"{nom}:x:{e['uid']}:{e['gid']}::{e['home']}:/bin/bash\n")
        if base == "group":
            for g in self.groupes_locaux().values():
                if cle in (g.nom, str(g.gid)):
                    return Resultat(0, f"{g.nom}:x:{g.gid}:{','.join(g.membres)}\n")
            for nom, e in self.entra.items():
                if cle in (nom, str(e["gid"])):
                    return Resultat(0, f"{nom}:x:{e['gid']}:\n")
        return Resultat(2)

    def _realm(self, a, entree):
        if a[0] == "list":
            return Resultat(0, "".join(d + "\n" for d in self.domaines_joints))
        if a[0] == "leave":
            self.domaines_joints = [d for d in self.domaines_joints if d != a[-1]]
        return Resultat(0)

    def _dpkg_query(self, a, entree):
        if a[-1] not in self.paquets:
            return Resultat(1, "", "pas installé")
        return Resultat(0, self.versions.get(a[-1], "1.0")) if "-f=${Version}" in a else Resultat(0, "ii ")

    def _mettre_a_jour(self, nom):
        if nom in self.mises_a_jour:
            self.versions[nom] = self.mises_a_jour[nom]

    def _snap(self, a, entree):
        if a[0] == "install":
            self.snaps.add(a[-1])
            self._mettre_a_jour(a[-1])
            return Resultat(0)
        if a[-1] not in self.snaps:
            return Resultat(1, "", "snap introuvable")
        if a[0] == "refresh":
            self._mettre_a_jour(a[-1])
            return Resultat(0)
        return Resultat(0, "Name             Version  Rev  Tracking       Publisher   Notes\n"
                           f"{a[-1]}  {self.versions.get(a[-1], '1.0')}  42   latest/stable  canonical✓  -\n")

    def _apt_get(self, a, entree):
        if a[0] == "install":
            for nom in (x for x in a[1:] if not x.startswith("-")):
                self.paquets.add(nom)
                self._mettre_a_jour(nom)
        return Resultat(0)

    def _systemctl(self, a, entree):
        if a[0] == "is-active":
            return Resultat(0, "active\n") if a[1] in self.actifs else Resultat(3, "inactive\n")
        if a[0] == "is-enabled":
            return Resultat(0, "enabled\n") if a[1] in self.actives else Resultat(1, "disabled\n")
        return Resultat(0)

    def _chpasswd(self, a, entree):
        nom, mdp = entree.rstrip("\n").split(":", 1)
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
        self._ajouter_a_groupe(a[2], a[-1])
        return Resultat(0)

    def _ajouter_a_groupe(self, groupe, nom):
        lignes = []
        for l in self._lignes("/etc/group"):
            g = l.split(":")
            if g[0] == groupe and nom not in g[3].split(","):
                g[3] = ",".join([m for m in g[3].split(",") if m] + [nom])
            lignes.append(":".join(g))
        self.ecrire("/etc/group", "\n".join(lignes) + "\n")

    def _userdel(self, a, entree):
        nom = a[-1]
        self.ecrire("/etc/passwd", "".join(l + "\n" for l in self._lignes("/etc/passwd") if l.split(":")[0] != nom))
        lignes = []
        for l in self._lignes("/etc/group"):
            g = l.split(":")
            if g[0] == nom and not self.groupe_reste:
                continue
            g[3] = ",".join(m for m in g[3].split(",") if m and m != nom)
            lignes.append(":".join(g))
        self.ecrire("/etc/group", "\n".join(lignes) + "\n")
        return Resultat(0)

    def _groupdel(self, a, entree):
        self.ecrire("/etc/group", "".join(l + "\n" for l in self._lignes("/etc/group") if l.split(":")[0] != a[-1]))
        return Resultat(0)

    def _crontab(self, a, entree):
        compte = a[1] if a[0] == "-u" else next((n for n, e in self.entra.items() if e["uid"] == self.uid), "?")
        if "-l" in a:
            return Resultat(0, self.crontabs[compte]) if compte in self.crontabs else Resultat(1, "", "no crontab")
        if "-r" in a:
            return Resultat(0) if self.crontabs.pop(compte, None) is not None else Resultat(1)
        self.crontabs[compte] = Path(a[2]).read_text()
        self.ecrire(f"/var/spool/cron/crontabs/{compte}", self.crontabs[compte], 0o600)
        return Resultat(0)

    def _authctl(self, a, entree):
        nom = a[2]
        e = self.entra.get(nom)
        if e is None:
            return Resultat(1, "", "utilisateur inconnu")
        self.authctl.append({"commande": a, "dossier_courant": e["home"],
                             "courant_existe": self.chemin(e["home"]).exists()})
        if a[:2] == ["user", "set-uid"]:
            e["uid"] = int(a[3])
        elif a[:2] == ["group", "set-gid"]:
            e["gid"] = int(a[3])
        elif a[:2] == ["user", "set-home"]:
            ancien, nouveau = self.chemin(e["home"]), self.chemin(a[3])
            if ancien.exists():  # comportement d'authctl : le contenu de l'ancien dossier suit
                if nouveau.exists():
                    return Resultat(1, "", "le dossier existe")
                os.rename(ancien, nouveau)
            elif self.authctl_cree_dossier:
                nouveau.mkdir(parents=True)
            e["home"] = a[3]
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
        """Poste type : compte local A (avec dossier, crontab, unité, VMware…), compte Entra N déjà connu d'authd."""
        m = self.m
        self.ecrire("/etc/passwd", f"root:x:0:0::/root:/bin/bash\n{A}:x:{U}:{G}::{H}:/bin/bash\n"
                                   + (f"secours:x:1001:1001::/home/secours:/bin/bash\n" if secours else ""))
        self.ecrire("/etc/group", f"root:x:0:\nsudo:x:27:{A}" + (",secours" if secours else "")
                    + f"\ndocker:x:999:{A}\nlpadmin:x:998:{A}\n{A}:x:{G}:\n")
        self.ecrire("/etc/shadow", "root:*:1::::::\n", 0o640)
        self.ecrire("/etc/subuid", f"{A}:100000:65536\nautre:200000:65536\n")
        self.ecrire("/etc/subgid", f"{A}:100000:65536\n")
        self.ecrire("/etc/nsswitch.conf", "passwd:         files systemd\ngroup:          files systemd\n"
                                          "shadow:         files\nhosts:          files dns\n")
        self.ecrire("/etc/login.defs", "LOGIN_TIMEOUT\t\t60\n")
        self.ecrire("/etc/os-release", 'VERSION_ID="24.04"\n')
        self.ecrire("/etc/gdm3/custom.conf", f"[daemon]\nAutomaticLogin={A}\nAutomaticLoginEnable=true\n")
        self.ecrire("/etc/systemd/system/app.service", f"[Service]\nUser={A}\nGroup={A}\nExecStart=/bin/app\n")
        self.ecrire("/etc/systemd/system/autre.service", "[Service]\nUser=root\n")
        self.ecrire("/etc/vmware/hostd/authorization.xml", f"<a><ACEDataUser>{A}</ACEDataUser></a>\n")
        self.ecrire(f"/var/lib/AccountsService/users/{A}", f"[User]\nIcon=/var/lib/AccountsService/icons/{A}\n")
        self.ecrire(f"/var/lib/AccountsService/icons/{A}", "png")
        self.ecrire(f"{H}/doc.txt", DOC)
        self.ecrire(f"{H}/.config/réglage", "x")
        self.ecrire(f"{NH}/.profile", "vierge\n")
        self.ecrire(f"/var/spool/cron/crontabs/{A}", "0 2 * * * sauvegarde\n", 0o600)
        m.crontabs[A] = "0 2 * * * sauvegarde\n"
        m.entra[N] = {"uid": NU, "gid": NG, "home": NH}
        m.paquets.add("authd")
        m.snaps.add("authd-msentraid")
        m.actifs.update({"authd", "snap.authd-msentraid.authd-msentraid.service"})
        m.actives.add("app.service")
        m.actifs.add("app.service")

    def config(self, **extra):
        c = cfg.Config(LOCATAIRE, CLIENT, N, A, U, G, H, "secours", ["sudo", "docker"])
        for k, v in extra.items():
            setattr(c, k, v)
        cfg.ecrire(self.m, c)
        return c

    def parametres(self):
        from sesame.reprise import Parametres
        return Parametres(A, N, U, G, H)
