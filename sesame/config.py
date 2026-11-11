"""Réglages de Sésame (/etc/sesame/sesame.conf), valeurs par défaut détectées et validation des saisies."""
import configparser
import re
from dataclasses import dataclass

from . import chemins

_UPN = re.compile(r"^[^@\s:/\;#]+@([A-Za-z0-9-]+\.)+[A-Za-z0-9-]{2,}$")
_NOM = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")
_NOM_MACHINE = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9-]{0,13}[A-Za-z0-9])?\Z")


@dataclass
class Config:
    """Réglages d'une installation."""
    compte: str = ""
    compte_local: str = ""
    uid: int = 0
    gid: int = 0
    dossier: str = ""
    secours: str = "secours"
    nom_machine: str = ""
    dossier_compilation: str = ""


def valider_upn(texte):
    """Vrai si `texte` ressemble à `partie@domaine.tld` (sans espace ; la casse est ignorée)."""
    return bool(_UPN.match((texte or "").strip()))


def normaliser_upn(texte):
    """UPN sans espace autour et en minuscules."""
    return (texte or "").strip().lower()


def valider_nom(texte):
    """Vrai si `texte` est un nom de compte Unix acceptable."""
    return bool(_NOM.match(texte or ""))


def valider_nom_machine(texte):
    """Vrai si `texte` est un nom de machine acceptable (règle Windows) : 1 à 15 caractères, lettres, chiffres et
    tirets, ni tiret au début ou à la fin, pas uniquement des chiffres."""
    return bool(_NOM_MACHINE.match(texte or "")) and not texte.isdigit()


def texte_conf(config):
    """Contenu de sesame.conf."""
    return (
        "# Réglages de Sésame — écrit par Sésame. Aucun secret ici.\n"
        "[entra]\n"
        f"compte = {normaliser_upn(config.compte)}\n\n"
        "[local]\n"
        f"compte = {config.compte_local}\n"
        f"uid = {config.uid}\n"
        f"gid = {config.gid}\n"
        f"dossier = {config.dossier}\n"
        f"secours = {config.secours}\n\n"
        "[machine]\n"
        f"nom = {config.nom_machine}\n\n"
        "[compilation]\n"
        f"dossier = {config.dossier_compilation}\n"
    )


def ecrire(systeme, config):
    systeme.ecrire(chemins.SESAME_CONF, texte_conf(config), 0o644)


def charger(systeme):
    """Lit sesame.conf (les clés inconnues, par exemple celles de la 1.x, sont ignorées) ; None s'il n'existe pas
    ou est illisible."""
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

    return Config(val("entra", "compte").lower(), val("local", "compte"), entier("local", "uid"),
                  entier("local", "gid"), val("local", "dossier"), val("local", "secours", "secours") or "secours",
                  val("machine", "nom"), val("compilation", "dossier"))


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
        domaines = systeme.domaines()
        if domaines:
            config.compte = f"{compte.nom.replace('-', '.')}@{domaines[0]}".lower()
    return config
