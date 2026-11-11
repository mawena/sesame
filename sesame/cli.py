"""Ligne de commande `sesame` : mêmes étapes que l'assistant graphique (Sésame 2.0.0, Himmelblau)."""
import argparse
import getpass
import json
import os
import socket
import subprocess
import sys

from . import config as cfg, etapes, verification
try:
    from . import compilation
except ImportError:  # module du cœur écrit en parallèle
    compilation = None
from .systeme import ErreurSesame, Systeme
from .version import VERSION

SYMBOLES = {"fait": "✓", "a_faire": "·", "sans_objet": "–", "programmee": "⏲", "bloquee": "✗", "inconnu": "?"}
RACINE_INSTALLEE = "/usr/libexec/sesame/sesame-racine"
PREMIERE_CONNEXION = (
    "Première connexion : déconnectez-vous, choisissez votre compte à l'écran d'accueil, tapez le mot de passe Entra\n"
    "de votre adresse pro et validez sur le téléphone. Le poste est inscrit dans Entra à cette première connexion ;\n"
    "vous choisissez ensuite un code PIN (Windows Hello) pour les connexions suivantes.\n"
    "Le trousseau GNOME (« Connexion ») reste chiffré avec l'ancien mot de passe local : changez-le dans\n"
    "« Mots de passe et clés » pour y mettre le mot de passe Entra, sinon les applications le redemandent.")


def chemin_racine():
    """Assistant root : celui du système si Sésame est installé, sinon `libexec/sesame-racine` du dépôt."""
    ici = os.path.dirname(os.path.realpath(__file__))
    if ici.startswith("/usr/share/sesame"):
        return RACINE_INSTALLEE
    return os.path.join(os.path.dirname(ici), "libexec", "sesame-racine")


def commande_racine(args, deja_root=None):
    """Commande qui lance l'assistant root : pkexec, ou appel direct si l'on est déjà root (jamais sudo)."""
    deja_root = os.geteuid() == 0 if deja_root is None else deja_root
    return ([] if deja_root else ["pkexec"]) + [chemin_racine()] + list(args)


def lancer_racine(args, entree=None, lanceur=subprocess.run):
    """Lance une action root ; renvoie le code de sortie. `entree` passe par stdin (jamais en argument)."""
    res = lanceur(commande_racine(args), input=entree, text=True if entree is not None else None)
    if res.returncode in (126, 127):
        print("Authentification annulée ou impossible.", file=sys.stderr)
    return res.returncode


# --- ce que le cœur fournit (isolé ici : le cœur évolue en parallèle)
def _vrai(fonction, valeur):
    """Résultat d'un validateur du cœur, qu'il renvoie un booléen ou lève une erreur."""
    try:
        return fonction(valeur) is not False
    except (ValueError, TypeError, ErreurSesame):
        return False


def valider_compte(valeur):
    return _vrai(cfg.valider_upn, valeur)


def valider_nom_machine(valeur):
    return _vrai(cfg.valider_nom_machine, valeur)


def normaliser_compte(valeur):
    return getattr(cfg, "normaliser_upn", lambda v: v.strip().lower())(valeur)


def defauts(systeme):
    return cfg.charger(systeme) or cfg.defauts(systeme)


def etat_complet(systeme):
    return etapes.etat_complet(systeme)


def nom_hote():
    return socket.gethostname().split(".")[0]


def utilisateur_courant():
    return getpass.getuser()


# --- affichage
def afficher_etat(systeme, en_json, sortie=None):
    sortie = sortie or sys.stdout
    donnees = etat_complet(systeme)
    if en_json:
        print(json.dumps(donnees, ensure_ascii=False, indent=2), file=sortie)
        return 0
    for i, e in enumerate(donnees["etapes"], 1):
        print(f"{SYMBOLES[e['statut']]} {i}. {e['titre']} : {e['detail']}", file=sortie)
    suivante = next((e for e in donnees["etapes"] if e["id"] == donnees["suivante"]), None)
    print(f"\nÉtape suivante : {suivante['titre']}" if suivante else "\nTout est en place.", file=sortie)
    return 0


def verifier(systeme, sortie=None):
    """Affiche les contrôles (sans root) ; code 0 si tout est bon."""
    sortie = sortie or sys.stdout
    controles = verification.controler(systeme, cfg.charger(systeme))
    for ok, texte in controles:
        print(f"{'✓' if ok else '✗'} {texte}", file=sortie)
    return 0 if all(ok for ok, _ in controles) else 1


# --- saisie
def demander(texte, defaut="", valider=None, saisie=input):
    """Pose une question avec une valeur par défaut, jusqu'à obtenir une valeur valide."""
    while True:
        reponse = saisie(f"{texte}" + (f" [{defaut}]" if defaut else "") + " : ").strip() or defaut
        if valider is None or valider(reponse):
            return reponse
        print("Valeur invalide.", file=sys.stderr)


