"""Dialogues de l'assistant : secours, première connexion, confirmation, vérification."""
import gi

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Adw, GLib, Gtk

from . import donnees, lanceur


def _alerte(titre, corps, reponses, defaut=None, fermeture='annuler'):
    """Crée un Adw.AlertDialog. reponses : liste de (id, libellé, apparence ou None)."""
    d = Adw.AlertDialog(heading=titre, body=corps)
    for identifiant, libelle, apparence in reponses:
        d.add_response(identifiant, libelle)
        if apparence:
            d.set_response_appearance(identifiant, apparence)
    if defaut:
        d.set_default_response(defaut)
    d.set_close_response(fermeture)
    return d


def secours(parent, nom, rappel):
    """Demande deux fois le mot de passe du compte de secours ; rappel(mot_de_passe) si validé."""
    d = _alerte('Compte de secours', 'Choisissez le mot de passe du compte « %s », administrateur de dépannage : il '
                'servira si la connexion Entra ne marche plus. Il n’est écrit nulle part.' % nom,
                [('annuler', 'Annuler', None), ('creer', 'Créer', Adw.ResponseAppearance.SUGGESTED)], 'creer')
    liste = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
    liste.add_css_class('boxed-list')
    un = Adw.PasswordEntryRow(title='Mot de passe')
    deux = Adw.PasswordEntryRow(title='Confirmer le mot de passe')
    liste.append(un)
    liste.append(deux)
    erreur = Gtk.Label(wrap=True, xalign=0, margin_top=6)
    erreur.add_css_class('caption')
    boite = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
    boite.append(liste)
    boite.append(erreur)
    d.set_extra_child(boite)
    d.set_response_enabled('creer', False)

    def controle(*_):
        message = donnees.valider_secours(un.get_text(), deux.get_text())
        # pas de reproche tant que la confirmation n'est pas commencée
        erreur.set_text(message if (message and deux.get_text()) else '')
        erreur.add_css_class('error')
        d.set_response_enabled('creer', message is None)
    un.connect('changed', controle)
    deux.connect('changed', controle)
    deux.connect('entry-activated', lambda *_: d.response('creer') if donnees.valider_secours(un.get_text(), deux.get_text()) is None else None)
    d.connect('response', lambda _d, r: rappel(un.get_text()) if r == 'creer' else None)
    d.present(parent)


def texte_premiere_connexion(compte):
    """Marche à suivre à l'écran de connexion."""
    return ('1. Déconnectez-vous (fermez la session).\n'
            '2. À l’écran d’accueil, choisissez votre compte.\n'
            '3. Tapez le mot de passe Entra de %s, puis validez sur votre téléphone (Microsoft Authenticator), '
            'comme sur Windows.\n'
            '4. Le poste est inscrit dans Entra à cette première connexion ; choisissez ensuite un code PIN '
            '(Windows Hello) pour les connexions suivantes.') % (compte or 'votre adresse pro')


def premiere_connexion(parent, compte, rappel_fait=None):
    """Explique la première connexion par Entra : plus tard, déconnexion, ou « c'est fait »."""
    d = _alerte('Première connexion par Entra', texte_premiere_connexion(compte),
                [('plus-tard', 'Plus tard', None), ('fait', 'J’ai fait ma première connexion', None),
                 ('fermer', 'Se déconnecter', Adw.ResponseAppearance.SUGGESTED)], 'fermer', 'plus-tard')

    def reponse(_d, r):
        if r == 'fermer':
            lanceur.fermer_session()
        elif r == 'fait' and rappel_fait:
            rappel_fait()
    d.connect('response', reponse)
    d.present(parent)


def confirmer(parent, titre, corps, libelle, rappel, destructif=True):
    """Confirmation simple d'une action (désactiver…)."""
    apparence = Adw.ResponseAppearance.DESTRUCTIVE if destructif else Adw.ResponseAppearance.SUGGESTED
    d = _alerte(titre, corps, [('annuler', 'Annuler', None), ('ok', libelle, apparence)], 'annuler')
    d.connect('response', lambda _d, r: rappel() if r == 'ok' else None)
    d.present(parent)


def ouvrir_url(parent, url):
    if hasattr(Gtk, 'UriLauncher'):
        Gtk.UriLauncher.new(url).launch(parent, None, lambda *_: None)
    else:  # pragma: no cover : GTK < 4.10
        Gtk.show_uri(parent, url, 0)


def verification(parent, controles, rappel_noter):
    """Liste des contrôles ; si tous sont bons, propose d'enregistrer le passage réussi (rappel_noter)."""
    tous_ok = bool(controles) and all(ok for ok, _ in controles)
    d = Adw.Dialog(title='Vérification', content_width=520, content_height=560)
    vue = Adw.ToolbarView()
    vue.add_top_bar(Adw.HeaderBar())
    page = Adw.PreferencesPage()
    groupe = Adw.PreferencesGroup(description='Tous les contrôles sont bons.' if tous_ok else
                                  'Certains contrôles ne passent pas encore.')
    for ok, texte in controles:
        ligne = Adw.ActionRow(title=GLib.markup_escape_text(texte), title_lines=0)
        icone = Gtk.Image.new_from_icon_name('emblem-ok-symbolic' if ok else 'dialog-warning-symbolic')
        icone.add_css_class('success' if ok else 'warning')
        ligne.add_prefix(icone)
        groupe.add(ligne)
    page.add(groupe)
    vue.set_content(page)
    if tous_ok and rappel_noter:
        bouton = Gtk.Button(label='Enregistrer le résultat', halign=Gtk.Align.CENTER, margin_top=12, margin_bottom=12)
        bouton.add_css_class('suggested-action')
        bouton.add_css_class('pill')
        bouton.connect('clicked', lambda *_: (d.close(), rappel_noter()))
        vue.add_bottom_bar(bouton)
    d.set_child(vue)
    d.present(parent)
