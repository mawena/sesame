"""Ligne de commande `sesame` : mêmes étapes que l'assistant graphique."""
import argparse
import getpass
import json
import os
import subprocess
import sys

from . import config as cfg, etapes, guide, verification
from .systeme import Systeme
from .version import VERSION

SYMBOLES = {"fait": "✓", "a_faire": "·", "sans_objet": "–", "programmee": "⏲", "bloquee": "✗", "inconnu": "?"}
RACINE_INSTALLEE = "/usr/libexec/sesame/sesame-racine"


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
    """Lance une action root ; renvoie le code de sortie. `entree` passe par stdin."""
    res = lanceur(commande_racine(args), input=entree, text=True if entree is not None else None)
    if res.returncode in (126, 127):
        print("Authentification annulée ou impossible.", file=sys.stderr)
    return res.returncode


# --- affichage
def afficher_etat(systeme, en_json, sortie=None):
    sortie = sortie or sys.stdout
    donnees = etapes.etat_complet(systeme)
    if en_json:
        print(json.dumps(donnees, ensure_ascii=False, indent=2), file=sortie)
        return 0
    for i, e in enumerate(donnees["etapes"], 1):
        print(f"{SYMBOLES[e['statut']]} {i}. {e['titre']} : {e['detail']}", file=sortie)
    suivante = next((e for e in donnees["etapes"] if e["id"] == donnees["suivante"]), None)
    print(f"\nÉtape suivante : {suivante['titre']}" if suivante else "\nTout est en place.", file=sortie)
    return 0


def verifier(systeme, sortie=None, lanceur=subprocess.run):
    """Affiche les contrôles ; si tout est bon et qu'on est connecté en compte Entra, le note."""
    sortie = sortie or sys.stdout
    c = cfg.charger(systeme)
    controles = verification.controler(systeme, c)
    for ok, texte in controles:
        print(f"{'✓' if ok else '✗'} {texte}", file=sortie)
    tout_bon = all(ok for ok, _ in controles)
    if tout_bon and verification.est_connecte(systeme, c):
        lancer_racine(["noter-verification"], lanceur=lanceur)
    return 0 if tout_bon else 1


# --- saisie
def demander(texte, defaut="", valider=None, saisie=input):
    """Pose une question avec une valeur par défaut, jusqu'à obtenir une valeur valide."""
    while True:
        reponse = saisie(f"{texte}" + (f" [{defaut}]" if defaut else "") + " : ").strip() or defaut
        if valider is None or valider(reponse):
            return reponse
        print("Valeur invalide.", file=sys.stderr)


def configurer(systeme, args, saisie=input, lanceur=subprocess.run):
    """Demande les valeurs manquantes (avec les valeurs détectées) puis lance l'action root."""
    d = cfg.charger(systeme) or cfg.defauts(systeme)
    locataire = args.locataire or demander("ID du locataire (annuaire)", d.locataire, cfg.valider_guid, saisie)
    client = args.client or demander("ID client (application)", d.client, cfg.valider_guid, saisie)
    compte = args.compte or demander("Compte Entra (UPN)", d.compte, cfg.valider_upn, saisie)
    local = args.compte_local or demander("Compte local à reprendre", d.compte_local, cfg.valider_nom, saisie)
    groupes = args.groupes if args.groupes is not None else demander("Groupes à redonner (séparés par des virgules)",
                                                                      ",".join(d.groupes), None, saisie)
    cmd = ["configurer", "--locataire", locataire, "--client", client, "--compte", cfg.normaliser_upn(compte),
           "--compte-local", local, "--groupes", groupes]
    if args.secours:
        cmd += ["--secours", args.secours]
    return lancer_racine(cmd, lanceur=lanceur)