def compte_et_local(systeme, args, saisie, utilisateur):
    """Adresse pro et compte local, demandés s'ils manquent."""
    d = defauts(systeme)
    compte = args.compte or demander("Adresse pro (compte Entra)", getattr(d, "compte", ""), valider_compte, saisie)
    if not valider_compte(compte):
        print("Adresse invalide.", file=sys.stderr)
        return None, None
    local = getattr(args, "compte_local", None) or utilisateur()
    return normaliser_compte(compte), local


def evenements_racine(args, lanceur):
    """Lance l'assistant root en JSON, relaie les événements lisibles ; renvoie (code, types d'événements vus)."""
    res = lanceur(commande_racine(["--json"] + list(args)), input=None, text=True, stdout=subprocess.PIPE)
    vus = set()
    for ligne in (getattr(res, "stdout", None) or "").splitlines():
        try:
            e = json.loads(ligne)
        except ValueError:
            print(ligne)
            continue
        vus.add(e.get("type"))
        if e.get("type") == "etape":
            print("== " + e.get("texte", ""))
        elif e.get("type") == "sortie":
            print("   " + e.get("texte", ""))
        elif e.get("type") == "avertissement":
            print("Attention : " + e.get("texte", ""), file=sys.stderr)
        elif e.get("type") == "fin":
            print(e.get("message", ""), file=sys.stdout if e.get("ok") else sys.stderr)
    if res.returncode in (126, 127):
        print("Authentification annulée ou impossible.", file=sys.stderr)
    return res.returncode, vus


def dossier_compilation():
    return compilation.dossier_par_defaut()


def dossier_paquets():
    return os.path.join(dossier_compilation(), "packaging")


def deja_compile():
    """Vrai si les paquets de Himmelblau sont déjà compilés dans le dossier de compilation."""
    try:
        return bool(compilation.etat(dossier_compilation()).get("compile"))
    except Exception:  # module absent ou incomplet, fichier illisible : on compilera
        return False


def compiler(lanceur=subprocess.run):
    """Compile Himmelblau sous l'utilisateur (jamais root) : par la file Gagarine si elle est là."""
    dossier = dossier_compilation()
    cmd = compilation.commande_file(dossier) or compilation.commande_directe(dossier)
    print("Compilation de Himmelblau (environ 30 à 60 minutes, ~6 Go de RAM)…")
    return lanceur(list(cmd)).returncode


def rejoindre(systeme, args, saisie=input, lanceur=subprocess.run, utilisateur=utilisateur_courant, hote=nom_hote):
    """Demande ce qui manque, prépare le poste ; compile Himmelblau si besoin ; installe et configure."""
    compte, local = compte_et_local(systeme, args, saisie, utilisateur)
    if compte is None:
        return 2
    nom = args.nom_machine or demander("Nom de la machine", hote(), valider_nom_machine, saisie)
    if not valider_nom_machine(nom):
        print("Nom de machine invalide (1 à 15 caractères : lettres, chiffres, tirets).", file=sys.stderr)
        return 2
    cmd = ["rejoindre", "--compte", compte, "--nom-machine", nom, "--compte-local", local]
    if deja_compile():  # Himmelblau déjà compilé : on reprend ses paquets sans recompiler
        return evenements_racine(cmd + ["--paquets", dossier_paquets()], lanceur)[0]
    code, vus = evenements_racine(cmd, lanceur)
    if code != 0 or "compilation_requise" not in vus:
        return code
    code = compiler(lanceur)
    if code != 0:
        print("La compilation de Himmelblau a échoué ; relancez « sesame rejoindre » pour reprendre.", file=sys.stderr)
        return code
    return evenements_racine(cmd + ["--paquets", dossier_paquets()], lanceur)[0]


def installer(lanceur=subprocess.run):
    return lancer_racine(["installer", "--paquets", dossier_paquets()], lanceur=lanceur)


def mettre_a_jour(args, lanceur=subprocess.run):
    """Recompile si la branche stable a avancé (ou avec --forcer), puis réinstalle."""
    if not args.forcer and compilation.a_jour(dossier_compilation()):
        print("Himmelblau est à jour.")
        return 0
    code = compiler(lanceur)
    return code if code != 0 else installer(lanceur)


def configurer(systeme, args, saisie=input, lanceur=subprocess.run, utilisateur=utilisateur_courant):
    compte, local = compte_et_local(systeme, args, saisie, utilisateur)
    if compte is None:
        return 2
    return lancer_racine(["configurer", "--compte", compte, "--compte-local", local], lanceur=lanceur)


def nom_machine(systeme, args, saisie=input, lanceur=subprocess.run, hote=nom_hote):
    nom = args.nom or demander("Nom de la machine", hote(), valider_nom_machine, saisie)
    if not valider_nom_machine(nom):
        print("Nom de machine invalide (1 à 15 caractères : lettres, chiffres, tirets).", file=sys.stderr)
        return 2
    return lancer_racine(["nom-machine", "--nom", nom], lanceur=lanceur)


