"""Reprise du compte local par le compte Entra, et annulation (voir « Reprise » dans la conception).

Point critique : `authctl user set-home` déplace le contenu de l'ancien dossier. Le vrai dossier H ne doit donc
jamais être le dossier courant du compte Entra quand on appelle `set-home` ou `set-uid` : on l'écarte en
`H.sesame-reprise` le temps de l'appel.
"""
import re
from dataclasses import asdict, dataclass

from . import chemins, etat, sauvegarde
from .systeme import ErreurSesame

SUFFIXE = ".sesame-reprise"
MODES = ("maintenant", "au-demarrage", "execution-demarrage")


class ErreurReprise(ErreurSesame):
    """Une précondition manque ou une étape a échoué."""


@dataclass
class Parametres:
    """Ce qu'il faut savoir pour reprendre : compte local A (UID U, GID G, dossier H) et compte Entra N."""
    compte_local: str
    compte_entra: str
    uid: int
    gid: int
    dossier: str
    secours: str = "secours"

    @classmethod
    def depuis_config(cls, config):
        return cls(config.compte_local, config.compte, config.uid, config.gid, config.dossier, config.secours)

    @classmethod
    def depuis_dict(cls, donnees):
        return cls(**{k: donnees[k] for k in ("compte_local", "compte_entra", "uid", "gid", "dossier")},
                   secours=donnees.get("secours", "secours"))


# --- préconditions
def verifier(systeme, p, mode):
    """Contrôle les préconditions sans rien modifier. Renvoie (NU, NG, NH) ; lève ErreurReprise sinon."""
    locaux = systeme.comptes_locaux()
    a = locaux.get(p.compte_local)
    if a is None or a.uid != p.uid:
        raise ErreurReprise(f"Le compte local {p.compte_local} n'existe pas avec l'UID {p.uid} (déjà repris ?).")
    if not systeme.est_dossier(p.dossier):
        raise ErreurReprise(f"Le dossier {p.dossier} est introuvable.")
    if systeme.existe(p.dossier + SUFFIXE):
        raise ErreurReprise(f"{p.dossier + SUFFIXE} existe : une reprise précédente a laissé le dossier de côté. "
                            "Lancez d'abord « sesame annuler-reprise ».")
    if systeme.existe(chemins.REPRISE_ETAT):
        raise ErreurReprise("Une reprise est déjà en cours ou interrompue : lancez d'abord « sesame annuler-reprise ».")
    if p.compte_entra in locaux:
        raise ErreurReprise(f"{p.compte_entra} est dans /etc/passwd : ce n'est pas un compte authd.")
    n = systeme.utilisateur(p.compte_entra)
    if n is None:
        raise ErreurReprise(f"{p.compte_entra} est inconnu : faites d'abord la première connexion par Entra.")
    if n.uid == p.uid:
        raise ErreurReprise(f"Le compte Entra a déjà l'UID {p.uid}.")
    if n.dossier == p.dossier:
        raise ErreurReprise(f"Le compte Entra pointe déjà sur {p.dossier}.")
    if not systeme.programme_present("authctl"):
        raise ErreurReprise("authctl est absent : installez d'abord authd.")
    if mode != "au-demarrage":
        _verifier_processus(systeme, p, n.uid, mode)
    return n.uid, n.gid, n.dossier


def _verifier_processus(systeme, p, nu, mode):
    for uid, nom in ((p.uid, p.compte_local), (nu, p.compte_entra)):
        procs = systeme.processus_uid(uid)
        if procs:
            exemples = ", ".join(n for _, n in procs[:5])
            raise ErreurReprise(f"Des programmes tournent encore sous {nom} ({exemples}) : fermez cette session.")
    if mode == "maintenant" and systeme.uid_appelant() == p.uid:
        raise ErreurReprise(f"Lancez la reprise depuis un autre compte que {p.compte_local} (le compte de secours).")


# --- reprise
def _terminer(systeme, ok, message, mode):
    systeme.ecrire_json(chemins.DERNIERE_REPRISE,
                        {"ok": ok, "message": message, "date": systeme.date_iso(), "mode": mode}, 0o644)
    return ok, message


