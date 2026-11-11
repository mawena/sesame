"""/var/lib/sesame/etat.json : ce que Sésame a fait et quand (sans secret)."""
from . import chemins


def lire(systeme):
    donnees = systeme.lire_json(chemins.ETAT_JSON, {})
    return donnees if isinstance(donnees, dict) else {}


def noter(systeme, cle, valeur):
    """Enregistre `valeur` sous `cle`."""
    donnees = lire(systeme)
    donnees[cle] = valeur
    systeme.ecrire_json(chemins.ETAT_JSON, donnees, 0o644)


def retirer(systeme, cle):
    donnees = lire(systeme)
    if cle in donnees:
        del donnees[cle]
        systeme.ecrire_json(chemins.ETAT_JSON, donnees, 0o644)


def ajouter_sauvegarde(systeme, chemin, motif):
    donnees = lire(systeme)
    donnees.setdefault("sauvegardes", []).append({"chemin": chemin, "motif": motif, "date": systeme.date_iso()})
    systeme.ecrire_json(chemins.ETAT_JSON, donnees, 0o644)


def derniere_sauvegarde(systeme):
    liste = lire(systeme).get("sauvegardes") or []
    return liste[-1] if liste else None
