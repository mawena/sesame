"""Les huit étapes de Sésame et leur détection (sans root, sans jamais planter)."""
from dataclasses import dataclass

from . import chemins, config as cfg, etat, nsswitch
from .version import VERSION

A_FAIRE, FAIT, SANS_OBJET, PROGRAMMEE, BLOQUEE, INCONNU = (
    "a_faire", "fait", "sans_objet", "programmee", "bloquee", "inconnu")


@dataclass(frozen=True)
class Etape:
    id: str
    titre: str
    explication: str
    action_racine: str  # action de sesame-racine, ou None


ETAPES = [
    Etape("sauvegarde", "Sauvegarder la configuration",
          "Copie les fichiers de comptes et de connexion (/etc/passwd, PAM, GDM…) dans un dossier protégé. "
          "Rien n'est modifié : c'est le filet de sécurité des étapes suivantes.", "sauvegarde"),
    Etape("secours", "Créer le compte de secours",
          "Crée un compte local administrateur pour dépanner le poste si la connexion Entra ne fonctionne pas. "
          "Notez son mot de passe en lieu sûr.", "secours"),
    Etape("quitter_ad", "Quitter le domaine Active Directory",
          "Retire le poste de l'ancien domaine (sur ce poste seulement) et arrête SSSD, qui donnerait un compte "
          "de même nom que le compte Entra.", "quitter-ad"),
    Etape("installer", "Installer authd et le module Entra",
          "Installe authd (le service de connexion de Canonical) et le module Microsoft Entra ID. "
          "Demande Ubuntu 24.04 ou plus récent et une connexion Internet.", "installer"),
    Etape("configurer", "Configurer la connexion Entra",
          "Indique à authd votre annuaire et votre application Entra. Vous seul pourrez vous connecter par Entra "
          "sur ce poste.", "configurer"),
    Etape("premiere_connexion", "Première connexion par Entra",
          "Ouvrez une session par Entra une première fois : « Non listé ? », votre adresse pro, Microsoft Entra ID, "
          "puis votre mot de passe Entra et la validation sur le téléphone, comme sur Windows.", None),
    Etape("reprise", "Reprendre le compte local",
          "Le compte Entra prend l'UID, le dossier personnel, les groupes et la crontab du compte local. "
          "De préférence au prochain démarrage, quand aucune session n'est ouverte.", "reprise"),
    Etape("verification", "Vérifier",
          "Contrôle que tout est en place : compte, dossier, groupes, crontab et services. "
          "À faire connecté avec le compte Entra.", None),
]

# Étapes à satisfaire (faites ou sans objet) avant de pouvoir lancer l'étape.
PREREQUIS = {
    "secours": ["sauvegarde"],
    "quitter_ad": ["sauvegarde", "secours"],
    "installer": ["sauvegarde", "quitter_ad"],
    "configurer": ["installer"],
    "premiere_connexion": ["configurer"],
    "reprise": ["secours", "premiere_connexion"],
    "verification": ["reprise"],
}
TITRES = {e.id: e.titre for e in ETAPES}
NOMS_CONNEXION = {cfg.MOT_DE_PASSE: "mot de passe", cfg.CODE: "code sur le téléphone"}


def _config(systeme):
    """Réglages enregistrés, sinon valeurs détectées."""
    return cfg.charger(systeme) or cfg.defauts(systeme)


def _sauvegarde(systeme, c):
    derniere = etat.derniere_sauvegarde(systeme)
    if derniere:
        return FAIT, f"Dernière sauvegarde : {derniere.get('date', '?')}"
    return A_FAIRE, "Aucune sauvegarde."


def _secours(systeme, c):
    nom = c.secours or "secours"
    compte = systeme.comptes_locaux().get(nom)
    if compte is None:
        return A_FAIRE, f"Le compte {nom} n'existe pas."
    sudo = systeme.groupes_locaux().get("sudo")
    if sudo is None or nom not in sudo.membres:
        return A_FAIRE, f"Le compte {nom} n'est pas administrateur (groupe sudo)."
    return FAIT, f"Le compte {nom} existe et est administrateur."


def _quitter_ad(systeme, c):
    domaines = systeme.domaines()
    sss = nsswitch.contient(systeme.lire(chemins.NSSWITCH), "sss")
    if domaines:
        return A_FAIRE, "Le poste est dans le domaine " + ", ".join(domaines) + "."
    if sss:
        return A_FAIRE, "SSSD est encore consulté (nsswitch.conf)."
    if etat.lire(systeme).get("quitter_ad"):
        return FAIT, "Le poste a quitté le domaine."
    return SANS_OBJET, "Le poste n'est dans aucun domaine."


def _installer(systeme, c):
    version = _version_ubuntu(systeme)
    if version and version < (24, 4):
        return BLOQUEE, f"Ubuntu {version[0]}.{version[1]:02d} est trop ancien : il faut Ubuntu 24.04 ou plus récent."
    paquet = systeme.lancer(["dpkg-query", "-W", "-f=${db:Status-Abbrev}", "authd"])
    snap = systeme.lancer(["snap", "list", "authd-msentraid"])
    manque = []
    if not (paquet.ok and paquet.sortie.strip().startswith("ii")):
        manque.append("le paquet authd")
    if not snap.ok:
        manque.append("le module authd-msentraid")
    if manque:
        return A_FAIRE, "Manque : " + " et ".join(manque) + "."
    versions = cfg.versions_installees(systeme)
    installes = (f"authd {cfg.texte_version(versions['authd'])} et le module Entra "
                 f"{cfg.texte_version(versions['module'])} sont installés.")
    trop = cfg.trop_anciens(versions) if c.connexion == cfg.MOT_DE_PASSE else ""
    if trop:
        return FAIT, (f"{installes} Trop ancien pour la connexion par mot de passe : {trop}. "
                      "Relancez cette étape pour mettre à jour.")
    return FAIT, installes


