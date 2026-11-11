"""Actions root de Sésame : chacune renvoie un message, ou lève ErreurSesame."""
import re
import tarfile

from . import chemins, config as cfg, etapes, etat, himmelblau, nsswitch, sauvegarde
from .systeme import ErreurSesame, ErreurSysteme

MESSAGE_NOM_MACHINE = ("Nom de machine invalide : {!r} (1 à 15 lettres, chiffres ou tirets, sans tiret au début "
                       "ni à la fin, pas uniquement des chiffres).")


def _config_ou_defauts(systeme):
    return cfg.charger(systeme) or cfg.defauts(systeme)


def _noter(systeme, cle, **extra):
    etat.noter(systeme, cle, dict(extra, date=systeme.date_iso()))


def _enregistrer(systeme, **champs):
    """Met à jour sesame.conf (créé à partir des valeurs détectées s'il manque)."""
    c = _config_ou_defauts(systeme)
    for cle, valeur in champs.items():
        setattr(c, cle, valeur)
    cfg.ecrire(systeme, c)
    return c


def compte_local_appelant(systeme):
    """Compte local de la personne derrière pkexec s'il est ordinaire (UID 1000 à 59999), sinon None."""
    uid = systeme.uid_appelant()
    return next((u.nom for u in systeme.comptes_locaux().values() if u.uid == uid and 1000 <= uid <= 59999), None)


def _compte_local(systeme, demande=None):
    """Compte local à relier : celui qui est demandé, sinon l'appelant, sinon le premier compte ordinaire."""
    nom = demande or compte_local_appelant(systeme) or cfg.defauts(systeme).compte_local
    if not nom or nom not in systeme.comptes_locaux():
        raise ErreurSesame(f"Le compte local {nom or '?'} n'existe pas.")
    return nom


# --- 1. sauvegarde
def faire_sauvegarde(systeme, motif=""):
    c = _config_ou_defauts(systeme)
    dossier = sauvegarde.faire(systeme, c.compte_local, motif)
    return f"Configuration sauvegardée dans {dossier}."


# --- 2. secours
def _empreinte(systeme, compte):
    """Empreinte du mot de passe d'un compte local (/etc/shadow, champ 2) ; ErreurSesame si elle est inutilisable."""
    empreinte = None
    for ligne in systeme.lire(chemins.SHADOW).splitlines():
        champs = ligne.split(":")
        if champs[0] == compte and len(champs) > 1:
            empreinte = champs[1]
            break
    if not empreinte or empreinte[0] in "!*" or ":" in empreinte:
        raise ErreurSesame(f"Le compte {compte} n'a pas de mot de passe utilisable : impossible de le copier. "
                           "Choisissez le mot de passe du compte de secours dans le mode avancé de l'assistant.")
    return empreinte


def creer_secours(systeme, nom, mot_de_passe=None, copier_de=None):
    """Crée (ou répare) le compte de secours ; le mot de passe passe par l'entrée standard de chpasswd.
    Sans mot de passe, `copier_de` donne le compte local dont l'empreinte est copiée (`chpasswd -e`)."""
    if not cfg.valider_nom(nom):
        raise ErreurSesame(f"Nom de compte invalide : {nom!r}.")
    existe = nom in systeme.comptes_locaux()
    empreinte = None
    if copier_de and not mot_de_passe and not existe:
        if copier_de not in systeme.comptes_locaux():
            raise ErreurSesame(f"Le compte local {copier_de} n'existe pas : impossible d'en copier le mot de passe.")
        empreinte = _empreinte(systeme, copier_de)
    if not existe and not mot_de_passe and not empreinte:
        raise ErreurSesame("Un mot de passe est nécessaire pour créer le compte de secours.")
    if mot_de_passe and (len(mot_de_passe) < 8 or "\n" in mot_de_passe):
        raise ErreurSesame("Le mot de passe doit faire au moins 8 caractères, sur une seule ligne.")
    if existe:
        systeme.executer(["usermod", "-aG", "sudo", nom])
    else:
        systeme.executer(["useradd", "-m", "-s", "/bin/bash", "-c", "Compte de secours (Sésame)", "-G", "sudo", nom])
    if mot_de_passe:
        systeme.executer(["chpasswd"], entree=f"{nom}:{mot_de_passe}\n")
    elif empreinte:
        systeme.executer(["chpasswd", "-e"], entree=f"{nom}:{empreinte}\n")
    _enregistrer(systeme, secours=nom)
    return f"Le compte de secours {nom} est prêt."


# --- 3. nom de la machine
def _nom_machine_actuel(systeme):
    """Nom statique (/etc/hostname), sans domaine ni espaces."""
    lignes = systeme.lire(chemins.HOSTNAME).split()
    return lignes[0].split(".")[0] if lignes else ""


