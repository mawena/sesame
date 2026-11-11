"""Accès au système : fichiers sous une racine, commandes externes (une seule méthode), NSS et /proc.

Les tests remplacent `Systeme.lancer`, seul endroit où un processus externe est démarré.
"""
import json
import os
import re
import shutil
import subprocess
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


class ErreurSesame(Exception):
    """Erreur dont le message est destiné à l'utilisateur."""


class ErreurSysteme(ErreurSesame):
    """Une commande externe a échoué."""


@dataclass
class Resultat:
    """Résultat d'une commande externe."""
    code: int
    sortie: str = ""
    erreur: str = ""
    diffuse: bool = False  # vrai si les lignes ont déjà été transmises pendant l'exécution

    @property
    def ok(self):
        return self.code == 0


@dataclass
class Utilisateur:
    """Une ligne de passwd."""
    nom: str
    uid: int
    gid: int
    dossier: str
    shell: str = ""


@dataclass
class Groupe:
    """Une ligne de group."""
    nom: str
    gid: int
    membres: list = field(default_factory=list)


def lire_utilisateur(ligne):
    """Analyse une ligne passwd ; renvoie None si elle est invalide."""
    p = ligne.strip().split(":")
    if len(p) < 6 or not p[2].isdigit() or not p[3].isdigit():
        return None
    return Utilisateur(p[0], int(p[2]), int(p[3]), p[5], p[6] if len(p) > 6 else "")


def lire_groupe(ligne):
    """Analyse une ligne group ; renvoie None si elle est invalide."""
    p = ligne.strip().split(":")
    if len(p) < 3 or not p[2].isdigit():
        return None
    return Groupe(p[0], int(p[2]), [m for m in (p[3].split(",") if len(p) > 3 else []) if m])


def _copie(src, dst):
    """Copie un fichier ou un lien en gardant droits et, si root, propriétaire."""
    if os.path.lexists(dst):
        os.unlink(dst)
    if os.path.islink(src):
        os.symlink(os.readlink(src), dst)
        return
    shutil.copy2(src, dst)
    if os.geteuid() == 0:
        st = os.stat(src)
        os.chown(dst, st.st_uid, st.st_gid)


