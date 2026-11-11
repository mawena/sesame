"""Actions root de Sésame : chacune renvoie un message, ou lève ErreurSesame."""
import re
import tarfile

from . import chemins, config as cfg, etat, nsswitch, reprise, sauvegarde, verification
from .systeme import ErreurSesame


def _config_ou_defauts(systeme):
    return cfg.charger(systeme) or cfg.defauts(systeme)


def _noter(systeme, cle, **extra):
    etat.noter(systeme, cle, dict(extra, date=systeme.date_iso()))


# --- 1. sauvegarde
def faire_sauvegarde(systeme, motif=""):
    c = _config_ou_defauts(systeme)
    dossier = sauvegarde.faire(systeme, c.compte_local, motif)
    return f"Configuration sauvegardée dans {dossier}."


# --- 2. secours
def creer_secours(systeme, nom, mot_de_passe):
    """Crée (ou répare) le compte de secours ; le mot de passe passe par l'entrée standard de chpasswd."""
    if not cfg.valider_nom(nom):
        raise ErreurSesame(f"Nom de compte invalide : {nom!r}.")
    existe = nom in systeme.comptes_locaux()
    if not existe and not mot_de_passe:
        raise ErreurSesame("Un mot de passe est nécessaire pour créer le compte de secours.")
    if mot_de_passe and (len(mot_de_passe) < 8 or "\n" in mot_de_passe):
        raise ErreurSesame("Le mot de passe doit faire au moins 8 caractères, sur une seule ligne.")
    if existe:
        systeme.executer(["usermod", "-aG", "sudo", nom])
    else:
        systeme.executer(["useradd", "-m", "-s", "/bin/bash", "-c", "Compte de secours (Sésame)", "-G", "sudo", nom])
    if mot_de_passe:
        systeme.executer(["chpasswd"], entree=f"{nom}:{mot_de_passe}\n")
    return f"Le compte de secours {nom} est prêt."


# --- 3. quitter le domaine AD
def _archiver_dossier_ad(systeme, upn):
    """Archive puis supprime /home/<UPN> (ancien dossier AD du même nom)."""
    dossier = f"/home/{upn}"
    if not upn or not systeme.est_dossier(dossier):
        return
    derniere = etat.derniere_sauvegarde(systeme)
    sauv = derniere["chemin"] if derniere and systeme.est_dossier(derniere["chemin"]) \
        else sauvegarde.faire(systeme, "", "quitter-ad")
    archive = f"{sauv}/home-ad-{upn}.tar.gz"
    with tarfile.open(systeme.chemin(archive), "w:gz") as t:
        t.add(systeme.chemin(dossier), arcname=upn)
    systeme.supprimer(dossier)
    systeme.etape(f"Ancien dossier AD archivé : {archive}")


def quitter_ad(systeme):
    c = _config_ou_defauts(systeme)
    domaines = systeme.domaines()
    for domaine in domaines:
        systeme.etape(f"Départ du domaine {domaine}")
        systeme.executer(["realm", "leave", "-v", domaine])
    systeme.etape("Arrêt de SSSD")
    systeme.executer(["systemctl", "disable", "--now", "sssd"], tolerant=True)
    for rep, motif in (("/var/lib/sss/db", ".ldb"), ("/var/lib/sss/mc", "")):
        for nom in systeme.lister(rep):
            if nom.endswith(motif):
                systeme.supprimer(f"{rep}/{nom}")
    if not systeme.executer(["pam-auth-update", "--disable", "sss"], tolerant=True).ok:
        systeme.avertir("pam-auth-update n'a pas pu retirer SSSD de PAM : à vérifier.")
    texte = systeme.lire(chemins.NSSWITCH)
    systeme.ecrire(chemins.NSSWITCH, nsswitch.retirer_service(texte, nsswitch.BASES_SSS, "sss"))
    _archiver_dossier_ad(systeme, c.compte)
    if c.compte and systeme.utilisateur(c.compte) is not None:
        raise ErreurSesame(f"Le compte AD {c.compte} est encore visible.")
    _noter(systeme, "quitter_ad", domaines=domaines)
    return "Le poste a quitté le domaine et SSSD ne sert plus."


# --- 4. installer
def installer(systeme):
    texte = systeme.lire("/etc/os-release")
    m = re.search(r'^VERSION_ID="?(\d+)\.(\d+)', texte, re.M)
    version = (int(m.group(1)), int(m.group(2))) if m else None
    if version is None or version < (24, 4):
        raise ErreurSesame("Sésame demande Ubuntu 24.04 ou plus récent.")
    if version == (24, 4):
        systeme.etape("Ajout du PPA d'authd")
        systeme.executer(["add-apt-repository", "-y", "ppa:ubuntu-enterprise-desktop/authd"])
    systeme.etape("Installation d'authd")
    systeme.executer(["apt-get", "update"])
    systeme.executer(["apt-get", "install", "-y", "authd", "gnome-shell", "yaru-theme-gnome-shell"])
    if systeme.lancer(["snap", "list", "authd-msentraid"]).ok:
        systeme.etape("Mise à jour du module Entra")
        systeme.executer(["snap", "refresh", "authd-msentraid"], tolerant=True)
    else:
        systeme.etape("Installation du module Entra")
        systeme.executer(["snap", "install", "authd-msentraid"])
    versions = cfg.versions_installees(systeme)
    trop = cfg.trop_anciens(versions)
    if trop:
        systeme.avertir(f"Trop ancien pour la connexion par mot de passe Entra : {trop}. "
                        "La connexion par code sur le téléphone reste possible.")
    _noter(systeme, "installer", authd=cfg.texte_version(versions["authd"]),
           module=cfg.texte_version(versions["module"]))
    return (f"authd {cfg.texte_version(versions['authd'])} et le module Entra "
            f"{cfg.texte_version(versions['module'])} sont installés.")