def reprendre(systeme, p, mode):
    """Fait la reprise ; renvoie (ok, message). Annule seule si elle échoue à partir de l'étape 3."""
    try:
        nu, ng, nh = verifier(systeme, p, mode)
        sauv = _preparer(systeme, p, nu, ng, nh)
    except Exception as e:  # rien n'a encore été modifié : pas d'annulation
        return _terminer(systeme, False, str(e), mode)
    try:
        _supprimer_compte(systeme, p)
        _identifiants(systeme, p)
        _deplacer_dossier(systeme, p, nh, sauv)
        reglages = _reglages(systeme, p, sauv)
        systeme.etape("Rechargement de systemd")
        systeme.executer(["systemctl", "daemon-reload"])
        etat.noter(systeme, "reprise", dict(reglages, date=systeme.date_iso(), compte_entra=p.compte_entra))
    except Exception as e:  # toute erreur, même inattendue, déclenche l'annulation
        ok, retour = annuler(systeme, verifier_processus=False, mode=mode, ecrire_resultat=False)
        suite = "Le compte local est restauré." if ok else f"L'annulation a échoué : {retour}"
        return _terminer(systeme, False, f"Échec de la reprise : {e}. {suite}", mode)
    horo = systeme.horodatage()
    message = f"{p.compte_entra} a repris le compte {p.compte_local} (UID {p.uid}, dossier {p.dossier})."
    _terminer(systeme, True, message, mode)
    systeme.deplacer(chemins.REPRISE_ETAT, f"{chemins.VAR_SESAME}/reprise-etat.termine-{horo}.json")
    return True, message


def _preparer(systeme, p, nu, ng, nh):
    """Étapes 1 et 2 : sauvegarde `avant-reprise` puis état de la reprise."""
    systeme.etape("Sauvegarde avant la reprise")
    sauv = sauvegarde.faire(systeme, p.compte_local, "avant-reprise")
    systeme.ecrire_json(chemins.REPRISE_ETAT, {
        "compte_local": p.compte_local, "compte_entra": p.compte_entra, "uid": p.uid, "gid": p.gid,
        "dossier": p.dossier, "entra_uid": nu, "entra_gid": ng, "entra_dossier": nh,
        "horodatage": systeme.horodatage(), "sauvegarde": sauv}, 0o600)
    return sauv


def _supprimer_compte(systeme, p):
    """Étape 3 : le compte local disparaît (sans son dossier) et libère l'UID et le GID."""
    systeme.etape(f"Suppression du compte local {p.compte_local}")
    systeme.executer(["userdel", p.compte_local])
    if p.compte_local in systeme.groupes_locaux():
        systeme.executer(["groupdel", p.compte_local])
    systeme.supprimer(f"{chemins.CRONTABS}/{p.compte_local}")


def _identifiants(systeme, p):
    """Étape 4 : le compte Entra prend l'UID et le GID."""
    systeme.etape("UID et GID du compte Entra")
    systeme.executer(["authctl", "user", "set-uid", p.compte_entra, p.uid])
    systeme.executer(["authctl", "group", "set-gid", p.compte_entra, p.gid])


def _remettre(systeme, reserve, dossier):
    """Remet le dossier écarté à sa place ; un dossier vide créé entre-temps par authctl est retiré."""
    if systeme.existe(dossier):
        if not systeme.est_vide(dossier):
            raise ErreurReprise(f"{dossier} existe et n'est pas vide : le dossier d'origine reste dans {reserve}.")
        systeme.supprimer(dossier)
    systeme.deplacer(reserve, dossier)


def _deplacer_dossier(systeme, p, nh, sauv):
    """Étape 5 : le compte Entra pointe sur H sans que authctl ne déplace son contenu."""
    systeme.etape(f"Le compte Entra prend le dossier {p.dossier}")
    reserve = p.dossier + SUFFIXE
    systeme.deplacer(p.dossier, reserve)
    if systeme.existe(nh):
        systeme.deplacer(nh, f"{sauv}/dossier-entra-vierge")
    systeme.executer(["authctl", "user", "set-home", p.compte_entra, p.dossier])
    _remettre(systeme, reserve, p.dossier)


