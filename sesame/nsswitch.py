"""Édition de /etc/nsswitch.conf : retrait de `sss`, ajout d'`authd` (fonctions pures, idempotentes)."""
import re

BASES_SSS = ("passwd", "group", "shadow", "netgroup", "services", "sudoers", "automount")
BASES_AUTHD = ("passwd", "group", "shadow")


def _separer(ligne):
    """Sépare une ligne en (corps, commentaire)."""
    corps, dièse, commentaire = ligne.partition("#")
    return corps, dièse + commentaire


def _base(corps):
    m = re.match(r"\s*([A-Za-z_]+):", corps)
    return m.group(1) if m else None


def retirer_service(texte, bases, service):
    """Retire `service` des lignes des `bases`."""
    sortie = []
    for ligne in texte.split("\n"):
        corps, commentaire = _separer(ligne)
        if _base(corps) in bases:
            corps = re.sub(r"[ \t]+" + re.escape(service) + r"(?=[ \t]|$)", "", corps)
            ligne = corps + commentaire
        sortie.append(ligne)
    return "\n".join(sortie)


def ajouter_service(texte, bases, service):
    """Ajoute `service` en fin des lignes des `bases` qui ne l'ont pas."""
    sortie = []
    for ligne in texte.split("\n"):
        corps, commentaire = _separer(ligne)
        if _base(corps) in bases and service not in corps.split()[1:]:
            corps = corps.rstrip() + f" {service}" + (" " if commentaire else "")
            ligne = corps + commentaire
        sortie.append(ligne)
    return "\n".join(sortie)


def contient(texte, service, bases=BASES_SSS):
    """Vrai si une ligne des `bases` cite `service`."""
    for ligne in texte.split("\n"):
        corps = _separer(ligne)[0]
        if _base(corps) in bases and service in corps.split()[1:]:
            return True
    return False


def manque(texte, service, bases=BASES_AUTHD):
    """Bases présentes dans le fichier dont la ligne ne cite pas `service`."""
    presentes = {_base(_separer(l)[0]) for l in texte.split("\n")}
    return [b for b in bases if b in presentes and not contient(texte, service, (b,))]


def service_de(texte, base):
    """Services listés sur la ligne `base` (sans commentaire)."""
    for ligne in texte.split("\n"):
        corps = _separer(ligne)[0]
        if _base(corps) == base:
            return corps.split()[1:]
    return []
