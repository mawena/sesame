"""Contrôles de fin de parcours, sans root : liste de (ok, texte)."""
from . import chemins, himmelblau, nsswitch


def utilisateur_courant(systeme):
    """Compte NSS de l'utilisateur courant, ou None."""
    return systeme.utilisateur(systeme.uid)


def est_connecte(systeme, config):
    """Vrai si l'on est connecté avec le compte local relié à Entra."""
    courant = utilisateur_courant(systeme)
    return bool(courant and config and config.compte_local and courant.nom == config.compte_local)


def controler(systeme, config):
    """Contrôles de l'installation Himmelblau."""
    if config is None:
        return [(False, "Sésame n'est pas encore configuré")]
    res = [(systeme.service_actif("himmelblaud"), "Le service himmelblaud est actif")]
    nss = systeme.lire(chemins.NSSWITCH)
    for base in ("passwd", "group"):
        res.append((nsswitch.contient(nss, "himmelblau", (base,)), f"nsswitch.conf consulte himmelblau pour {base}"))
    res.append(("pam_himmelblau" in systeme.lire(chemins.PAM_COMMON_AUTH), "PAM utilise pam_himmelblau (common-auth)"))
    liens = himmelblau.lire_user_map(systeme.lire(himmelblau.USER_MAP))
    attendu = f"{config.compte_local} est relié à {config.compte}"
    res.append((bool(config.compte_local) and liens.get(config.compte_local, "").lower() == config.compte.lower()
                and bool(config.compte), f"user-map : {attendu}"))
    if systeme.programme_present("aad-tool"):
        res.append((systeme.lancer(["aad-tool", "status"]).ok, "aad-tool status répond"))
    actuel = (systeme.lire(chemins.HOSTNAME).split() or [""])[0].split(".")[0]
    if config.nom_machine:
        res.append((actuel == config.nom_machine, f"Le nom de la machine est {config.nom_machine} (actuel : {actuel or '?'})"))
    secours = systeme.comptes_locaux().get(config.secours)
    sudo = systeme.groupes_locaux().get("sudo")
    res.append((secours is not None and sudo is not None and config.secours in sudo.membres,
                f"Le compte de secours {config.secours} existe et est administrateur"))
    return res