# --- réglages qui citaient l'ancien compte
def _remplacer(systeme, chemin, motif, remplacement):
    """Remplace dans un fichier ; renvoie vrai s'il a changé."""
    texte = systeme.lire(chemin, None)
    if texte is None:
        return False
    nouveau = re.sub(motif, remplacement, texte, flags=re.M)
    if nouveau != texte:
        systeme.ecrire(chemin, nouveau)
    return nouveau != texte


def _unites(systeme, p):
    """User=A / Group=A deviennent U / G ; une surcharge attend authd. Renvoie les unités modifiées."""
    modifiees = []
    for nom in systeme.lister(chemins.UNITES_SYSTEME):
        chemin = f"{chemins.UNITES_SYSTEME}/{nom}"
        if not nom.endswith(".service") or not systeme.chemin(chemin).is_file():
            continue
        a = re.escape(p.compte_local)
        texte = systeme.lire(chemin)
        nouveau = re.sub(rf"^User={a}[ \t]*$", f"User={p.uid}", texte, flags=re.M)
        nouveau = re.sub(rf"^Group={a}[ \t]*$", f"Group={p.gid}", nouveau, flags=re.M)
        if nouveau != texte:
            systeme.ecrire(chemin, nouveau)
            systeme.ecrire(f"{chemin}.d/sesame-authd.conf",
                           "[Unit]\n# Le compte vient d'authd : attendre le service.\nAfter=authd.socket authd.service\n")
            modifiees.append(nom)
    return modifiees


def _accountsservice(systeme, p):
    """Les réglages d'AccountsService de A sont copiés sous le nom de N (icône comprise)."""
    base = chemins.ACCOUNTSSERVICE
    if not systeme.existe(f"{base}/users/{p.compte_local}"):
        return
    systeme.copier(f"{base}/users/{p.compte_local}", f"{base}/users/{p.compte_entra}")
    if systeme.existe(f"{base}/icons/{p.compte_local}"):
        systeme.copier(f"{base}/icons/{p.compte_local}", f"{base}/icons/{p.compte_entra}")
        _remplacer(systeme, f"{base}/users/{p.compte_entra}",
                   rf"icons/{re.escape(p.compte_local)}$", f"icons/{p.compte_entra}")


def _reglages(systeme, p, sauv):
    """Étape 6 ; renvoie {"unites": [...], "crontab": bool} pour la vérification."""
    systeme.etape("Réglages qui citaient l'ancien compte")
    a = re.escape(p.compte_local)
    for fichier in (chemins.SUBUID, chemins.SUBGID):
        _remplacer(systeme, fichier, rf"^{a}:", f"{p.uid}:")
    unites = _unites(systeme, p)
    _remplacer(systeme, chemins.VMWARE_AUTORISATION, rf"<ACEDataUser>{a}</ACEDataUser>",
               f"<ACEDataUser>{p.compte_entra}</ACEDataUser>")
    _remplacer(systeme, chemins.GDM_CUSTOM, rf"^(AutomaticLogin={a})[ \t]*$", r"#\1")
    crontab = bool(systeme.lire(f"{sauv}/crontab-{p.compte_local}").strip())
    if crontab:
        systeme.executer(["crontab", "-u", p.compte_entra, systeme.chemin(f"{sauv}/crontab-{p.compte_local}")])
    _accountsservice(systeme, p)
    return {"unites": unites, "crontab": crontab}


# --- annulation
def annuler(systeme, verifier_processus=True, mode="annulation", ecrire_resultat=True):
    """Annule une reprise d'après reprise-etat.json ; renvoie (ok, message)."""
    e = systeme.lire_json(chemins.REPRISE_ETAT)
    if not e:
        return _fin_annulation(systeme, False, "Aucune reprise à annuler.", mode, False)
    try:
        _annuler(systeme, e, verifier_processus)
    except ErreurSesame as err:
        return _fin_annulation(systeme, False, f"Annulation impossible : {err}", mode, ecrire_resultat)
    systeme.deplacer(chemins.REPRISE_ETAT, f"{chemins.VAR_SESAME}/reprise-etat.annule-{systeme.horodatage()}.json")
    etat.retirer(systeme, "reprise")
    return _fin_annulation(systeme, True, f"La reprise est annulée : {e['compte_local']} a retrouvé son compte.",
                           mode, ecrire_resultat)


