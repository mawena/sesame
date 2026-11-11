"""Parties de l'assistant qui ne dépendent pas de GTK : constantes, statuts, décodage du journal, validation."""
import importlib
import json
import os
import re
import socket
import types

APPLICATION_ID = 'io.github.mawena.Sesame'
SITE = 'https://mawena.github.io/sesame/'
DEPOT = 'https://github.com/mawena/sesame'
RACINE_INSTALLEE = '/usr/libexec/sesame/sesame-racine'

# statut -> (icône symbolique, classe CSS de l'icône, libellé court)
STATUTS = {
    'fait': ('emblem-ok-symbolic', 'success', 'Fait'),
    'a_faire': ('media-record-symbolic', 'accent', 'À faire'),
    'sans_objet': ('list-remove-symbolic', 'dim-label', 'Sans objet'),
    'programmee': ('alarm-symbolic', 'warning', 'Programmée'),
    'bloquee': ('action-unavailable-symbolic', 'dim-label', 'Bloquée'),
    'inconnu': ('dialog-question-symbolic', 'dim-label', 'Inconnu'),
}


def icone_statut(statut):
    """(icône, classe CSS, libellé) d'un statut ; un statut inattendu est traité comme « inconnu »."""
    return STATUTS.get(statut, STATUTS['inconnu'])


def libelle_bouton(statut):
    """Texte du bouton d'une étape, ou None quand aucun bouton n'a de sens."""
    if statut == 'sans_objet':
        return None
    return 'Refaire' if statut == 'fait' else 'Lancer'


def dossier_depot():
    """Racine du dépôt quand on tourne depuis les sources (bin/sesame-assistant à côté de libexec/), sinon None."""
    racine = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if os.path.exists(os.path.join(racine, 'bin', 'sesame-assistant')) and os.path.isdir(os.path.join(racine, 'libexec')):
        return racine
    return None


def chemin_racine():
    """Chemin de sesame-racine : celui du dépôt depuis les sources, sinon celui du paquet."""
    depot = dossier_depot()
    if depot:
        return os.path.join(depot, 'libexec', 'sesame-racine')
    return RACINE_INSTALLEE


def commande_racine(action, arguments=()):
    """Ligne de commande d'une action root : jamais sudo, toujours pkexec."""
    return ['pkexec', chemin_racine(), '--json', action, *arguments]


ACTIONS = {'premiere_connexion': 'noter-premiere-connexion'}


def action_de_etape(etape):
    """Nom de l'action de sesame-racine d'une étape (dict de lire_etat) : la table ci-dessus d'abord, puis le champ
    « action » de l'étape, puis son id avec des tirets."""
    return ACTIONS.get(etape['id']) or etape.get('action') or etape['id'].replace('_', '-')


def nom_machine_actuel():
    """Nom d'hôte sans domaine : la valeur préremplie du champ « Nom de la machine »."""
    return socket.gethostname().split('.')[0]


def charger_coeur():
    """Modules du cœur, importés à la demande (ce qui laisse les tests injecter de faux modules)."""
    noms = ('systeme', 'config', 'etapes', 'verification', 'version')
    modules = {n: importlib.import_module('sesame.' + n) for n in noms}
    try:
        modules['compilation'] = importlib.import_module('sesame.compilation')
    except ImportError:
        modules['compilation'] = None
    return types.SimpleNamespace(**modules)


def dossier_compilation(coeur, config=None):
    """Dossier de compilation de Himmelblau : celui de sesame.conf, sinon celui par défaut."""
    return getattr(config, 'dossier_compilation', '') or coeur.compilation.dossier_par_defaut()


def argv_compilation(coeur, dossier):
    """Commande de compilation, lancée sous l'utilisateur (jamais pkexec) : la file Gagarine si elle est là."""
    c = coeur.compilation
    argv = c.commande_file(dossier) or c.commande_directe(dossier)
    return list(argv) + ['--json']


def argv_paquets(dossier):
    return ['--paquets', os.path.join(dossier, 'packaging')]



def lire_etats(coeur, systeme):
    """Liste d'états des étapes : etapes.lire_etat, sinon la clé « etapes » de etapes.etat_complet."""
    fonction = getattr(coeur.etapes, 'lire_etat', None)
    if fonction is not None:
        return fonction(systeme)
    return coeur.etapes.etat_complet(systeme)['etapes']


