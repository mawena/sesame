"""Sauvegarde de la configuration dans /var/lib/sesame/sauvegardes/AAAAMMJJ-HHMMSS[-motif]/ (dossier 0700)."""
import re

from . import chemins, etat

FIXES = ["/etc/passwd", "/etc/shadow", "/etc/group", "/etc/gshadow", "/etc/subuid", "/etc/subgid",
         "/etc/nsswitch.conf", "/etc/login.defs", "/etc/krb5.conf", "/etc/sssd", "/etc/pam.d", "/etc/gdm3",
         chemins.VMWARE_AUTORISATION, chemins.ACCOUNTSSERVICE]


def a_sauvegarder(systeme):
    """Chemins à copier : liste fixe plus les unités /etc/systemd/system/*.service."""
    unites = [f"{chemins.UNITES_SYSTEME}/{n}" for n in systeme.lister(chemins.UNITES_SYSTEME) if n.endswith(".service")]
    return FIXES + unites


def crontab_de(systeme, compte):
    """Texte de la crontab d'un compte, ou chaîne vide."""
    r = systeme.lancer(["crontab", "-u", compte, "-l"])
    return r.sortie if r.ok else ""


def _nouveau_dossier(systeme, motif):
    base = systeme.horodatage() + (("-" + re.sub(r"[^a-z0-9_-]+", "-", motif.lower())) if motif else "")
    nom, n = base, 1
    while systeme.existe(f"{chemins.SAUVEGARDES}/{nom}"):
        n += 1
        nom = f"{base}-{n}"
    return f"{chemins.SAUVEGARDES}/{nom}"


def faire(systeme, compte_local="", motif=""):
    """Copie la configuration (et la crontab du compte local) ; renvoie le chemin de la sauvegarde."""
    systeme.etape("Sauvegarde de la configuration")
    systeme.creer_dossier(chemins.VAR_SESAME, 0o755)
    systeme.creer_dossier(chemins.SAUVEGARDES, 0o700)
    dossier = _nouveau_dossier(systeme, motif)
    systeme.creer_dossier(dossier, 0o700)
    for chemin in a_sauvegarder(systeme):
        if systeme.existe(chemin):
            systeme.copier(chemin, dossier + chemin)
    if compte_local:
        texte = crontab_de(systeme, compte_local)
        if texte.strip():
            systeme.ecrire(f"{dossier}/crontab-{compte_local}", texte, 0o600)
    etat.ajouter_sauvegarde(systeme, dossier, motif)
    return dossier