def secours(args, mot_de_passe=getpass.getpass, lanceur=subprocess.run):
    """Mot de passe du compte de secours sur stdin ; `--copier` reprend le mot de passe actuel (entrée vide)."""
    if args.copier:
        return lancer_racine(["secours", "--nom", args.nom], entree="\n", lanceur=lanceur)
    mdp = mot_de_passe("Mot de passe du compte de secours : ")
    if mdp != mot_de_passe("Confirmez le mot de passe : "):
        print("Les deux mots de passe sont différents.", file=sys.stderr)
        return 1
    if len(mdp) < 8:
        print("Le mot de passe doit faire au moins 8 caractères.", file=sys.stderr)
        return 1
    return lancer_racine(["secours", "--nom", args.nom], entree=mdp + "\n", lanceur=lanceur)


def premiere_connexion(lanceur=subprocess.run):
    print(PREMIERE_CONNEXION)
    return lancer_racine(["noter-premiere-connexion"], lanceur=lanceur)


def analyseur():
    p = argparse.ArgumentParser(prog="sesame", description="Relie ce poste Ubuntu à Microsoft Entra ID avec "
                                "Himmelblau, comme un PC Windows : adresse pro et nom de la machine.")
    p.add_argument("--json", action="store_true", dest="json_global", help=argparse.SUPPRESS)
    sous = p.add_subparsers(dest="commande", title="commandes", metavar="COMMANDE")
    sous.add_parser("etat", help="état des étapes").add_argument("--json", action="store_true",
                                                                 help="écrit l'état en JSON")
    r = sous.add_parser("rejoindre", help="fait tout : de la sauvegarde à la configuration")
    r.add_argument("--compte", metavar="ADRESSE", help="adresse pro (compte Entra)")
    r.add_argument("--nom-machine", metavar="NOM", help="nom de la machine (défaut : nom d'hôte actuel)")
    for nom, aide in (("sauvegarde", "sauvegarde la configuration"),
                      ("quitter-ad", "quitte le domaine Active Directory"),
                      ("outils", "installe les outils de compilation (podman, git…)"),
                      ("compiler", "compile Himmelblau (sous votre compte, sans root)"),
                      ("installer", "installe Himmelblau compilé"),
                      ("desactiver", "coupe la connexion Entra sans rien désinstaller"),
                      ("verifier", "contrôles, sans root"),
                      ("premiere-connexion", "explique la première connexion et la note"),
                      ("version", "affiche la version")):
        sous.add_parser(nom, help=aide)
    s = sous.add_parser("secours", help="crée le compte de secours")
    s.add_argument("--nom", default="secours", help="nom du compte (défaut : secours)")
    s.add_argument("--copier", action="store_true", help="reprend le mot de passe Ubuntu actuel")
    m = sous.add_parser("mettre-a-jour", help="recompile Himmelblau si la branche stable a avancé, puis réinstalle")
    m.add_argument("--forcer", action="store_true", help="recompile même si Himmelblau est à jour")
    n = sous.add_parser("nom-machine", help="change le nom de la machine")
    n.add_argument("nom", nargs="?", metavar="NOM")
    c = sous.add_parser("configurer", help="relie votre compte local à Entra")
    c.add_argument("--compte", metavar="ADRESSE", help="adresse pro (compte Entra)")
    c.add_argument("--compte-local", metavar="NOM", help="compte local à relier (défaut : utilisateur courant)")
    return p


def main(argv=None, systeme=None, saisie=input, mot_de_passe=getpass.getpass, lanceur=subprocess.run,
         utilisateur=utilisateur_courant, hote=nom_hote):
    """Point d'entrée ; renvoie le code de sortie."""
    args = analyseur().parse_args(sys.argv[1:] if argv is None else argv)
    commande = args.commande or "etat"
    if commande == "version":
        print(f"Sésame {VERSION}")
        return 0
    systeme = systeme or Systeme()
    if commande == "etat":
        return afficher_etat(systeme, getattr(args, "json", False) or args.json_global)
    if commande == "verifier":
        return verifier(systeme)
    if commande == "rejoindre":
        return rejoindre(systeme, args, saisie, lanceur, utilisateur, hote)
    if commande == "configurer":
        return configurer(systeme, args, saisie, lanceur, utilisateur)
    if commande == "nom-machine":
        return nom_machine(systeme, args, saisie, lanceur, hote)
    if commande == "compiler":
        return compiler(lanceur)
    if commande == "installer":
        return installer(lanceur)
    if commande == "mettre-a-jour":
        return mettre_a_jour(args, lanceur)
    if commande == "secours":
        return secours(args, mot_de_passe, lanceur)
    if commande == "premiere-connexion":
        return premiere_connexion(lanceur)
    return lancer_racine([commande], lanceur=lanceur)


if __name__ == "__main__":
    sys.exit(main())