class Systeme:
    """Le système vu depuis une racine (« / » en production, un dossier temporaire dans les tests)."""

    def __init__(self, racine="/", recepteur=None, env=None):
        self.racine = Path(racine)
        self.recepteur = recepteur  # fonction (type, texte) qui reçoit les événements
        self.env = dict(os.environ if env is None else env)
        self.uid = os.getuid()
        self._verrou = threading.Lock()

    # --- chemins et fichiers
    def chemin(self, absolu):
        """Chemin réel d'un chemin système."""
        return self.racine / str(absolu).lstrip("/")

    def existe(self, p):
        return os.path.lexists(self.chemin(p))

    def est_dossier(self, p):
        c = self.chemin(p)
        return c.is_dir() and not c.is_symlink()

    def est_vide(self, p):
        return self.est_dossier(p) and not os.listdir(self.chemin(p))

    def lister(self, p):
        try:
            return sorted(os.listdir(self.chemin(p)))
        except OSError:
            return []

    def lire(self, p, defaut=""):
        try:
            return self.chemin(p).read_text(encoding="utf-8", errors="replace")
        except OSError:
            return defaut

    def ecrire(self, p, texte, mode=None):
        """Écrit un fichier (dossiers créés) ; `mode` est appliqué s'il est donné."""
        c = self.chemin(p)
        c.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(c, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode or 0o644)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(texte)
        if mode is not None:
            os.chmod(c, mode)

    def lire_json(self, p, defaut=None):
        try:
            return json.loads(self.lire(p, "") or "null") or defaut
        except ValueError:
            return defaut

    def ecrire_json(self, p, donnees, mode=None):
        self.ecrire(p, json.dumps(donnees, ensure_ascii=False, indent=2) + "\n", mode)

    def creer_dossier(self, p, mode=0o755):
        self.chemin(p).mkdir(parents=True, exist_ok=True)
        os.chmod(self.chemin(p), mode)

    def supprimer(self, p):
        """Supprime un fichier ou un dossier ; sans erreur s'il n'existe pas."""
        c = self.chemin(p)
        if c.is_dir() and not c.is_symlink():
            shutil.rmtree(c)
        elif os.path.lexists(c):
            os.unlink(c)

    def deplacer(self, src, dst):
        """Renomme `src` en `dst`, qui ne doit pas exister (jamais de déplacement « dans » un dossier)."""
        if self.existe(dst):
            raise ErreurSesame(f"{dst} existe déjà")
        self.chemin(dst).parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(self.chemin(src)), str(self.chemin(dst)))

    def copier(self, src, dst):
        """Copie un fichier ou un dossier (fusionné s'il existe) en gardant droits et liens."""
        s, d = self.chemin(src), self.chemin(dst)
        d.parent.mkdir(parents=True, exist_ok=True)
        if s.is_dir() and not s.is_symlink():
            shutil.copytree(s, d, symlinks=True, dirs_exist_ok=True, copy_function=_copie)
        else:
            _copie(s, d)

    def est_root(self):
        return os.geteuid() == 0

    def programme_present(self, nom):
        return shutil.which(nom) is not None

    # --- temps
    def horodatage(self):
        return datetime.now().strftime("%Y%m%d-%H%M%S")

    def date_iso(self):
        return datetime.now().astimezone().isoformat(timespec="seconds")

    # --- événements
    def dire(self, type_, texte):
        """Transmet un événement (`etape`, `commande`, `sortie`, `avertissement`) au récepteur."""
        if self.recepteur:
            with self._verrou:
                self.recepteur(type_, texte)

    def etape(self, texte):
        self.dire("etape", texte)

    def avertir(self, texte):
        self.dire("avertissement", texte)

    # --- commandes externes
    def lancer(self, argv, entree=None, direct=None):
        """Seul point d'exécution des commandes externes. `direct(ligne)` reçoit les lignes au fil de l'eau."""
        env = dict(os.environ, LC_ALL="C.UTF-8", DEBIAN_FRONTEND="noninteractive")
        try:
            p = subprocess.Popen(argv, stdin=subprocess.PIPE if entree is not None else subprocess.DEVNULL,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                 errors="replace", env=env)
        except OSError as e:
            return Resultat(127, "", f"{argv[0]} : {e.strerror}")
        sorties = ([], [])

        def lire(flux, liste):
            for ligne in flux:
                ligne = ligne.rstrip("\n")
                liste.append(ligne)
                if direct:
                    direct(ligne)

        fils = [threading.Thread(target=lire, args=(p.stdout, sorties[0])),
                threading.Thread(target=lire, args=(p.stderr, sorties[1]))]
        for f in fils:
            f.start()
        if entree is not None:
            try:
                p.stdin.write(entree)
                p.stdin.close()
            except OSError:
                pass
        for f in fils:
            f.join()
        p.stdout.close()
        p.stderr.close()
        return Resultat(p.wait(), "\n".join(sorties[0]), "\n".join(sorties[1]), diffuse=direct is not None)

    def executer(self, argv, entree=None, tolerant=False):
        """Annonce et lance une commande ; lève ErreurSysteme si elle échoue (sauf `tolerant`)."""
        argv = [str(a) for a in argv]
        self.dire("commande", " ".join(argv))
        res = self.lancer(argv, entree, lambda l: self.dire("sortie", l))
        if not res.diffuse:
            for ligne in (res.sortie + "\n" + res.erreur).splitlines():
                if ligne.strip():
                    self.dire("sortie", ligne)
        if not res.ok and not tolerant:
            detail = (res.erreur or res.sortie).strip().splitlines()
            raise ErreurSysteme(f"« {' '.join(argv[:3])} » a échoué (code {res.code})"
                                + (f" : {detail[-1]}" if detail else ""))
        return res

    # --- NSS
    def utilisateur(self, cle):
        """Compte résolu par NSS (nom ou UID), ou None."""
        r = self.lancer(["getent", "passwd", str(cle)])
        lignes = r.sortie.strip().splitlines() if r.ok else []
        return lire_utilisateur(lignes[0]) if lignes else None

    def groupe(self, cle):
        """Groupe résolu par NSS (nom ou GID), ou None."""
        r = self.lancer(["getent", "group", str(cle)])
        lignes = r.sortie.strip().splitlines() if r.ok else []
        return lire_groupe(lignes[0]) if lignes else None

    def comptes_locaux(self):
        """Comptes de /etc/passwd : {nom: Utilisateur}."""
        comptes = (lire_utilisateur(l) for l in self.lire("/etc/passwd").splitlines())
        return {u.nom: u for u in comptes if u}

    def groupes_locaux(self):
        """Groupes de /etc/group : {nom: Groupe}."""
        groupes = (lire_groupe(l) for l in self.lire("/etc/group").splitlines())
        return {g.nom: g for g in groupes if g}

    def domaines(self):
        """Domaines AD joints (`realm list --name-only`)."""
        r = self.lancer(["realm", "list", "--name-only"])
        return [l.strip() for l in r.sortie.splitlines() if l.strip()] if r.ok else []

    def service_actif(self, nom):
        return self.lancer(["systemctl", "is-active", nom]).sortie.strip() == "active"

    def unite_activee(self, nom):
        return self.lancer(["systemctl", "is-enabled", nom]).sortie.strip() == "enabled"

    # --- processus
    def processus_uid(self, uid):
        """Processus d'un UID, lus dans <racine>/proc/*/status : [(pid, nom)]."""
        trouves = []
        for pid in self.lister("/proc"):
            if not pid.isdigit():
                continue
            statut = self.lire(f"/proc/{pid}/status")
            m = re.search(r"^Uid:\s+(\d+)\s+(\d+)\s+(\d+)", statut, re.M)
            if m and str(uid) in m.groups():
                nom = re.search(r"^Name:\s*(.*)$", statut, re.M)
                trouves.append((int(pid), nom.group(1) if nom else "?"))
        return trouves

    # --- appelant
    def uid_appelant(self):
        """UID de la personne derrière pkexec ou sudo, sinon l'utilisateur courant."""
        for cle in ("PKEXEC_UID", "SUDO_UID"):
            if self.env.get(cle, "").isdigit():
                return int(self.env[cle])
        return self.uid
