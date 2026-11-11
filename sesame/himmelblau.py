"""Himmelblau : constantes et fonctions pures (paquets compilés, himmelblau.conf, user-map)."""
import re

CONFIG = "/etc/himmelblau/himmelblau.conf"
USER_MAP = "/etc/himmelblau/user-map"
PAQUETS = ["himmelblau", "pam-himmelblau", "nss-himmelblau"]
PAQUETS_OPTIONNELS = ("himmelblau-apparmor",)
OUTILS = ("podman", "uidmap", "git", "make")
SERVICES = ["himmelblaud", "himmelblaud-tasks"]


def debs_dans(noms):
    """{paquet: nom de fichier} pour chaque paquet voulu (PAQUETS puis PAQUETS_OPTIONNELS) trouvé dans `noms`.
    Un nom convient s'il est le nom du paquet ou un fichier `<paquet>_<version>_<arch>.deb` ; le dernier par ordre
    alphabétique l'emporte."""
    trouves = {}
    for paquet in list(PAQUETS) + list(PAQUETS_OPTIONNELS):
        for nom in sorted(str(n) for n in noms):
            base = nom.rsplit("/", 1)[-1]
            if base == paquet or (base.startswith(paquet + "_") and base.endswith(".deb")):
                trouves[paquet] = nom
    return trouves


def domaine(adresse):
    """Domaine d'une adresse (`a@b.com` → `b.com`), en minuscules ; vide s'il n'y en a pas."""
    return adresse.rpartition("@")[2].strip().lower() if "@" in (adresse or "") else ""


def _regler(lignes, section, valeurs):
    """Fixe `cle = valeur` dans `section` (créée si besoin) ; le reste est conservé tel quel."""
    debut, fin = None, len(lignes)
    for i, ligne in enumerate(lignes):
        m = re.match(r"\s*\[([^\]]*)\]", ligne)
        if not m:
            continue
        if debut is not None:
            fin = i
            break
        if m.group(1).strip() == section:
            debut = i
    if debut is None:
        while lignes and not lignes[-1].strip():
            lignes.pop()
        return lignes + ([""] if lignes else []) + [f"[{section}]"] + [f"{c} = {v}" for c, v in valeurs.items()]
    for cle, valeur in valeurs.items():
        motif = re.compile(r"\s*" + re.escape(cle) + r"\s*=")
        rang = next((i for i in range(debut + 1, fin) if motif.match(lignes[i])), None)
        if rang is None:
            lignes.insert(debut + 1, f"{cle} = {valeur}")
            fin += 1
        else:
            lignes[rang] = f"{cle} = {valeur}"
    return lignes


def texte_config(existant, domaine, user_map):
    """himmelblau.conf : `domain` et `user_map_file` fixés dans [global], le reste du fichier est gardé."""
    lignes = (existant or "").rstrip("\n").split("\n") if (existant or "").strip() else []
    lignes = _regler(lignes, "global", {"domain": domaine, "user_map_file": user_map})
    return "\n".join(lignes) + "\n"


def lire_config(texte, cle, section="global"):
    """Valeur de `cle` dans `section` de himmelblau.conf, ou ""."""
    dans = False
    for ligne in (texte or "").splitlines():
        m = re.match(r"\s*\[([^\]]*)\]", ligne)
        if m:
            dans = m.group(1).strip() == section
        elif dans:
            v = re.match(r"\s*" + re.escape(cle) + r"\s*=\s*(.*?)\s*$", ligne)
            if v:
                return v.group(1)
    return ""


def _champ_local(ligne):
    corps = ligne.strip()
    return None if not corps or corps.startswith("#") or ":" not in corps else corps.split(":", 1)[0].strip()


def texte_user_map(existant, local, adresse):
    """user-map avec la ligne `local:adresse` ; elle remplace toute ligne existante de ce compte local."""
    sortie, mis = [], False
    for ligne in (existant or "").splitlines():
        if _champ_local(ligne) == local:
            if not mis:
                sortie.append(f"{local}:{adresse}")
                mis = True
            continue
        sortie.append(ligne)
    if not mis:
        sortie.append(f"{local}:{adresse}")
    return "\n".join(sortie) + "\n"


def retirer_user_map(existant, local):
    """user-map sans la ligne du compte local."""
    lignes = [l for l in (existant or "").splitlines() if _champ_local(l) != local]
    return "\n".join(lignes) + "\n" if lignes else ""


def lire_user_map(texte):
    """{compte local: adresse} d'un user-map."""
    liens = {}
    for ligne in (texte or "").splitlines():
        local = _champ_local(ligne)
        if local:
            liens[local] = ligne.strip().split(":", 1)[1].strip()
    return liens
