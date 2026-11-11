"""Dialogues de l'assistant : secours, première connexion, reprise, guide du portail, vérification."""
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


def premiere_connexion(parent, compte, rappel_vu=None):
    """Explique la première connexion par Entra, avec un bouton pour fermer la session."""
    corps = ('1. Fermez la session, puis, à l’écran de connexion, choisissez « Non listé ? ».\n'
             '2. Saisissez votre compte Entra%s.\n'
             '3. Choisissez « Microsoft Entra ID ».\n'
             '4. Scannez le QR code ou saisissez le code sur votre téléphone, et validez la connexion.\n'
             '5. Choisissez un mot de passe local : il servira à déverrouiller la session.\n\n'
             'Ensuite, revenez ici : l’étape sera cochée.') % (' (%s)' % compte if compte else '')
    d = _alerte('Première connexion par Entra', corps,
                [('plus-tard', 'Plus tard', None), ('fermer', 'Fermer la session', Adw.ResponseAppearance.SUGGESTED)],
                'plus-tard', 'plus-tard')

    def reponse(_d, r):
        if r == 'fermer':
            lanceur.fermer_session()
    d.connect('response', reponse)
    d.present(parent)


def reprise(parent, compte_local, compte, peut_maintenant, rappel):
    """Dialogue destructif de la reprise ; rappel('au-demarrage' | 'maintenant')."""
    corps = ('Le compte local « %s » sera supprimé de la liste des comptes, et le compte Entra « %s » le remplacera avec '
             'le même identifiant, le même dossier personnel, les mêmes groupes et la même crontab. Une sauvegarde est '
             'faite avant, et tout est annulé automatiquement si une erreur survient.\n\n'
             'Recommandé : « Au prochain démarrage ». La reprise se fait avant l’écran de connexion, quand aucun '
             'programme ne tourne.') % (compte_local or '?', compte or '?')
    reponses = [('annuler', 'Annuler', None)]
    if peut_maintenant:
        reponses.append(('maintenant', 'Maintenant', Adw.ResponseAppearance.DESTRUCTIVE))
    reponses.append(('demarrage', 'Au prochain démarrage', Adw.ResponseAppearance.SUGGESTED))
    d = _alerte('Reprendre le compte local ?', corps, reponses, 'demarrage')
    d.connect('response', lambda _d, r: rappel('au-demarrage' if r == 'demarrage' else 'maintenant') if r in ('demarrage', 'maintenant') else None)
    d.present(parent)


def proposer_redemarrage(parent, rappel_erreur):
    """Après une reprise programmée : propose de redémarrer tout de suite."""
    d = _alerte('Reprise programmée', 'La reprise du compte aura lieu au prochain démarrage du poste. '
                'Enregistrez votre travail, puis redémarrez quand vous voulez.',
                [('plus-tard', 'Plus tard', None), ('redemarrer', 'Redémarrer maintenant', Adw.ResponseAppearance.SUGGESTED)],
                'plus-tard', 'plus-tard')
    d.connect('response', lambda _d, r: lanceur.redemarrer(rappel_erreur) if r == 'redemarrer' else None)
    d.present(parent)


def confirmer(parent, titre, corps, libelle, rappel, destructif=True):
    """Confirmation simple d'une action (désactiver, annuler la reprise…)."""
    apparence = Adw.ResponseAppearance.DESTRUCTIVE if destructif else Adw.ResponseAppearance.SUGGESTED
    d = _alerte(titre, corps, [('annuler', 'Annuler', None), ('ok', libelle, apparence)], 'annuler')
    d.connect('response', lambda _d, r: rappel() if r == 'ok' else None)
    d.present(parent)


def _ouvrir_url(parent, url):
    if hasattr(Gtk, 'UriLauncher'):
        Gtk.UriLauncher.new(url).launch(parent, None, lambda *_: None)
    else:  # pragma: no cover : GTK < 4.10
        Gtk.show_uri(parent, url, 0)


def guide_portail(parent, coeur):
    """Les étapes de la création de l'application dans le portail Entra, avec un bouton qui ouvre le portail."""
    d = Adw.Dialog(title='Créer l’application dans Entra', content_width=560, content_height=680)
    vue = Adw.ToolbarView()
    vue.add_top_bar(Adw.HeaderBar())
    page = Adw.PreferencesPage()
    intro = Adw.PreferencesGroup(description='Faites-le une fois, avec un compte administrateur de l’annuaire. À la fin, '
                                 'copiez l’ID du locataire et l’ID client dans l’assistant.')
    page.add(intro)
    groupe = Adw.PreferencesGroup(title='Étapes')
    for n, element in enumerate(coeur.guide.PORTAIL, 1):
        titre, detail = (element if isinstance(element, (tuple, list)) else (element.get('titre', ''), element.get('detail', '')))
        ligne = Adw.ActionRow(title=GLib.markup_escape_text(titre), subtitle=GLib.markup_escape_text(detail),
                              subtitle_selectable=True, subtitle_lines=0, title_lines=0)
        numero = Gtk.Label(label=str(n), valign=Gtk.Align.START, margin_top=14)
        numero.add_css_class('dim-label')
        numero.add_css_class('numeric')
        ligne.add_prefix(numero)
        groupe.add(ligne)
    page.add(groupe)
    vue.set_content(page)
    bouton = Gtk.Button(label='Ouvrir le portail Entra', halign=Gtk.Align.CENTER, margin_top=12, margin_bottom=12)
    bouton.add_css_class('suggested-action')
    bouton.add_css_class('pill')
    bouton.connect('clicked', lambda *_: _ouvrir_url(parent, coeur.guide.URL_PORTAIL))
    vue.add_bottom_bar(bouton)
    d.set_child(vue)
    d.present(parent)


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