# --- 5. configurer
def _login_timeout(systeme):
    """Porte LOGIN_TIMEOUT à 300 s s'il est plus bas."""
    texte = systeme.lire(chemins.LOGIN_DEFS)

    def corriger(m):
        return m.group(0) if int(m.group(2)) >= 300 else m.group(1) + "300"

    nouveau = re.sub(r"^(LOGIN_TIMEOUT[ \t]+)(\d+)", corriger, texte, flags=re.M)
    if nouveau != texte:
        systeme.ecrire(chemins.LOGIN_DEFS, nouveau)


def verifier_config(c):
    """Lève ErreurSesame si un réglage est invalide."""
    if not cfg.valider_guid(c.locataire):
        raise ErreurSesame("L'ID du locataire doit être un GUID (8-4-4-4-12 caractères hexadécimaux).")
    if not cfg.valider_guid(c.client):
        raise ErreurSesame("L'ID client doit être un GUID (8-4-4-4-12 caractères hexadécimaux).")
    if not cfg.valider_upn(c.compte):
        raise ErreurSesame("Le compte Entra doit ressembler à prenom.nom@entreprise.com.")
    if not cfg.valider_connexion(c.connexion):
        raise ErreurSesame(f"Mode de connexion inconnu : {c.connexion!r} (mot-de-passe ou code).")
    for nom in [c.compte_local, c.secours] + c.groupes:
        if not cfg.valider_nom(nom):
            raise ErreurSesame(f"Nom de compte ou de groupe invalide : {nom!r}.")


def construire_config(systeme, locataire, client, compte, compte_local=None, secours=None, groupes=None,
                      connexion=None):
    """Réglages à écrire : saisie, sinon réglages déjà enregistrés, sinon valeurs détectées."""
    ancien, defaut = cfg.charger(systeme), cfg.defauts(systeme)
    base = ancien if ancien and ancien.compte_local else defaut
    nom_local = compte_local or base.compte_local
    local = systeme.comptes_locaux().get(nom_local)
    c = cfg.Config(locataire=locataire, client=client, compte=cfg.normaliser_upn(compte), compte_local=nom_local,
                   uid=local.uid if local else base.uid, gid=local.gid if local else base.gid,
                   dossier=local.dossier if local else base.dossier, secours=secours or base.secours or "secours",
                   groupes=groupes if groupes is not None else base.groupes,
                   connexion=connexion or (ancien.connexion if ancien else cfg.MOT_DE_PASSE))
    if local is None and (not ancien or ancien.compte_local != nom_local):
        raise ErreurSesame(f"Le compte local {nom_local or '?'} n'existe pas.")
    verifier_config(c)
    return c


def configurer(systeme, c):
    if not systeme.existe(chemins.BROKER_MODELE):
        raise ErreurSesame("Le module authd-msentraid n'est pas installé : faites d'abord l'étape d'installation.")
    if c.connexion == cfg.MOT_DE_PASSE:
        trop = cfg.trop_anciens(cfg.versions_installees(systeme))
        if trop:
            raise ErreurSesame(f"La connexion par mot de passe Entra demande authd "
                               f"{cfg.texte_version(cfg.VERSION_MIN_AUTHD)} et le module Entra "
                               f"{cfg.texte_version(cfg.VERSION_MIN_MODULE)} : {trop}. Relancez l'étape « Installer » "
                               "pour les mettre à jour, ou choisissez la connexion « Code sur le téléphone ».")
    systeme.etape("Écriture de sesame.conf")
    cfg.ecrire(systeme, c)
    systeme.etape("Déclaration du module à authd")
    systeme.copier(chemins.BROKER_MODELE, chemins.BROKER_AUTHD)
    systeme.etape("Configuration du module Entra")
    if systeme.existe(chemins.BROKER_CONF) and not systeme.existe(chemins.BROKER_CONF + ".origine"):
        systeme.copier(chemins.BROKER_CONF, chemins.BROKER_CONF + ".origine")
    systeme.ecrire(chemins.BROKER_CONF, cfg.texte_broker(c))
    _login_timeout(systeme)
    texte = systeme.lire(chemins.NSSWITCH)
    systeme.ecrire(chemins.NSSWITCH, nsswitch.ajouter_service(texte, nsswitch.BASES_AUTHD, "authd"))
    systeme.etape("Redémarrage des services")
    systeme.executer(["systemctl", "restart", "authd"])
    systeme.executer(["systemctl", "restart", chemins.SERVICE_BROKER])
    _noter(systeme, "configurer", connexion=c.connexion)
    if c.connexion == cfg.MOT_DE_PASSE:
        return ("La connexion Entra est configurée : adresse pro et mot de passe Entra, comme sur Windows. "
                "Le poste sera inscrit dans Entra à la première connexion.")
    return "La connexion Entra est configurée : code à saisir sur le téléphone."


def desactiver(systeme):
    systeme.supprimer(chemins.BROKER_AUTHD)
    systeme.executer(["systemctl", "restart", "authd"])
    return "La connexion Entra est coupée (rien n'est désinstallé). L'étape « configurer » la rétablit."


# --- 7. reprise
def reprendre(systeme, mode):
    c = cfg.charger(systeme)
    if c is None or not (c.compte and c.compte_local and c.uid and c.dossier):
        raise ErreurSesame("Sésame n'est pas configuré : faites d'abord l'étape « Configurer ».")
    p = reprise.Parametres.depuis_config(c)
    if mode == "au-demarrage":
        return True, reprise.programmer(systeme, p)
    return reprise.reprendre(systeme, p, mode)


# --- 8. vérification
def noter_verification(systeme):
    _noter(systeme, "verification")
    return "Vérification notée."