def secours(args, mot_de_passe=getpass.getpass, lanceur=subprocess.run):
    """Demande le mot de passe deux fois et le passe à l'assistant root par stdin."""
    mdp = mot_de_passe("Mot de passe du compte de secours : ")
    if mdp != mot_de_passe("Confirmez le mot de passe : "):
        print("Les deux mots de passe sont différents.", file=sys.stderr)
        return 1
    if len(mdp) < 8:
        print("Le mot de passe doit faire au moins 8 caractères.", file=sys.stderr)
        return 1
    return lancer_racine(["secours", "--nom", args.nom], entree=mdp + "\n", lanceur=lanceur)


def reprise(args, saisie=input, lanceur=subprocess.run):
    mode = "annuler-programmation" if args.annuler_programmation else \
        "maintenant" if args.maintenant else "au-demarrage"
    if mode != "annuler-programmation" and not args.oui:
        print("Le compte Entra va reprendre le compte local : UID, dossier, groupes, crontab.\n"
              "Le compte local sera supprimé, pas son dossier. Une sauvegarde est faite ; la reprise s'annule\n"
              "toute seule en cas d'échec (« sesame annuler-reprise » à la main).")
        if saisie("Continuer ? Tapez OUI : ").strip() != "OUI":
            print("Annulé.")
            return 1
    return lancer_racine(["reprise", "--" + mode], lanceur=lanceur)


def analyseur():
    p = argparse.ArgumentParser(prog="sesame", description="Connecte ce poste à Microsoft Entra ID (authd).")
    p.add_argument("--json", action="store_true", dest="json_global", help=argparse.SUPPRESS)
    sous = p.add_subparsers(dest="commande")
    sous.add_parser("etat", help="état des étapes").add_argument("--json", action="store_true")
    for nom, aide in (("sauvegarde", "sauvegarde la configuration"), ("quitter-ad", "quitte le domaine Active Directory"),
                      ("installer", "installe authd et le module Entra"), ("annuler-reprise", "annule la reprise"),
                      ("desactiver", "coupe la connexion Entra sans rien désinstaller"),
                      ("verifier", "contrôles, sans root"), ("portail", "explique la création de l'application Entra"),
                      ("version", "affiche la version")):
        sous.add_parser(nom, help=aide)
    s = sous.add_parser("secours", help="crée le compte de secours")
    s.add_argument("--nom", default="secours")
    c = sous.add_parser("configurer", help="configure la connexion Entra")
    for opt in ("locataire", "client", "compte", "compte-local", "secours", "groupes"):
        c.add_argument("--" + opt)
    r = sous.add_parser("reprise", help="le compte Entra reprend le compte local")
    g = r.add_mutually_exclusive_group()
    g.add_argument("--maintenant", action="store_true")
    g.add_argument("--au-demarrage", action="store_true")
    g.add_argument("--annuler-programmation", action="store_true")
    r.add_argument("--oui", action="store_true", help="ne pas demander de confirmation")
    return p


def main(argv=None, systeme=None, saisie=input, mot_de_passe=getpass.getpass, lanceur=subprocess.run):
    """Point d'entrée ; renvoie le code de sortie."""
    args = analyseur().parse_args(sys.argv[1:] if argv is None else argv)
    systeme = systeme or Systeme()
    commande = args.commande or "etat"
    if commande == "version":
        print(f"Sésame {VERSION}")
        return 0
    if commande == "portail":
        print(guide.texte_portail(), end="")
        return 0
    if commande == "etat":
        return afficher_etat(systeme, getattr(args, "json", False) or args.json_global)
    if commande == "verifier":
        return verifier(systeme, lanceur=lanceur)
    if commande == "configurer":
        return configurer(systeme, args, saisie, lanceur)
    if commande == "secours":
        return secours(args, mot_de_passe, lanceur)
    if commande == "reprise":
        return reprise(args, saisie, lanceur)
    if commande == "sauvegarde":
        return lancer_racine(["sauvegarde"], lanceur=lanceur)
    return lancer_racine([commande], lanceur=lanceur)


if __name__ == "__main__":
    sys.exit(main())
