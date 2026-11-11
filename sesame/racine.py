"""Assistant root de Sésame : `sesame-racine [--json] ACTION [options]` (lancé par pkexec)."""
import argparse
import json
import sys

from . import actions, config as cfg, etapes, reprise
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
            prefixe = {"etape": "== ", "commande": "$ ", "sortie": "   ", "avertissement": "Attention : "}[type_]
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
    sous.add_parser("sauvegarde").add_argument("--motif", default="")
    sous.add_parser("secours").add_argument("--nom", default="secours")
    sous.add_parser("quitter-ad")
    sous.add_parser("installer")
    c = sous.add_parser("configurer")
    c.add_argument("--locataire", required=True)
    c.add_argument("--client", required=True)
    c.add_argument("--compte", required=True)
    c.add_argument("--compte-local")
    c.add_argument("--secours")
    c.add_argument("--groupes")
    r = sous.add_parser("reprise")
    mode = r.add_mutually_exclusive_group(required=True)
    for nom in ("maintenant", "au-demarrage", "annuler-programmation", "execution-demarrage"):
        mode.add_argument("--" + nom, action="store_const", const=nom, dest="mode")
    for nom in ("annuler-reprise", "desactiver", "noter-verification", "etat"):
        sous.add_parser(nom)
    return p


def _lire_mot_de_passe(entree):
    ligne = entree.readline()
    return ligne.rstrip("\r\n") or None


def _secours(systeme, args, entree):
    return True, actions.creer_secours(systeme, args.nom, _lire_mot_de_passe(entree))


def _configurer(systeme, args, entree):
    groupes = cfg.decouper_groupes(args.groupes) if args.groupes is not None else None
    c = actions.construire_config(systeme, args.locataire, args.client, args.compte, args.compte_local,
                                  args.secours, groupes)
    return True, actions.configurer(systeme, c)


def _reprise(systeme, args, entree):
    if args.mode == "annuler-programmation":
        return True, reprise.annuler_programmation(systeme)
    if args.mode == "execution-demarrage":
        return reprise.executer_demarrage(systeme)
    return actions.reprendre(systeme, args.mode)


def _etat(systeme, args, entree):
    donnees = etapes.etat_complet(systeme)
    systeme.dire("sortie", json.dumps(donnees, ensure_ascii=False) if args.json
                 else json.dumps(donnees, ensure_ascii=False, indent=2))
    return True, "État lu."


ACTIONS = {
    "sauvegarde": lambda s, a, e: (True, actions.faire_sauvegarde(s, a.motif)),
    "secours": _secours,
    "quitter-ad": lambda s, a, e: (True, actions.quitter_ad(s)),
    "installer": lambda s, a, e: (True, actions.installer(s)),
    "configurer": _configurer,
    "reprise": _reprise,
    "annuler-reprise": lambda s, a, e: reprise.annuler(s),
    "desactiver": lambda s, a, e: (True, actions.desactiver(s)),
    "noter-verification": lambda s, a, e: (True, actions.noter_verification(s)),
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
    au_demarrage = args.action == "reprise" and args.mode == "execution-demarrage"
    return 0 if ok or au_demarrage else 1  # un échec ne doit jamais bloquer le démarrage


if __name__ == "__main__":
    sys.exit(main())
