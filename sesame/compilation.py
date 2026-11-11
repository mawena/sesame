"""Compilation de Himmelblau (branche stable-4.x) sur le poste, sous l'utilisateur : jamais root, jamais pkexec ni sudo.

Tous les processus passent par `lancer(argv, cwd=None, rappel=None) -> (code, sortie)`, que les tests remplacent.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from .systeme import ErreurSesame

DEPOT_GIT = "https://github.com/himmelblau-idm/himmelblau.git"
BRANCHE = "stable-4.x"
CIBLE = "ubuntu24.04"
IMAGE = "sesame-himmelblau-ubuntu24.04"
PAQUETS = ("himmelblau", "pam-himmelblau", "nss-himmelblau")
RAM_GO = 6
COEURS = 4
FICHIER_ETAT = "sesame-compilation.json"

CODE_A_METTRE_A_JOUR = 10
LIGNES_UTILES = 15
INDICE_OUTILS = "lancez d'abord l'étape « Installer les outils de compilation »"
MOTIFS_RESEAU = re.compile(
    r"could not resolve host|temporary failure in name resolution|name or service not known|no such host|"
    r"unable to access|failed to connect|connection (timed out|refused|reset)|network is unreachable|"
    r"dial tcp|error sending request|failed to download|unable to connect|tls handshake|i/o timeout|"
    r"could not connect|failed to fetch|toomanyrequests|registry-1\.docker\.io|index\.crates\.io", re.I)


class ErreurCompilation(ErreurSesame):
    """La compilation de Himmelblau a échoué ; le message est destiné à l'utilisateur."""


def dossier_par_defaut():
    """~/.local/share/sesame/himmelblau (ou sous $XDG_DATA_HOME)."""
    base = os.environ.get("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"), ".local", "share")
    return os.path.join(base, "sesame", "himmelblau")


def lancer(argv, cwd=None, rappel=None):
    """Lance un processus ; relaie chaque ligne de sortie à `rappel` en direct. Renvoie (code, sortie)."""
    p = subprocess.Popen(argv, cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, text=True, errors="replace", bufsize=1)
    lignes = []
    for ligne in p.stdout:
        ligne = ligne.rstrip("\n")
        lignes.append(ligne)
        if rappel:
            rappel(ligne)
    p.stdout.close()
    return p.wait(), "\n".join(lignes)


def _queue(sortie, n=LIGNES_UTILES):
    lignes = [l for l in (sortie or "").splitlines() if l.strip()]
    return "\n".join(lignes[-n:])


def _executer(argv, lancer_, cwd=None, rappel=None, outil=None, etape=""):
    """Lance une commande ; transforme un outil absent ou un échec en ErreurCompilation."""
    try:
        code, sortie = lancer_(argv, cwd=cwd, rappel=rappel)
    except FileNotFoundError:
        nom = outil or argv[0]
        raise ErreurCompilation(f"« {nom} » est introuvable : {INDICE_OUTILS}.") from None
    if code == 0:
        return sortie
    if code == 127 and outil:
        raise ErreurCompilation(f"« {outil} » est introuvable : {INDICE_OUTILS}.")
    if MOTIFS_RESEAU.search(sortie or ""):
        raise ErreurCompilation(
            f"{etape} : le réseau a échoué (GitHub, Docker Hub ou crates.io injoignable). "
            f"Vérifiez la connexion à Internet puis relancez.\n{_queue(sortie)}")
    raise ErreurCompilation(f"{etape} a échoué (code {code}).\n{_queue(sortie)}")


def commit_distant(lancer_=None):
    """Commit de tête de stable-4.x sur GitHub, ou None s'il est introuvable."""
    lancer_ = lancer_ or lancer
    try:
        r = lancer_(["git", "ls-remote", DEPOT_GIT, f"refs/heads/{BRANCHE}"])
    except (FileNotFoundError, OSError, subprocess.SubprocessError):
        return None
    if hasattr(r, "returncode"):  # un subprocess.CompletedProcess est accepté aussi
        code, sortie = r.returncode, r.stdout or ""
    else:
        code, sortie = r
    if code != 0:
        return None
    for ligne in sortie.splitlines():
        p = ligne.split()
        if len(p) >= 2 and re.fullmatch(r"[0-9a-f]{40}", p[0]) and p[1] == f"refs/heads/{BRANCHE}":
            return p[0]
    return None