def _fin_annulation(systeme, ok, message, mode, ecrire):
    if ecrire:
        _terminer(systeme, False, "Reprise annulée. " + message if ok else message, mode)
    return ok, message


def _annuler(systeme, e, verifier_processus):
    a, n, u, g, h = e["compte_local"], e["compte_entra"], e["uid"], e["gid"], e["dossier"]
    nu, ng, nh, sauv = e["entra_uid"], e["entra_gid"], e["entra_dossier"], e["sauvegarde"]
    if not systeme.est_dossier(sauv):
        raise ErreurSesame(f"La sauvegarde {sauv} est introuvable.")
    if verifier_processus and systeme.processus_uid(u):
        raise ErreurSesame(f"Des programmes tournent sous l'UID {u} : fermez cette session.")
    systeme.etape("Le dossier personnel sort du compte Entra")
    reserve = h + SUFFIXE
    if not systeme.existe(h) and systeme.existe(reserve):
        systeme.deplacer(reserve, h)
    _rendre_dossier(systeme, n, h, nh, reserve)
    _remettre_vierge(systeme, f"{sauv}/dossier-entra-vierge", nh)
    systeme.etape("Le compte Entra rend l'UID et le GID")
    _rendre_identifiants(systeme, n, h, u, g, nu, ng)
    systeme.etape("Restauration des fichiers de /etc")
    _restaurer(systeme, sauv, a, n)
    systeme.etape("Crontab et unités")
    _annuler_reglages(systeme, sauv, a, n)
    systeme.executer(["systemctl", "daemon-reload"])


def _rendre_dossier(systeme, n, h, nh, reserve):
    """Si N pointe sur H : H est écarté, `set-home` rend NH à N, puis H revient (même en cas d'échec)."""
    compte = systeme.utilisateur(n)
    if compte is None or compte.dossier != h:
        return
    if not systeme.existe(h):
        raise ErreurSesame(f"{h} est introuvable alors que {n} y pointe : à vérifier à la main.")
    if systeme.existe(nh):
        raise ErreurSesame(f"{nh} existe déjà : à écarter avant d'annuler.")
    systeme.deplacer(h, reserve)
    try:
        systeme.executer(["authctl", "user", "set-home", n, nh])
    finally:
        _remettre(systeme, reserve, h)


def _remettre_vierge(systeme, vierge, nh):
    if not systeme.existe(vierge):
        return
    if systeme.existe(nh):
        if not systeme.est_vide(nh):
            systeme.avertir(f"{nh} existe : le dossier vierge reste dans {vierge}.")
            return
        systeme.supprimer(nh)
    systeme.deplacer(vierge, nh)


def _rendre_identifiants(systeme, n, h, u, g, nu, ng):
    compte = systeme.utilisateur(n)
    if compte is None:
        return
    if compte.dossier == h:
        raise ErreurSesame(f"Le compte Entra pointe encore sur {h}.")
    if compte.uid == u:
        systeme.executer(["authctl", "user", "set-uid", n, nu])
    groupe = systeme.groupe(n)
    if groupe is not None and groupe.gid == g:
        systeme.executer(["authctl", "group", "set-gid", n, ng])


def _restaurer(systeme, sauv, a, n):
    if systeme.existe(f"{sauv}/etc"):
        systeme.copier(f"{sauv}/etc", "/etc")
    base = chemins.ACCOUNTSSERVICE
    for sous, nom in (("users", a), ("icons", a), ("users", n), ("icons", n)):
        copie = f"{sauv}{base}/{sous}/{nom}"
        if systeme.existe(copie):
            systeme.copier(copie, f"{base}/{sous}/{nom}")
        elif nom == n:
            systeme.supprimer(f"{base}/{sous}/{nom}")