def changer_nom_machine(systeme, nom):
    """Nom statique de la machine, ligne 127.0.1.1 de /etc/hosts et sesame.conf ; casse gardée."""
    if not cfg.valider_nom_machine(nom):
        raise ErreurSesame(MESSAGE_NOM_MACHINE.format(nom))
    if _nom_machine_actuel(systeme) != nom:
        systeme.executer(["hostnamectl", "hostname", nom])
        lignes = systeme.lire(chemins.HOSTS).splitlines()
        nouvelle = f"127.0.1.1\t{nom}"
        if any(re.match(r"127\.0\.1\.1(\s|$)", l) for l in lignes):
            lignes = [nouvelle if re.match(r"127\.0\.1\.1(\s|$)", l) else l for l in lignes]
        else:
            rang = next((i for i, l in enumerate(lignes) if re.match(r"127\.0\.0\.1(\s|$)", l)), -1)
            lignes.insert(rang + 1, nouvelle)
        systeme.ecrire(chemins.HOSTS, "\n".join(lignes) + "\n")
        message = f"La machine s'appelle maintenant {nom}."
    else:
        message = f"La machine s'appelle déjà {nom}."
    _enregistrer(systeme, nom_machine=nom)
    return message


# --- 4. quitter le domaine AD
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


# --- 5. outils de compilation
def _plage(systeme, fichier, compte):
    """Vrai si /etc/subuid (ou subgid) donne une plage au compte."""
    return any(l.split(":")[0] == compte for l in systeme.lire(fichier).splitlines())


def installer_outils(systeme, compte_local=None):
    """Installe podman, uidmap, git et make ; donne au compte local une plage subuid/subgid s'il n'en a pas."""
    local = _compte_local(systeme, compte_local)
    systeme.etape("Installation des outils de compilation")
    try:
        systeme.executer(["apt-get", "install", "-y"] + list(himmelblau.OUTILS))
    except ErreurSysteme as e:
        raise ErreurSesame(f"L'installation des outils de compilation a échoué ({e}). Vérifiez la connexion Internet "
                           "du poste ; relancer « Rejoindre » reprend là où on s'était arrêté.") from None
    if not (_plage(systeme, chemins.SUBUID, local) and _plage(systeme, chemins.SUBGID, local)):
        systeme.etape(f"Plage d'identifiants pour {local}")
        systeme.executer(["usermod", "--add-subuids", "100000-165535", "--add-subgids", "100000-165535", local])
    return "Les outils de compilation sont installés."


# --- 6. installer
def _paquets_manquants(systeme):
    return etapes.paquets_manquants(systeme)


def _debs(systeme, paquets):
    """{paquet: chemin du .deb} dans le dossier `paquets` ; ErreurSesame si le dossier n'existe pas."""
    if not paquets or not systeme.est_dossier(paquets):
        raise ErreurSesame(f"Le dossier des paquets Himmelblau n'existe pas : {paquets or '(non indiqué)'}. "
                           "Compilez d'abord Himmelblau.")
    trouves = himmelblau.debs_dans([n for n in systeme.lister(paquets) if n.endswith(".deb")])
    return {p: f"{paquets.rstrip('/')}/{n}" for p, n in trouves.items()}


def _paquets_complets(systeme, paquets):
    try:
        return all(p in _debs(systeme, paquets) for p in himmelblau.PAQUETS)
    except ErreurSesame:
        return False


def installer(systeme, paquets):
    """Installe les .deb compilés du dossier `paquets` (obligatoires, puis optionnels s'ils existent)."""
    version = etapes.version_ubuntu(systeme)
    if version is None or version < (24, 4):
        raise ErreurSesame("Sésame demande Ubuntu 24.04 ou plus récent.")
    debs = _debs(systeme, paquets)
    absents = [p for p in himmelblau.PAQUETS if p not in debs]
    if absents:
        raise ErreurSesame("Il manque dans " + paquets + " le paquet " + ", ".join(absents)
                           + " : recompilez Himmelblau.")
    for paquet, chemin in debs.items():
        r = systeme.lancer(["dpkg-deb", "-f", chemin, "Package"])
        if not r.ok or r.sortie.strip() != paquet:
            raise ErreurSesame(f"Le fichier {chemin} n'est pas le paquet {paquet} : recompilez Himmelblau.")
    systeme.etape("Installation de Himmelblau")
    try:
        systeme.executer(["apt-get", "install", "-y"] + [debs[p] for p in himmelblau.PAQUETS])
    except ErreurSysteme as e:
        raise ErreurSesame(f"L'installation de Himmelblau a échoué ({e}). Relancer « Rejoindre » reprend là où on "
                           "s'était arrêté.") from None
    optionnels = [debs[p] for p in himmelblau.PAQUETS_OPTIONNELS if p in debs]
    if optionnels and systeme.existe(chemins.APPARMOR):
        if not systeme.executer(["apt-get", "install", "-y"] + optionnels, tolerant=True).ok:
            systeme.avertir("himmelblau-apparmor n'a pas pu être installé : AppArmor pourrait gêner Himmelblau.")
    r = systeme.lancer(["dpkg-query", "-W", "-f=${Version}", "himmelblau"])
    numero = r.sortie.strip() if r.ok else "?"
    _noter(systeme, "installer", himmelblau=numero)
    return f"Himmelblau {numero} est installé."