def _nom_paquet(fichier):
    """himmelblau_4.0.1_amd64.deb -> himmelblau."""
    return os.path.basename(fichier).split("_", 1)[0]


def etat(dossier):
    """{compile, commit, date, paquets: {nom: fichier}} d'après packaging/sesame-compilation.json et les .deb présents."""
    res = {"compile": False, "commit": "", "date": "", "paquets": {}}
    pack = Path(dossier) / "packaging"
    try:
        donnees = json.loads((pack / FICHIER_ETAT).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return res
    if not isinstance(donnees, dict):
        return res
    res["commit"] = str(donnees.get("commit") or "")
    res["date"] = str(donnees.get("date") or "")
    for nom, fichier in (donnees.get("paquets") or {}).items():
        if (pack / str(fichier)).is_file():
            res["paquets"][nom] = str(fichier)
    res["compile"] = bool(res["commit"]) and all(p in res["paquets"] for p in PAQUETS)
    return res


def a_jour(dossier, lancer_=None):
    """Vrai si le commit compilé est celui de stable-4.x sur GitHub."""
    e = etat(dossier)
    if not e["compile"]:
        return False
    distant = commit_distant(lancer_)
    return bool(distant) and distant == e["commit"]


def compiler(dossier, lancer=lancer, rappel=None, coeurs=COEURS, etape=None):
    """Clone ou met à jour Himmelblau, le compile dans un conteneur podman et range les .deb dans packaging/.

    `rappel(ligne)` reçoit la sortie des commandes ; `etape(texte)` les étapes (par défaut : `rappel`).
    Renvoie le dict de `etat(dossier)`. Lève ErreurCompilation.
    """
    dossier = str(dossier)
    annoncer = etape or rappel or (lambda texte: None)

    src = Path(dossier)

    annoncer(f"Téléchargement du code de Himmelblau ({BRANCHE})")
    if (src / ".git").is_dir():
        _executer(["git", "fetch", "--depth", "1", "origin", BRANCHE], lancer, dossier, rappel, "git",
                  "Le téléchargement du code de Himmelblau")
        _executer(["git", "reset", "--hard", "FETCH_HEAD"], lancer, dossier, rappel, "git",
                  "La mise à jour du code de Himmelblau")
    else:
        src.parent.mkdir(parents=True, exist_ok=True)
        _executer(["git", "clone", "--depth", "1", "--branch", BRANCHE, DEPOT_GIT, dossier], lancer,
                  str(src.parent), rappel, "git", "Le téléchargement du code de Himmelblau")
    sortie = _executer(["git", "rev-parse", "HEAD"], lancer, dossier, None, "git", "La lecture du commit")
    commit = sortie.strip().splitlines()[-1].strip() if sortie.strip() else ""
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ErreurCompilation("Impossible de lire le commit du code téléchargé de Himmelblau.")

    annoncer("Préparation du conteneur de compilation")
    _executer(["python3", "scripts/gen_dockerfiles.py", "--out", "./images/"], lancer, dossier, rappel,
              "python3", "La génération des Dockerfile")
    _executer(["podman", "build", "-t", IMAGE, "-f", f"images/Dockerfile.{CIBLE}", "."], lancer, dossier, rappel,
              "podman", "La préparation du conteneur de compilation")

    annoncer("Compilation (environ 30 à 60 min)")
    cible = src / "target" / CIBLE
    cible.mkdir(parents=True, exist_ok=True)
    _executer(["podman", "run", "--rm", "--security-opt", "label=disable", "-e", f"CARGO_BUILD_JOBS={int(coeurs)}",
               "-v", f"{dossier}:/himmelblau", "-v", f"{cible}:/himmelblau/target", IMAGE],
              lancer, dossier, rappel, "podman", "La compilation de Himmelblau")

    pack = src / "packaging"
    pack.mkdir(parents=True, exist_ok=True)
    for ancien in pack.glob("*.deb"):
        ancien.unlink()
    for debs in sorted((cible / "debian").glob("*.deb")):
        shutil.copy2(debs, pack / debs.name)
    paquets = {}
    for f in sorted(pack.glob("*.deb")):
        paquets[_nom_paquet(f.name)] = f.name
    manquants = [p for p in PAQUETS if p not in paquets]
    if manquants:
        raise ErreurCompilation(
            "La compilation s'est terminée mais il manque des paquets : " + ", ".join(manquants) +
            f". Regardez les dernières lignes de la compilation, puis relancez.")
    (pack / FICHIER_ETAT).write_text(json.dumps(
        {"commit": commit, "branche": BRANCHE, "date": datetime.now().astimezone().isoformat(timespec="seconds"),
         "paquets": paquets}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    annoncer("Paquets prêts")
    return etat(dossier)


def commande_file(dossier, quoi=shutil.which):
    """Commande `gagarine file …` qui lance la compilation, ou None si gagarine est absent."""
    if not quoi("gagarine"):
        return None
    return ["gagarine", "file", "himmelblau compilation", str(RAM_GO), str(COEURS), "--",
            *commande_directe(dossier)]


def commande_directe(dossier):
    """argv complet de la compilation directe.

    PYTHONPATH est toujours donné : le processus lancé (par la file Gagarine notamment) n'hérite pas du sys.path du
    programme qui le demande, et le paquet installé place `sesame` dans /usr/share/sesame (bogue de la 2.0.0)."""
    parent = str(Path(__file__).resolve().parent.parent)
    autres = [p for p in (os.environ.get("PYTHONPATH") or "").split(os.pathsep) if p and p != parent]
    return ["env", "PYTHONPATH=" + os.pathsep.join([parent] + autres),
            sys.executable, "-m", "sesame.compilation", "--directe", "--dossier", str(dossier)]


def main(argv=None, lancer_=None, sortie=None, quoi=shutil.which):
    """python3 -m sesame.compilation [--directe] [--dossier D] [--json] [--verifier-a-jour]."""
    p = argparse.ArgumentParser(prog="python3 -m sesame.compilation",
                                description="Compile Himmelblau (stable-4.x) sur ce poste, sous votre compte.")
    p.add_argument("--directe", action="store_true", help="compiler tout de suite, sans passer par la file Gagarine")
    p.add_argument("--dossier", default=None, help="dossier de compilation (défaut : ~/.local/share/sesame/himmelblau)")
    p.add_argument("--json", action="store_true", help="une ligne JSON par événement")
    p.add_argument("--verifier-a-jour", action="store_true", help="dit si une nouvelle version stable est disponible")
    a = p.parse_args(argv)
    lancer_ = lancer_ or lancer
    sortie = sortie or sys.stdout
    dossier = a.dossier or dossier_par_defaut()

    def emettre(type_, **champs):
        if a.json:
            print(json.dumps({"type": type_, **champs}, ensure_ascii=False), file=sortie, flush=True)
        elif type_ == "fin":
            print(champs.get("message", ""), file=sortie, flush=True)
        else:
            print(("== " if type_ == "etape" else "") + champs.get("texte", ""), file=sortie, flush=True)

    if a.verifier_a_jour:
        e = etat(dossier)
        distant = commit_distant(lancer_)
        if distant is None:
            emettre("fin", ok=False, message="Impossible de joindre GitHub pour vérifier la version.")
            return 1
        if e["compile"] and e["commit"] == distant:
            emettre("fin", ok=True, a_jour=True, commit=distant, message="Himmelblau compilé est à jour.")
            return 0
        emettre("fin", ok=True, a_jour=False, commit=distant, compile=e["compile"],
                message="Une nouvelle version stable de Himmelblau est disponible."
                if e["compile"] else "Himmelblau n'est pas encore compilé.")
        return CODE_A_METTRE_A_JOUR

    if not a.directe:
        cmd = commande_file(dossier, quoi)
        if cmd:
            if a.json:
                cmd += ["--json"]
            return lancer_(cmd, rappel=lambda l: print(l, file=sortie, flush=True))[0]

    def rappel(ligne):
        emettre("sortie", texte=ligne)

    try:
        e = compiler(dossier, lancer=lancer_, rappel=rappel, etape=lambda texte: emettre("etape", texte=texte))
    except ErreurSesame as exc:
        emettre("fin", ok=False, message=str(exc))
        return 1
    emettre("fin", ok=True, message="Himmelblau est compilé.", commit=e["commit"], paquets=e["paquets"],
            dossier=str(Path(dossier) / "packaging"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
