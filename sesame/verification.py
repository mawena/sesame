"""Contrôles de fin de parcours, sans root : liste de (ok, texte)."""
import os

from . import chemins, etat


def utilisateur_courant(systeme):
    """Compte NSS de l'utilisateur courant, ou None."""
    return systeme.utilisateur(systeme.uid)


def est_connecte(systeme, config):
    """Vrai si l'on est connecté en tant que le compte Entra."""
    courant = utilisateur_courant(systeme)
    return bool(courant and config and courant.nom == config.compte)


def _controles_session(systeme, config):
    courant = utilisateur_courant(systeme)
    res = [(courant is not None and courant.uid == config.uid,
            f"Le compte Entra a l'UID {config.uid} (actuel : {courant.uid if courant else '?'})")]
    home = systeme.env.get("HOME", "")
    res.append((home == config.dossier, f"$HOME vaut {config.dossier} (actuel : {home or 'vide'})"))
    try:
        proprietaire = os.stat(systeme.chemin(config.dossier)).st_uid
    except OSError:
        proprietaire = None
    res.append((proprietaire == config.uid, f"{config.dossier} appartient à l'UID {config.uid}"))
    return res


def _controles_groupes(systeme, config):
    res = []
    for nom in config.groupes:
        groupe = systeme.groupe(nom)
        res.append((groupe is not None and config.compte in groupe.membres,
                    f"{config.compte} fait partie du groupe {nom}"))
    return res


def _controles_reprise(systeme, config):
    reprise = etat.lire(systeme).get("reprise") or {}
    res = []
    if reprise.get("crontab") and est_connecte(systeme, config):  # on ne lit que sa propre crontab sans root
        res.append((systeme.lancer(["crontab", "-l"]).ok, "Une crontab existe, comme avant la reprise"))
    res.append((config.compte_local not in systeme.comptes_locaux(), f"L'ancien compte {config.compte_local} n'existe plus"))
    for unite in reprise.get("unites", []):
        if systeme.unite_activee(unite):
            res.append((systeme.service_actif(unite), f"L'unité {unite} est active"))
    return res


def controler(systeme, config):
    """Contrôles de l'installation. Hors session du compte Entra, seule la configuration est contrôlée (et dit)."""
    if config is None:
        return [(False, "Sésame n'est pas encore configuré")]
    res = []
    if est_connecte(systeme, config):
        res += _controles_session(systeme, config)
    else:
        res.append((True, f"Vous n'êtes pas connecté en tant que {config.compte} : "
                          "seule la configuration est contrôlée"))
    res += _controles_groupes(systeme, config)
    res += _controles_reprise(systeme, config)
    res.append((systeme.service_actif("authd"), "Le service authd est actif"))
    res.append((systeme.service_actif(chemins.SERVICE_BROKER), "Le service du module Entra est actif"))
    secours = systeme.comptes_locaux().get(config.secours)
    sudo = systeme.groupes_locaux().get("sudo")
    res.append((secours is not None and sudo is not None and config.secours in sudo.membres,
                f"Le compte de secours {config.secours} existe et est administrateur"))
    return res