def _annuler_reglages(systeme, sauv, a, n):
    for nom in systeme.lister(chemins.UNITES_SYSTEME):
        if nom.endswith(".service.d"):
            dossier = f"{chemins.UNITES_SYSTEME}/{nom}"
            systeme.supprimer(f"{dossier}/sesame-authd.conf")
            if systeme.est_vide(dossier):
                systeme.supprimer(dossier)
    crontab = f"{sauv}/crontab-{a}"
    if systeme.lire(crontab).strip():
        systeme.executer(["crontab", "-u", a, systeme.chemin(crontab)])
    systeme.executer(["crontab", "-u", n, "-r"], tolerant=True)


# --- démarrage
ORDRE_REPRISE = f"{chemins.UNITES_SYSTEME}/{chemins.UNITE_REPRISE}.d/sesame-ordre.conf"


def unites_du_compte(systeme, p):
    """Services système qui tournent sous le compte local (`User=A` ou `User=U`)."""
    motif = re.compile(rf"^User=({re.escape(p.compte_local)}|{p.uid})[ \t]*$", re.M)
    trouvees = []
    for nom in systeme.lister(chemins.UNITES_SYSTEME):
        chemin = f"{chemins.UNITES_SYSTEME}/{nom}"
        if nom.endswith(".service") and systeme.chemin(chemin).is_file() and motif.search(systeme.lire(chemin)):
            trouvees.append(nom)
    return trouvees


def _ecrire_ordre(systeme, p):
    """Au démarrage, ces services tourneraient déjà sous le compte local et bloqueraient la reprise :
    une surcharge du service de reprise le fait passer avant eux."""
    unites = unites_du_compte(systeme, p)
    if unites:
        systeme.ecrire(ORDRE_REPRISE, "[Unit]\n# Écrit par Sésame : la reprise passe avant les services qui tournent "
                                      "sous le compte local.\nBefore=" + " ".join(unites) + "\n")
    return unites


def _retirer_ordre(systeme):
    systeme.supprimer(ORDRE_REPRISE)
    dossier = ORDRE_REPRISE.rsplit("/", 1)[0]
    if systeme.existe(dossier) and systeme.est_vide(dossier):
        systeme.supprimer(dossier)


def programmer(systeme, p):
    """Écrit reprise-programmee et active le service de démarrage (`enable` recharge systemd)."""
    verifier(systeme, p, "au-demarrage")
    _ecrire_ordre(systeme, p)
    systeme.ecrire_json(chemins.REPRISE_PROGRAMMEE, asdict(p), 0o600)
    try:
        systeme.executer(["systemctl", "enable", chemins.UNITE_REPRISE])
    except ErreurSesame:
        systeme.supprimer(chemins.REPRISE_PROGRAMMEE)
        _retirer_ordre(systeme)
        raise
    return "La reprise aura lieu au prochain démarrage, avant l'écran de connexion."


def annuler_programmation(systeme):
    systeme.supprimer(chemins.REPRISE_PROGRAMMEE)
    _retirer_ordre(systeme)
    systeme.executer(["systemctl", "disable", chemins.UNITE_REPRISE], tolerant=True)
    return "La reprise programmée est retirée."


def executer_demarrage(systeme):
    """Exécutée par le service au démarrage : (ok, message). Le fichier programmé est supprimé avant tout."""
    brut = systeme.lire_json(chemins.REPRISE_PROGRAMMEE)
    systeme.supprimer(chemins.REPRISE_PROGRAMMEE)
    try:
        if not brut:
            ok, message = _terminer(systeme, False, "Aucune reprise programmée.", "execution-demarrage")
        else:
            ok, message = reprendre(systeme, Parametres.depuis_dict(brut), "execution-demarrage")
    except Exception as e:  # le démarrage ne doit jamais être bloqué
        ok, message = _terminer(systeme, False, f"Échec de la reprise : {e!r}", "execution-demarrage")
    try:
        systeme.executer(["systemctl", "disable", chemins.UNITE_REPRISE], tolerant=True)
        _retirer_ordre(systeme)
    except Exception:
        pass
    return ok, message