def statut_etape(etats, identifiant):
    """Statut de l'étape d'identifiant donné, None si elle n'est pas dans la liste."""
    for e in etats or ():
        if e.get('id') == identifiant:
            return e.get('statut')
    return None


def deja_relie(etats):
    """Le compte est relié à Entra quand l'étape « configurer » est faite."""
    return statut_etape(etats, 'configurer') == 'fait'


def texte_final(nom, compte):
    return ('Le poste %s est prêt. Déconnectez-vous, choisissez votre compte à l’écran d’accueil, tapez le mot de '
            'passe Entra de %s et validez sur le téléphone. Le poste sera inscrit dans Entra à cette première '
            'connexion, puis vous choisirez un code PIN (Windows Hello) pour les connexions suivantes.') % (nom, compte)


# --- journal -----------------------------------------------------------------------------------------------------

def decoder_ligne(ligne):
    """Décode une ligne de sesame-racine --json en dict {'type', 'texte', 'ok', 'message'}.
    Une ligne qui n'est pas du JSON (par exemple une erreur de pkexec) devient une ligne de sortie."""
    ligne = ligne.rstrip('\r\n')
    try:
        obj = json.loads(ligne)
    except ValueError:
        obj = None
    if not isinstance(obj, dict) or not isinstance(obj.get('type'), str):
        return {'type': 'sortie', 'texte': ligne}
    return {'type': obj['type'], 'texte': str(obj.get('texte', '')), 'ok': bool(obj.get('ok', False)),
            'message': str(obj.get('message', ''))}


def mise_en_forme(evenement):
    """(balise, texte) à écrire dans le journal pour un événement décodé."""
    t = evenement['type']
    if t == 'etape':
        return 'etape', '\n▶ ' + evenement['texte'] + '\n'
    if t == 'compilation_requise':
        return 'etape', '\n▶ Himmelblau doit maintenant être compilé\n'
    if t == 'commande':
        return 'commande', '$ ' + evenement['texte'] + '\n'
    if t == 'avertissement':
        return 'avertissement', '! ' + evenement['texte'] + '\n'
    if t == 'fin':
        marque = '✔ ' if evenement['ok'] else '✘ '
        return ('fin-ok' if evenement['ok'] else 'fin-erreur'), marque + evenement['message'] + '\n'
    return 'sortie', '  ' + evenement['texte'] + '\n'


# --- validation des champs ---------------------------------------------------------------------------------------

_UPN = re.compile(r'^[^@\s]+@[^@\s.]+(\.[^@\s.]+)+$')
_NOM_MACHINE = re.compile(r'^(?!-)(?!\d+$)[A-Za-z0-9-]{1,15}(?<!-)$')

MESSAGES = {'compte': 'Une adresse a la forme prenom.nom@entreprise.com',
            'nom_machine': '1 à 15 lettres, chiffres ou « - », sans « - » au début ni à la fin, pas uniquement des chiffres'}


def _interprete(retour, texte):
    """Rend (valide, texte normalisé) quelle que soit la forme de la réponse d'un validateur du cœur
    (booléen, texte normalisé, tuple, ou exception ValueError)."""
    if isinstance(retour, tuple):
        retour = retour[0] if retour else False
    if isinstance(retour, str):
        return bool(retour), retour or texte
    return bool(retour), texte


def valider_champ(coeur, champ, texte):
    """Rend ('vide' | 'ok' | 'erreur', texte normalisé, message d'erreur) pour un champ du formulaire :
    'compte' ou 'nom_machine'."""
    texte = texte.strip()
    if not texte:
        return 'vide', '', ''
    if champ == 'compte':
        fonction, motif = getattr(coeur.config, 'valider_upn', None), _UPN
    else:
        fonction, motif = getattr(coeur.config, 'valider_nom_machine', None), _NOM_MACHINE
    if fonction is None:
        ok, norme = bool(motif.match(texte)), texte
    else:
        try:
            ok, norme = _interprete(fonction(texte), texte)
        except ValueError:
            ok, norme = False, texte
    if ok and champ == 'compte':
        norme = norme.lower()
    return ('ok', norme, '') if ok else ('erreur', texte, MESSAGES[champ])


def valider_secours(mdp1, mdp2):
    """None si les deux mots de passe conviennent, sinon le message à afficher."""
    if len(mdp1) < 8:
        return 'Au moins 8 caractères'
    if mdp1 != mdp2:
        return 'Les deux mots de passe doivent être identiques'
    return None