# --- 7. configurer
def _retablir_integration(systeme):
    """Remet Himmelblau dans PAM et NSS s'il en a été retiré (par « désactiver », par exemple)."""
    if "pam_himmelblau" not in systeme.lire(chemins.PAM_COMMON_AUTH):
        systeme.executer(["pam-auth-update", "--enable", _profil_pam(systeme)], tolerant=True)
    nss = systeme.lire(chemins.NSSWITCH)
    if nss and nsswitch.manque(nss, "himmelblau"):
        systeme.ecrire(chemins.NSSWITCH, nsswitch.ajouter_service(nss, nsswitch.BASES_HIMMELBLAU, "himmelblau"))


def _controler_integration(systeme):
    """Signale (sans échouer) ce que les paquets auraient dû configurer : NSS et PAM."""
    nss = systeme.lire(chemins.NSSWITCH)
    if nsswitch.manque(nss, "himmelblau"):
        systeme.avertir("nsswitch.conf ne cite pas himmelblau pour passwd et group : "
                        "essayez « sudo update-nss add himmelblau » ou réinstallez nss-himmelblau.")
    if "pam_himmelblau" not in systeme.lire(chemins.PAM_COMMON_AUTH):
        systeme.avertir("PAM n'utilise pas pam_himmelblau (/etc/pam.d/common-auth) : "
                        "essayez « sudo pam-auth-update » et cochez Himmelblau.")


def configurer(systeme, compte, compte_local=None):
    compte = cfg.normaliser_upn(compte)
    if not cfg.valider_upn(compte):
        raise ErreurSesame("L'adresse pro doit ressembler à prenom.nom@entreprise.com.")
    local = _compte_local(systeme, compte_local)
    manque = _paquets_manquants(systeme)
    if manque:
        raise ErreurSesame("Himmelblau n'est pas installé (manque : " + ", ".join(manque) + ") : "
                           "faites d'abord l'étape « Installer Himmelblau ».")
    systeme.etape("Configuration de Himmelblau")
    existant = systeme.lire(himmelblau.CONFIG, None)
    if existant is not None and not systeme.existe(himmelblau.CONFIG + ".sesame-origine"):
        systeme.copier(himmelblau.CONFIG, himmelblau.CONFIG + ".sesame-origine")
    systeme.ecrire(himmelblau.CONFIG, himmelblau.texte_config(existant or "", himmelblau.domaine(compte),
                                                              himmelblau.USER_MAP), 0o644)
    systeme.ecrire(himmelblau.USER_MAP, himmelblau.texte_user_map(systeme.lire(himmelblau.USER_MAP), local, compte),
                   0o644)
    systeme.etape("Démarrage des services")
    systeme.executer(["systemctl", "enable", "--now"] + himmelblau.SERVICES)
    systeme.executer(["systemctl", "restart"] + himmelblau.SERVICES)
    _retablir_integration(systeme)
    _controler_integration(systeme)
    u = systeme.comptes_locaux()[local]
    _enregistrer(systeme, compte=compte, compte_local=local, uid=u.uid, gid=u.gid, dossier=u.dossier)
    _noter(systeme, "configurer", compte=compte, compte_local=local)
    return (f"Le compte {local} est relié à {compte} : il garde son dossier et ses réglages, et se connecte avec "
            "le mot de passe Entra.")


# --- 8. première connexion
def noter_premiere_connexion(systeme):
    _noter(systeme, "premiere_connexion")
    return "Première connexion notée."


# --- rejoindre Entra d'un seul geste
def _fait(systeme, id_, c=None):
    """Vrai si l'étape est faite (ou sans objet) d'après la détection (sans root) des étapes."""
    return etapes.DETECTIONS[id_](systeme, c or _config_ou_defauts(systeme))[0] in (etapes.FAIT, etapes.SANS_OBJET)


def _sauter(systeme, texte, fait):
    """Annonce l'étape ; vrai s'il faut la faire."""
    systeme.etape(f"{texte} : déjà fait" if fait else texte)
    return not fait


