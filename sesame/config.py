"""Réglages de Sésame (/etc/sesame/sesame.conf), valeurs par défaut détectées et modèle de broker.conf."""
import configparser
import re
from dataclasses import dataclass, field

from . import chemins

_GUID = re.compile(r"^[0-9a-fA-F]{8}-([0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$")
_UPN = re.compile(r"^[^@\s:/\;#]+@([A-Za-z0-9-]+\.)+[A-Za-z0-9-]{2,}$")
_NOM = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")


@dataclass
class Config:
    """Réglages d'une installation."""
    locataire: str = ""
    client: str = ""
    compte: str = ""
    compte_local: str = ""
    uid: int = 0
    gid: int = 0
    dossier: str = ""
    secours: str = "secours"
    groupes: list = field(default_factory=list)


def valider_guid(texte):
    """Vrai si `texte` est un GUID (8-4-4-4-12 hexadécimal)."""
    return bool(_GUID.match(texte or ""))


def valider_upn(texte):
    """Vrai si `texte` ressemble à `partie@domaine.tld` (sans espace ; la casse est ignorée)."""
    return bool(_UPN.match((texte or "").strip()))


def normaliser_upn(texte):
    """UPN sans espace autour et en minuscules."""
    return (texte or "").strip().lower()


def valider_nom(texte):
    """Vrai si `texte` est un nom de compte ou de groupe Unix acceptable."""
    return bool(_NOM.match(texte or ""))


def decouper_groupes(texte):
    """Liste de noms de groupes depuis `a,b, c`."""
    return [g.strip() for g in (texte or "").split(",") if g.strip()]


def texte_conf(config):
    """Contenu de sesame.conf."""
    return (
        "# Réglages de Sésame — écrit par l'étape « configurer ». Aucun secret ici.\n"
        "[entra]\n"
        f"locataire = {config.locataire}\n"
        f"client = {config.client}\n"
        f"compte = {normaliser_upn(config.compte)}\n\n"
        "[local]\n"
        f"compte = {config.compte_local}\n"
        f"uid = {config.uid}\n"
        f"gid = {config.gid}\n"
        f"dossier = {config.dossier}\n"
        f"secours = {config.secours}\n\n"
        "[groupes]\n"
        f"supplementaires = {','.join(config.groupes)}\n"
    )


def ecrire(systeme, config):
    systeme.ecrire(chemins.SESAME_CONF, texte_conf(config), 0o644)


def charger(systeme):
    """Lit sesame.conf ; None s'il n'existe pas ou est illisible."""
    texte = systeme.lire(chemins.SESAME_CONF, None)
    if texte is None:
        return None
    lecteur = configparser.ConfigParser(interpolation=None, inline_comment_prefixes=(";",))
    try:
        lecteur.read_string(texte)
    except configparser.Error:
        return None

    def val(section, cle, defaut=""):
        return lecteur.get(section, cle, fallback=defaut).strip()

    def entier(section, cle):
        v = val(section, cle)
        return int(v) if v.isdigit() else 0

    return Config(val("entra", "locataire"), val("entra", "client"), val("entra", "compte").lower(),
                  val("local", "compte"), entier("local", "uid"), entier("local", "gid"), val("local", "dossier"),
                  val("local", "secours", "secours") or "secours",
                  decouper_groupes(val("groupes", "supplementaires")))


def _compte_appelant(systeme, locaux):
    """Compte local de la personne qui lance l'assistant, sinon le premier compte ordinaire."""
    candidats = []
    if systeme.env.get("SUDO_USER") and systeme.env["SUDO_USER"] in locaux:
        candidats.append(locaux[systeme.env["SUDO_USER"]])
    par_uid = {u.uid: u for u in locaux.values()}
    for cle in ("PKEXEC_UID", "SUDO_UID"):
        if systeme.env.get(cle, "").isdigit() and int(systeme.env[cle]) in par_uid:
            candidats.append(par_uid[int(systeme.env[cle])])
    if systeme.uid in par_uid:
        candidats.append(par_uid[systeme.uid])
    candidats += sorted(locaux.values(), key=lambda u: u.uid)
    return next((u for u in candidats if 1000 <= u.uid <= 59999), None)


def defauts(systeme):
    """Valeurs proposées, détectées sur le poste (compte local, groupes, UPN suggéré)."""
    config = Config()
    locaux = systeme.comptes_locaux()
    compte = _compte_appelant(systeme, locaux)
    if compte:
        config.compte_local, config.uid, config.gid, config.dossier = compte.nom, compte.uid, compte.gid, compte.dossier
        primaire = next((g.nom for g in systeme.groupes_locaux().values() if g.gid == compte.gid), "")
        config.groupes = [g.nom for g in systeme.groupes_locaux().values()
                          if compte.nom in g.membres and g.nom not in (compte.nom, primaire)]
        domaines = systeme.domaines()
        if domaines:
            config.compte = f"{compte.nom.replace('-', '.')}@{domaines[0]}".lower()
    return config


def texte_broker(config):
    """Contenu de /var/snap/authd-msentraid/current/broker.conf."""
    return (
        "# Module Microsoft Entra ID pour authd — écrit par Sésame. Original : broker.conf.origine\n"
        "[oidc]\n"
        f"issuer = https://login.microsoftonline.com/{config.locataire}/v2.0\n"
        f"client_id = {config.client}\n\n"
        "[users]\n"
        "allowed_users = OWNER\n"
        f"owner = {normaliser_upn(config.compte)}\n"
        "home_base_dir = /home\n"
        f"owner_extra_groups = {','.join(config.groupes)}\n\n"
        "[msentraid]\n"
        "register_device = false\n\n"
        "[flows]\n"
        "entra_auth = false\n"
    )