def _configurer(systeme, c):
    manque = []
    if not systeme.existe(chemins.BROKER_AUTHD):
        manque.append("le module n'est pas déclaré à authd")
    enregistre = cfg.charger(systeme)
    if not (enregistre and cfg.valider_guid(enregistre.locataire) and cfg.valider_guid(enregistre.client)):
        manque.append("sesame.conf n'a pas de locataire et de client valides")
    if not systeme.service_actif(chemins.SERVICE_BROKER):
        manque.append("le service du module n'est pas actif")
    note = etat.lire(systeme).get("configurer")
    if not manque and isinstance(note, dict) and note.get("connexion", cfg.CODE) != enregistre.connexion:
        manque.append(f"le mode de connexion a changé ({NOMS_CONNEXION.get(note.get('connexion', cfg.CODE), '?')} → "
                      f"{NOMS_CONNEXION[enregistre.connexion]}) : relancez cette étape")
    return (A_FAIRE, "À faire : " + " ; ".join(manque) + ".") if manque else (FAIT, "La connexion Entra est configurée.")


def _premiere_connexion(systeme, c):
    if not c.compte:
        return A_FAIRE, "Le compte Entra n'est pas encore renseigné."
    if c.compte in systeme.comptes_locaux():
        return A_FAIRE, f"{c.compte} est un compte local, pas un compte authd."
    if "authd" not in nsswitch.service_de(systeme.lire(chemins.NSSWITCH), "passwd"):
        return A_FAIRE, "authd n'est pas encore consulté pour trouver les comptes (nsswitch.conf)."
    if systeme.utilisateur(c.compte) is not None:
        return FAIT, f"{c.compte} est connu d'authd."
    return A_FAIRE, f"{c.compte} ne s'est pas encore connecté par Entra."


def _reprise(systeme, c):
    n = systeme.utilisateur(c.compte) if c.compte else None
    if n and n.uid == c.uid and n.dossier == c.dossier and c.compte_local not in systeme.comptes_locaux():
        return FAIT, f"{c.compte} a repris le compte {c.compte_local} (UID {c.uid})."
    if systeme.existe(chemins.REPRISE_PROGRAMMEE):
        return PROGRAMMEE, "La reprise aura lieu au prochain démarrage."
    if systeme.existe(chemins.REPRISE_ETAT):
        return A_FAIRE, "Une reprise interrompue est en cours : « sesame annuler-reprise »."
    return A_FAIRE, f"{c.compte or 'Le compte Entra'} peut reprendre {c.compte_local or 'le compte local'}."


def _verification(systeme, c):
    verif = etat.lire(systeme).get("verification")
    if verif:
        return FAIT, f"Vérification réussie : {verif.get('date', '?')}"
    return A_FAIRE, "Pas encore vérifié."


DETECTIONS = {"sauvegarde": _sauvegarde, "secours": _secours, "quitter_ad": _quitter_ad, "installer": _installer,
              "configurer": _configurer, "premiere_connexion": _premiere_connexion, "reprise": _reprise,
              "verification": _verification}


def _version_ubuntu(systeme):
    """(majeur, mineur) d'après /etc/os-release, ou None."""
    for ligne in systeme.lire("/etc/os-release").splitlines():
        if ligne.startswith("VERSION_ID="):
            morceaux = ligne.split("=", 1)[1].strip().strip('"').split(".")
            if len(morceaux) >= 2 and morceaux[0].isdigit() and morceaux[1].isdigit():
                return int(morceaux[0]), int(morceaux[1])
    return None


def lire_etat(systeme):
    """Détecte l'état de chaque étape : [{"id", "titre", "statut", "detail", "explication", "action"}]."""
    try:
        c = _config(systeme)
    except Exception as e:
        c = cfg.Config()
        erreur_config = str(e)
    else:
        erreur_config = None
    etats = []
    for etape in ETAPES:
        try:
            if erreur_config:
                raise RuntimeError(erreur_config)
            statut, detail = DETECTIONS[etape.id](systeme, c)
        except Exception as e:  # la détection ne plante jamais
            statut, detail = INCONNU, f"Détection impossible : {e}"
        etats.append({"id": etape.id, "titre": etape.titre, "statut": statut, "detail": detail,
                      "explication": etape.explication, "action": etape.action_racine})
    _bloquer(etats)
    return etats


def _bloquer(etats):
    """Une étape à faire dont un prérequis manque devient `bloquee`."""
    par_id = {e["id"]: e for e in etats}
    for e in etats:
        if e["statut"] != A_FAIRE:
            continue
        manquants = [p for p in PREREQUIS.get(e["id"], []) if par_id[p]["statut"] not in (FAIT, SANS_OBJET)]
        if manquants:
            e["statut"] = BLOQUEE
            e["detail"] = "Il faut d'abord : " + ", ".join(TITRES[p] for p in manquants) + "."


def etape_suivante(etats):
    """Identifiant de la première étape à faire (ou programmée), None si tout est en place."""
    for e in etats:
        if e["statut"] in (A_FAIRE, PROGRAMMEE):
            return e["id"]
    return None


def derniere_reprise(systeme):
    """Résultat de la dernière reprise (derniere-reprise.json), ou None."""
    return systeme.lire_json(chemins.DERNIERE_REPRISE)


def etat_complet(systeme):
    """Ce que renvoie `sesame etat --json`."""
    etats = lire_etat(systeme)
    return {"version": VERSION, "etapes": etats, "suivante": etape_suivante(etats),
            "derniere_reprise": derniere_reprise(systeme)}