def rejoindre(systeme, compte, nom_machine, compte_local=None, paquets=None):
    """Toutes les étapes root pour rejoindre Entra ; chacune est sautée si elle est déjà faite, donc relancer
    après un échec reprend où l'on s'était arrêté. Tout est validé avant la première modification.
    Si Himmelblau n'est pas installé et que `paquets` (dossier des .deb compilés) est incomplet, s'arrête en
    réussite après les outils avec un événement `compilation_requise` : l'appelant compile, puis relance."""
    compte = cfg.normaliser_upn(compte)
    if not cfg.valider_upn(compte):
        raise ErreurSesame("L'adresse pro doit ressembler à prenom.nom@entreprise.com.")
    if not cfg.valider_nom_machine(nom_machine):
        raise ErreurSesame(MESSAGE_NOM_MACHINE.format(nom_machine))
    local = _compte_local(systeme, compte_local)
    secours = _config_ou_defauts(systeme).secours or "secours"
    if secours not in systeme.comptes_locaux():
        _empreinte(systeme, local)  # lève l'erreur tout de suite si le mot de passe n'est pas copiable
    version = etapes.version_ubuntu(systeme)
    if version is None or version < (24, 4):
        raise ErreurSesame("Sésame demande Ubuntu 24.04 ou plus récent.")

    if _sauter(systeme, "Sauvegarde de la configuration", etat.derniere_sauvegarde(systeme) is not None):
        sauvegarde.faire(systeme, local, "rejoindre")
    if _sauter(systeme, f"Compte de secours {secours}", _fait(systeme, "secours")):
        creer_secours(systeme, secours, copier_de=local)
    nom_fait = _nom_machine_actuel(systeme) == nom_machine and _enregistre(systeme, "nom_machine") == nom_machine
    if _sauter(systeme, f"Nom de la machine : {nom_machine}", nom_fait):
        changer_nom_machine(systeme, nom_machine)
    if _sauter(systeme, "Sortie du domaine Active Directory", _fait(systeme, "quitter_ad")):
        quitter_ad(systeme)
    if paquets:
        dossier = paquets.rstrip("/").rpartition("/")[0]
        if _enregistre(systeme, "dossier_compilation") != dossier:
            _enregistrer(systeme, dossier_compilation=dossier)
    if _sauter(systeme, "Outils de compilation", _fait(systeme, "outils")):
        installer_outils(systeme, local)
    installe = not _paquets_manquants(systeme)
    if not installe and not _paquets_complets(systeme, paquets):
        systeme.dire("compilation_requise", paquets or "")
        return "Préparation terminée : Himmelblau doit maintenant être compilé."
    if _sauter(systeme, "Installation de Himmelblau", installe):
        installer(systeme, paquets)
    enregistre = cfg.charger(systeme)
    deja = (enregistre is not None and enregistre.compte == compte and enregistre.compte_local == local
            and _fait(systeme, "configurer", enregistre))
    if _sauter(systeme, "Liaison du compte à Entra", deja):
        configurer(systeme, compte, local)
    _noter(systeme, "rejoindre")
    return (f"Le poste {nom_machine} est prêt. Déconnectez-vous, choisissez votre compte à l'écran d'accueil, "
            f"tapez le mot de passe Entra de {compte} et validez sur le téléphone. Le poste sera inscrit dans Entra "
            "à cette première connexion, puis vous choisirez un code PIN (Windows Hello) pour les connexions "
            "suivantes.")


def _enregistre(systeme, champ):
    c = cfg.charger(systeme)
    return getattr(c, champ) if c else ""


# --- désactiver
def _profil_pam(systeme):
    """Nom du profil pam-auth-update de Himmelblau, lu dans /usr/share/pam-configs/."""
    for nom in systeme.lister(chemins.PAM_CONFIGS):
        if "himmelblau" in nom.lower() or "pam_himmelblau" in systeme.lire(f"{chemins.PAM_CONFIGS}/{nom}"):
            return nom
    return "himmelblau"


def desactiver(systeme):
    """Retour à la connexion locale seule : rien n'est désinstallé, « rejoindre » rétablit tout."""
    c = _config_ou_defauts(systeme)
    local = c.compte_local or _compte_local(systeme)
    systeme.etape("Retrait du compte de user-map")
    if systeme.existe(himmelblau.USER_MAP):
        systeme.ecrire(himmelblau.USER_MAP, himmelblau.retirer_user_map(systeme.lire(himmelblau.USER_MAP), local), 0o644)
    systeme.etape("Retrait de Himmelblau de PAM")
    if not systeme.executer(["pam-auth-update", "--disable", _profil_pam(systeme)], tolerant=True).ok:
        systeme.avertir("pam-auth-update n'a pas pu retirer Himmelblau de PAM : à vérifier.")
    systeme.etape("Arrêt des services")
    systeme.executer(["systemctl", "disable", "--now"] + himmelblau.SERVICES, tolerant=True)
    etat.retirer(systeme, "configurer")
    _noter(systeme, "desactiver")
    return "La connexion Entra est coupée (rien n'est désinstallé). « Rejoindre » la rétablit."
