"""Assistant root de Sésame : `sesame-racine [--json] ACTION [options]` (lancé par pkexec)."""
import argparse
import json
import sys

from . import actions, config as cfg, etapes
from .systeme import ErreurSesame, Systeme
from .version import VERSION


class ErreurUsage(Exception):
    """Arguments invalides."""


class Analyseur(argparse.ArgumentParser):
    def error(self, message):
        raise ErreurUsage(message)


class Emetteur:
    """Écrit les événements : une ligne JSON chacun avec --json, du texte lisible sinon."""

    def __init__(self, sortie, erreur, en_json):
        self.sortie, self.erreur, self.en_json = sortie, erreur, en_json

    def evenement(self, type_, texte):
        if self.en_json:
            self._ligne({"type": type_, "texte": texte})
        else:
            prefixe = {"etape": "== ", "commande": "$ ", "sortie": "   ", "avertissement": "Attention : ",
                       "compilation_requise": "Compilation requise : "}[type_]
            print(prefixe + texte, file=self.sortie, flush=True)

    def fin(self, ok, message):
        if self.en_json:
            self._ligne({"type": "fin", "ok": ok, "message": message})
        else:
            print(message, file=self.sortie if ok else self.erreur, flush=True)

    def _ligne(self, donnees):
        print(json.dumps(donnees, ensure_ascii=False), file=self.sortie, flush=True)


def analyseur():
    p = Analyseur(prog="sesame-racine", description="Assistant root de Sésame.")
    p.add_argument("--json", action="store_true", help="un événement JSON par ligne")
    sous = p.add_subparsers(dest="action", required=True, parser_class=Analyseur)
    r = sous.add_parser("rejoindre")
    r.add_argument("--compte", required=True)
    r.add_argument("--nom-machine", required=True)
    r.add_argument("--compte-local")
    r.add_argument("--paquets")
    sous.add_parser("sauvegarde").add_argument("--motif", default="")
    sous.add_parser("secours").add_argument("--nom", default="secours")
    sous.add_parser("nom-machine").add_argument("--nom", required=True)
    c = sous.add_parser("configurer")
    c.add_argument("--compte", required=True)
    c.add_argument("--compte-local")
    sous.add_parser("installer").add_argument("--paquets", required=True)
    for nom in ("quitter-ad", "outils", "noter-premiere-connexion", "desactiver", "etat"):
        sous.add_parser(nom)
    return p


def _lire_ligne(entree):
    """Première ligne de l'entrée standard (mot de passe), sans fin de ligne ; None si elle est vide."""
    return entree.readline().rstrip("\r\n") or None


def _rejoindre(systeme, args, entree):
    return True, actions.rejoindre(systeme, args.compte, args.nom_machine, args.compte_local, args.paquets)


def _secours(systeme, args, entree):
    mot_de_passe = _lire_ligne(entree)
    copier_de = None if mot_de_passe else actions.compte_local_appelant(systeme) or cfg.defauts(systeme).compte_local
    return True, actions.creer_secours(systeme, args.nom, mot_de_passe, copier_de)


def _etat(systeme, args, entree):
    donnees = etapes.etat_complet(systeme)
    systeme.dire("sortie", json.dumps(donnees, ensure_ascii=False) if args.json
                 else json.dumps(donnees, ensure_ascii=False, indent=2))
    return True, "État lu."


ACTIONS = {
    "rejoindre": _rejoindre,
    "sauvegarde": lambda s, a, e: (True, actions.faire_sauvegarde(s, a.motif)),
    "secours": _secours,
    "nom-machine": lambda s, a, e: (True, actions.changer_nom_machine(s, a.nom)),
    "quitter-ad": lambda s, a, e: (True, actions.quitter_ad(s)),
    "outils": lambda s, a, e: (True, actions.installer_outils(s)),
    "installer": lambda s, a, e: (True, actions.installer(s, a.paquets)),
    "configurer": lambda s, a, e: (True, actions.configurer(s, a.compte, a.compte_local)),
    "noter-premiere-connexion": lambda s, a, e: (True, actions.noter_premiere_connexion(s)),
    "desactiver": lambda s, a, e: (True, actions.desactiver(s)),
    "etat": _etat,
}


def main(argv=None, systeme=None, sortie=None, erreur=None, entree=None):
    """Point d'entrée ; renvoie le code de sortie (0 réussi, 1 échec, 2 usage)."""
    argv = list(sys.argv[1:] if argv is None else argv)
    emetteur = Emetteur(sortie or sys.stdout, erreur or sys.stderr, "--json" in argv)
    try:
        args = analyseur().parse_args(argv)
    except ErreurUsage as e:
        emetteur.fin(False, f"Usage : {e}")
        return 2
    except SystemExit as e:  # --help
        return e.code or 0
    systeme = systeme or Systeme()
    systeme.recepteur = emetteur.evenement
    if not systeme.est_root():
        emetteur.fin(False, "Sésame doit être lancé en root (par pkexec).")
        return 1
    try:
        ok, message = ACTIONS[args.action](systeme, args, entree or sys.stdin)
    except ErreurSesame as e:
        ok, message = False, str(e)
    except Exception as e:  # la ligne « fin » doit toujours exister
        ok, message = False, f"Erreur inattendue : {e!r}"
    emetteur.fin(ok, message)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
