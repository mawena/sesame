"""Parties de l'assistant qui ne dépendent pas de GTK : constantes, statuts, décodage du journal, validation."""
import importlib
import json
import os
import re
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


def action_de_etape(etape):
    """Nom de l'action de sesame-racine d'une étape (dict de lire_etat)."""
    return etape.get('action') or etape['id'].replace('_', '-')


def charger_coeur():
    """Modules du cœur, importés à la demande (ce qui laisse les tests injecter de faux modules)."""
    noms = ('systeme', 'config', 'etapes', 'verification', 'guide', 'version')
    return types.SimpleNamespace(**{n: importlib.import_module('sesame.' + n) for n in noms})


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
    if t == 'commande':
        return 'commande', '$ ' + evenement['texte'] + '\n'
    if t == 'avertissement':
        return 'avertissement', '! ' + evenement['texte'] + '\n'
    if t == 'fin':
        marque = '✔ ' if evenement['ok'] else '✘ '
        return ('fin-ok' if evenement['ok'] else 'fin-erreur'), marque + evenement['message'] + '\n'
    return 'sortie', '  ' + evenement['texte'] + '\n'


# --- validation des champs ---------------------------------------------------------------------------------------

_COMPTE_LOCAL = re.compile(r'^[a-z_][a-z0-9_-]{0,31}$')
_GUID = re.compile(r'^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$')
_UPN = re.compile(r'^[^@\s]+@[^@\s.]+(\.[^@\s.]+)+$')


def _interprete(retour, texte):
    """Rend (valide, texte normalisé) quelle que soit la forme de la réponse d'un validateur du cœur
    (booléen, texte normalisé, tuple, ou exception ValueError)."""
    if isinstance(retour, tuple):
        retour = retour[0] if retour else False
    if isinstance(retour, str):
        return bool(retour), retour or texte
    return bool(retour), texte


def valider_champ(coeur, champ, texte):
    """Rend ('vide' | 'ok' | 'erreur', texte normalisé, message d'erreur) pour un champ de l'assistant."""
    texte = texte.strip()
    if not texte:
        return 'vide', '', ''
    messages = {'locataire': 'Un identifiant a la forme 00000000-0000-0000-0000-000000000000',
                'client': 'Un identifiant a la forme 00000000-0000-0000-0000-000000000000',
                'compte': 'Une adresse a la forme prenom.nom@entreprise.com',
                'compte_local': 'Lettres minuscules, chiffres, « - » et « _ » seulement'}
    if champ in ('locataire', 'client'):
        fonction, motif = getattr(coeur.config, 'valider_guid', None), _GUID
    elif champ == 'compte':
        fonction, motif = getattr(coeur.config, 'valider_upn', None), _UPN
    else:
        fonction, motif = None, _COMPTE_LOCAL
    if fonction is None:
        ok, norme = bool(motif.match(texte)), texte.lower() if champ == 'compte' else texte
    else:
        try:
            ok, norme = _interprete(fonction(texte), texte)
        except ValueError:
            ok, norme = False, texte
    if ok and champ == 'compte':
        norme = norme.lower()
    return ('ok', norme, '') if ok else ('erreur', texte, messages[champ])


def valider_secours(mdp1, mdp2):
    """None si les deux mots de passe conviennent, sinon le message à afficher."""
    if len(mdp1) < 8:
        return 'Au moins 8 caractères'
    if mdp1 != mdp2:
        return 'Les deux mots de passe doivent être identiques'
    return None


def texte_etape_suivante(etats):
    """Texte du bandeau d'après la liste d'états de lire_etat."""
    suivante = None
    for e in etats:
        if e.get('statut') in ('a_faire', 'inconnu'):
            suivante = e
            break
    if suivante is None:
        return 'Tout est en place'
    return 'Étape suivante : ' + suivante['titre']
