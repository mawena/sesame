"""Les huit étapes de Sésame et leur détection (sans root, sans jamais planter)."""
from dataclasses import dataclass

from . import chemins, config as cfg, etat, himmelblau, nsswitch
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
          "Crée un compte local administrateur, avec votre mot de passe Ubuntu actuel, pour dépanner le poste "
          "si la connexion Entra ne fonctionne pas.", "secours"),
    Etape("nom_machine", "Nommer la machine",
          "Donne au poste le nom sous lequel il sera inscrit dans Entra (15 caractères au plus : lettres, "
          "chiffres et tirets).", "nom-machine"),
    Etape("quitter_ad", "Quitter le domaine Active Directory",
          "Retire le poste de l'ancien domaine (sur ce poste seulement) et arrête SSSD, qui donnerait un compte "
          "de même nom que le compte Entra.", "quitter-ad"),
    Etape("outils", "Installer les outils de compilation",
          "Installe podman, git et make, qui servent à compiler Himmelblau sur ce poste (gratuit, sans abonnement), "
          "et réserve à votre compte la plage d'identifiants dont podman a besoin.", "outils"),
    Etape("compiler", "Compiler Himmelblau",
          "Télécharge et compile Himmelblau (version stable-4.x) dans un conteneur, sous votre compte. "
          "C'est long (de 20 minutes à plus d'une heure) et demande de la mémoire : le poste reste utilisable.", None),
    Etape("installer", "Installer Himmelblau",
          "Installe les paquets Himmelblau compilés : le service qui connecte Ubuntu à Microsoft Entra ID comme le "
          "fait Windows, sans application à créer. Demande Ubuntu 24.04 ou plus récent.", "installer"),
    Etape("configurer", "Relier votre compte à Entra",
          "Relie votre compte local à votre adresse pro : vous gardez votre dossier et vos réglages, et vous vous "
          "connectez avec le mot de passe Entra.", "configurer"),
    Etape("premiere_connexion", "Première connexion",
          "Déconnectez-vous, choisissez votre compte à l'écran d'accueil, tapez le mot de passe Entra et validez "
          "sur le téléphone. Le poste est inscrit dans Entra à cette première connexion, puis vous choisissez un "
          "code PIN (Windows Hello).", None),
]

# Étapes à satisfaire (faites ou sans objet) avant de pouvoir lancer l'étape.
PREREQUIS = {
    "secours": ["sauvegarde"],
    "nom_machine": ["sauvegarde"],
    "quitter_ad": ["sauvegarde", "secours"],
    "outils": ["sauvegarde"],
    "compiler": ["outils"],
    "installer": ["compiler", "quitter_ad"],
    "configurer": ["installer", "secours"],
    "premiere_connexion": ["configurer"],
}
TITRES = {e.id: e.titre for e in ETAPES}


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


def _nom_machine(systeme, c):
    actuel = (systeme.lire(chemins.HOSTNAME).split() or [""])[0].split(".")[0]
    if c.nom_machine and actuel == c.nom_machine:
        return FAIT, f"La machine s'appelle {actuel}."
    if c.nom_machine:
        return A_FAIRE, f"Le nom choisi est {c.nom_machine}, la machine s'appelle {actuel or '?'}."
    return A_FAIRE, f"La machine s'appelle {actuel or '?'} : choisissez le nom qu'elle aura dans Entra."


def _outils(systeme, c):
    manque = []
    for nom in himmelblau.OUTILS:
        r = systeme.lancer(["dpkg-query", "-W", "-f=${db:Status-Abbrev}", nom])
        if not (r.ok and r.sortie.strip().startswith("ii")):
            manque.append(nom)
    if manque:
        return A_FAIRE, "Manque : " + ", ".join(manque) + "."
    return FAIT, "Les outils de compilation sont installés."


def paquets_manquants(systeme):
    """Paquets Himmelblau obligatoires qui ne sont pas installés."""
    manque = []
    for nom in himmelblau.PAQUETS:
        r = systeme.lancer(["dpkg-query", "-W", "-f=${db:Status-Abbrev}", nom])
        if not (r.ok and r.sortie.strip().startswith("ii")):
            manque.append(nom)
    return manque


def _compiler(systeme, c):
    if not paquets_manquants(systeme):
        return FAIT, "Himmelblau est déjà installé : rien à compiler."
    if c.dossier_compilation:
        info = systeme.lire_json(f"{c.dossier_compilation}/packaging/sesame-compilation.json", {})
        entrees = info.get("paquets") if isinstance(info, dict) else None
        if isinstance(entrees, dict):
            entrees = list(entrees) + list(entrees.values())
        if isinstance(entrees, list) and all(p in himmelblau.debs_dans([str(e) for e in entrees])
                                            for p in himmelblau.PAQUETS):
            return FAIT, f"Himmelblau est compilé ({c.dossier_compilation}/packaging)."
    return A_FAIRE, "Himmelblau n'est pas encore compilé."


def _installer(systeme, c):
    version = version_ubuntu(systeme)
    if version and version < (24, 4):
        return BLOQUEE, f"Ubuntu {version[0]}.{version[1]:02d} est trop ancien : il faut Ubuntu 24.04 ou plus récent."
    manque = paquets_manquants(systeme)
    if manque:
        return A_FAIRE, "Manque : " + ", ".join(manque) + "."
    r = systeme.lancer(["dpkg-query", "-W", "-f=${Version}", "himmelblau"])
    return FAIT, f"Himmelblau {r.sortie.strip() if r.ok else '?'} est installé."


def _configurer(systeme, c):
    manque = []
    texte = systeme.lire(himmelblau.CONFIG)
    if not (himmelblau.lire_config(texte, "domain") and himmelblau.lire_config(texte, "user_map_file")):
        manque.append("himmelblau.conf n'a pas de domaine ni de user-map")
    liens = himmelblau.lire_user_map(systeme.lire(himmelblau.USER_MAP))
    if not c.compte_local or c.compte_local not in liens:
        manque.append("aucun compte local n'est relié à une adresse Entra (user-map)")
    if not systeme.service_actif("himmelblaud"):
        manque.append("le service himmelblaud n'est pas actif")
    if manque:
        return A_FAIRE, "À faire : " + " ; ".join(manque) + "."
    return FAIT, f"{c.compte_local} est relié à {liens[c.compte_local]}."


def _premiere_connexion(systeme, c):
    note = etat.lire(systeme).get("premiere_connexion")
    if note:
        return FAIT, f"Première connexion notée : {note.get('date', '?') if isinstance(note, dict) else '?'}"
    adresse = c.compte or "votre adresse pro"
    return A_FAIRE, (f"Déconnectez-vous, choisissez votre compte à l'écran d'accueil, tapez le mot de passe Entra "
                     f"de {adresse} et validez sur le téléphone.")


DETECTIONS = {"sauvegarde": _sauvegarde, "secours": _secours, "nom_machine": _nom_machine,
              "quitter_ad": _quitter_ad, "outils": _outils, "compiler": _compiler,
              "installer": _installer, "configurer": _configurer,
              "premiere_connexion": _premiere_connexion}


def version_ubuntu(systeme):
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


def etat_complet(systeme):
    """Ce que renvoie `sesame etat --json`."""
    etats = lire_etat(systeme)
    return {"version": VERSION, "etapes": etats, "suivante": etape_suivante(etats)}
