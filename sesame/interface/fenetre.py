"""Fenêtre principale de l'assistant : compte Entra, étapes, journal."""
import getpass
import types

import gi

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Adw, Gio, GLib, Gtk, Pango

from . import dialogues, donnees, lanceur

CHAMPS = (('locataire', 'ID du locataire (annuaire)'), ('client', 'ID client (application)'),
          ('compte', 'Compte Entra (UPN)'), ('compte_local', 'Compte local à reprendre'))
CONNEXIONS = (('mot-de-passe', 'Mot de passe Entra'), ('code', 'Code sur le téléphone'))


class Rangee:
    """Une étape : ligne Adw.ActionRow, icône de statut, bouton et indicateur d'activité."""

    def __init__(self, etape_id, titre, explication, sur_clic):
        self.id = etape_id
        self.statut = 'inconnu'
        self.row = Adw.ActionRow(title=GLib.markup_escape_text(titre), subtitle=GLib.markup_escape_text(explication),
                                 subtitle_lines=0, title_lines=0)
        self.row.set_tooltip_text(explication)
        self.icone = Gtk.Image.new_from_icon_name('dialog-question-symbolic')
        self.row.add_prefix(self.icone)
        self.activite = Gtk.Spinner(visible=False, valign=Gtk.Align.CENTER)
        self.bouton = Gtk.Button(valign=Gtk.Align.CENTER, label='Lancer')
        self.bouton.connect('clicked', lambda *_: sur_clic(etape_id))
        self.row.add_suffix(self.activite)
        self.row.add_suffix(self.bouton)
        self.explication = explication
        self.detail = ''

    def mettre_a_jour(self, etat):
        self.statut = etat.get('statut', 'inconnu')
        nom, classe, _ = donnees.icone_statut(self.statut)
        self.icone.set_from_icon_name(nom)
        for c in ('success', 'accent', 'dim-label', 'warning'):
            self.icone.remove_css_class(c)
        self.icone.add_css_class(classe)
        self.row.set_subtitle(GLib.markup_escape_text(etat.get('detail') or self.explication))
        libelle = donnees.libelle_bouton(self.statut)
        self.bouton.set_visible(libelle is not None)
        if libelle:
            self.bouton.set_label(libelle)
            self.bouton.remove_css_class('suggested-action')
            if self.statut in ('a_faire', 'inconnu'):
                self.bouton.add_css_class('suggested-action')
        self.detail = etat.get('detail') or ''

    def occupee(self, oui):
        self.activite.set_visible(oui)
        self.activite.set_spinning(oui)
        self.bouton.set_visible(not oui and donnees.libelle_bouton(self.statut) is not None)


class Fenetre(Adw.ApplicationWindow):
    def __init__(self, application, coeur=None):
        super().__init__(application=application, title='Sésame', default_width=720, default_height=820)
        self.set_size_request(360, 400)
        self.coeur = coeur or donnees.charger_coeur()
        self.systeme = self.coeur.systeme.Systeme()
        self.lanceur = lanceur.Lanceur()
        self.etats = []
        self.config = None
        self.reprise_resultat = None
        self.reprise_masquee = False
        self.rangees = {}
        self.champs = {}
        self.champs_remplis = False
        self.action_en_cours = None
        self._lecture = False
        self._relire = False
        self._construire()
        self.actualiser()

    # --- construction --------------------------------------------------------------------------------------------

    def _construire(self):
        self.toasts = Adw.ToastOverlay()
        vue = Adw.ToolbarView()
        entete = Adw.HeaderBar()
        entete.set_title_widget(Adw.WindowTitle(title='Sésame', subtitle='Connexion Microsoft Entra ID'))
        self.bouton_actualiser = Gtk.Button(icon_name='view-refresh-symbolic', tooltip_text='Actualiser')
        self.bouton_actualiser.connect('clicked', lambda *_: self.actualiser())
        entete.pack_start(self.bouton_actualiser)
        menu = Gio.Menu()
        menu.append('Guide du portail Entra', 'win.guide')
        menu.append('Désactiver la connexion Entra', 'win.desactiver')
        menu.append('Annuler la reprise', 'win.annuler-reprise')
        a_propos = Gio.Menu()
        a_propos.append('À propos de Sésame', 'app.a-propos')
        menu.append_section(None, a_propos)
        entete.pack_end(Gtk.MenuButton(icon_name='open-menu-symbolic', menu_model=menu, tooltip_text='Menu principal',
                                       primary=True))
        vue.add_top_bar(entete)
        self.bandeau = Adw.Banner(title='Lecture de l’état…', revealed=True)
        self.bandeau.connect('button-clicked', self._masquer_reprise)
        vue.add_top_bar(self.bandeau)

        for nom, rappel in (('guide', lambda *_: self.ouvrir_guide()), ('desactiver', lambda *_: self.desactiver()),
                            ('annuler-reprise', lambda *_: self.annuler_reprise())):
            a = Gio.SimpleAction.new(nom, None)
            a.connect('activate', rappel)
            self.add_action(a)

        page = Adw.PreferencesPage()
        compte = Adw.PreferencesGroup(title='Compte Microsoft Entra',
                                      description='Ces valeurs viennent du portail Entra. Ce ne sont pas des secrets.')
        for cle, titre in CHAMPS:
            champ = Adw.EntryRow(title=titre)
            champ.connect('changed', self._champ_modifie, cle)
            self.champs[cle] = champ
            compte.add(champ)
        self.connexion = Adw.ComboRow(title='Connexion', subtitle='À l’écran d’accueil ; le mot de passe Entra, c’est comme sur Windows',
                                      model=Gtk.StringList.new([titre for _, titre in CONNEXIONS]))
        compte.add(self.connexion)
        guide = Adw.ActionRow(title='Créer l’application dans le portail Entra', activatable=True,
                              subtitle='Pas à pas, avec un lien vers le portail')
        guide.add_prefix(Gtk.Image.new_from_icon_name('help-about-symbolic'))
        guide.add_suffix(Gtk.Image.new_from_icon_name('go-next-symbolic'))
        guide.connect('activated', lambda *_: self.ouvrir_guide())
        compte.add(guide)
        page.add(compte)

        groupe = Adw.PreferencesGroup(title='Étapes', description='Chaque étape détecte si elle est déjà faite : on peut '
                                      'les relancer sans risque.')
        for etape in self.coeur.etapes.ETAPES:
            r = Rangee(etape.id, etape.titre, getattr(etape, 'explication', '') or '', self.lancer_etape)
            self.rangees[etape.id] = r
            groupe.add(r.row)
        page.add(groupe)

        journal = Adw.PreferencesGroup(title='Journal')
        self.expandeur = Adw.ExpanderRow(title='Journal des actions', subtitle='Ce que fait l’assistant root')
        self.tampon = Gtk.TextBuffer()
        self.tampon.create_tag('etape', weight=Pango.Weight.BOLD)
        self.tampon.create_tag('commande', foreground='#62a0ea')
        self.tampon.create_tag('avertissement', foreground='#e5a50a')
        self.tampon.create_tag('fin-ok', foreground='#33b065', weight=Pango.Weight.BOLD)
        self.tampon.create_tag('fin-erreur', foreground='#e5493a', weight=Pango.Weight.BOLD)
        self.tampon.create_tag('sortie')
        self.texte = Gtk.TextView(buffer=self.tampon, editable=False, cursor_visible=False, monospace=True,
                                  wrap_mode=Gtk.WrapMode.WORD_CHAR, top_margin=8, bottom_margin=8, left_margin=12, right_margin=12)
        defilement = Gtk.ScrolledWindow(child=self.texte, min_content_height=220, hscrollbar_policy=Gtk.PolicyType.NEVER)
        self.defilement = defilement
        self.expandeur.add_row(Gtk.ListBoxRow(child=defilement, activatable=False, selectable=False))
        journal.add(self.expandeur)
        page.add(journal)

        vue.set_content(page)
        self.toasts.set_child(vue)
        self.set_content(self.toasts)

    # --- état ----------------------------------------------------------------------------------------------------

    def toast(self, texte):
        self.toasts.add_toast(Adw.Toast(title=texte, timeout=4))

    def actualiser(self):
        """Relit l'état dans un fil (les détections lancent des commandes) puis met l'écran à jour."""
        if self._lecture:
            self._relire = True
            return
        self._lecture = True
        self.bouton_actualiser.set_sensitive(False)

        def lire():
            coeur, systeme = self.coeur, self.systeme
            etats = coeur.etapes.lire_etat(systeme)
            config = coeur.config.charger(systeme) or coeur.config.defauts(systeme)
            reprise = coeur.etapes.derniere_reprise(systeme)
            return etats, config, reprise

        lanceur.en_arriere(lire, self._etat_lu)

    def _etat_lu(self, resultat, erreur):
        self._lecture = False
        self.bouton_actualiser.set_sensitive(True)
        if erreur is not None:
            self.bandeau.set_title('Impossible de lire l’état : %s' % erreur)
            self.bandeau.set_button_label(None)
        else:
            self.etats, self.config, self.reprise_resultat = resultat
            if not self.champs_remplis:
                self._remplir_champs()
            self._afficher()
        if self._relire:
            self._relire = False
            self.actualiser()
        return False

    def _remplir_champs(self):
        self.champs_remplis = True
        c = self.config
        for cle, valeur in (('locataire', c.locataire), ('client', c.client), ('compte', c.compte),
                            ('compte_local', c.compte_local)):
            self.champs[cle].set_text(valeur or '')
        modes = [mode for mode, _ in CONNEXIONS]
        mode = getattr(c, 'connexion', modes[0])
        self.connexion.set_selected(modes.index(mode) if mode in modes else 0)

    def valeur_connexion(self):
        """Mode de connexion choisi : 'mot-de-passe' ou 'code'."""
        i = self.connexion.get_selected()
        return CONNEXIONS[i][0] if 0 <= i < len(CONNEXIONS) else CONNEXIONS[0][0]

    def _afficher(self):
        par_id = {e['id']: e for e in self.etats}
        for identifiant, rangee in self.rangees.items():
            rangee.mettre_a_jour(par_id.get(identifiant, {'statut': 'inconnu'}))
        self._maj_bandeau()
        self._maj_boutons()

    def _maj_bandeau(self):
        r = self.reprise_resultat
        if r and not self.reprise_masquee and 'demarrage' in str(r.get('mode', '')):
            self.bandeau.set_title(('Reprise du compte réussie. ' if r.get('ok') else 'La reprise du compte a échoué. ')
                                   + str(r.get('message', '')))
            self.bandeau.set_button_label('Masquer')
            return
        suivante = self.coeur.etapes.etape_suivante(self.etats)
        if suivante is None:
            texte = 'Tout est en place'
        else:
            titre = next((e['titre'] for e in self.etats if e['id'] == suivante), suivante)
            texte = 'Étape suivante : ' + titre
        self.bandeau.set_title(texte)
        self.bandeau.set_button_label(None)

    def _masquer_reprise(self, *_):
        self.reprise_masquee = True
        self._maj_bandeau()

    def _maj_boutons(self):
        occupe = self.lanceur.occupe
        for identifiant, r in self.rangees.items():
            bloquee = r.statut == 'bloquee'
            r.bouton.set_sensitive(not occupe and not bloquee)
            if bloquee:
                r.bouton.set_tooltip_text('Impossible pour l’instant : ' + (getattr(r, 'detail', '') or 'une étape précédente manque'))
            elif occupe:
                r.bouton.set_tooltip_text('Une action est déjà en cours')
            else:
                r.bouton.set_tooltip_text(None)
            r.occupee(occupe and identifiant == self.action_en_cours)

    # --- champs --------------------------------------------------------------------------------------------------

    def _champ_modifie(self, champ, cle):
        etat, _, message = donnees.valider_champ(self.coeur, cle, champ.get_text())
        if etat == 'erreur':
            champ.add_css_class('error')
            champ.set_tooltip_text(message)
        else:
            champ.remove_css_class('error')
            champ.set_tooltip_text(None)

    def valeurs_champs(self):
        """(valeurs normalisées, liste des champs manquants ou invalides)."""
        valeurs, mauvais = {}, []
        for cle, titre in CHAMPS:
            etat, norme, _ = donnees.valider_champ(self.coeur, cle, self.champs[cle].get_text())
            valeurs[cle] = norme
            if etat != 'ok':
                mauvais.append(titre)
        return valeurs, mauvais

    def _compte_local(self):
        return self.champs['compte_local'].get_text().strip() or (self.config.compte_local if self.config else '')

    # --- actions -------------------------------------------------------------------------------------------------

    def lancer_etape(self, identifiant):
        if self.lanceur.occupe:
            self.toast('Une action est déjà en cours')
            return
        etape = next((e for e in self.etats if e['id'] == identifiant), {'id': identifiant})
        if identifiant == 'secours':
            nom = (self.config.secours if self.config and self.config.secours else 'secours')
            dialogues.secours(self, nom, lambda mdp: self.executer(etape, ['--nom', nom], mdp + '\n'))
        elif identifiant == 'configurer':
            self._configurer(etape)
        elif identifiant == 'premiere_connexion':
            dialogues.premiere_connexion(self, self.champs['compte'].get_text().strip(),
                                         connexion=self.valeur_connexion())
        elif identifiant == 'reprise':
            self._reprendre(etape)
        elif identifiant == 'verification':
            self._verifier()
        else:
            self.executer(etape, [])

    def _configurer(self, etape):
        valeurs, mauvais = self.valeurs_champs()
        if mauvais:
            self.toast('Champ à corriger : ' + mauvais[0])
            return
        groupes = ','.join(self.config.groupes) if self.config and self.config.groupes else ''
        arguments = ['--locataire', valeurs['locataire'], '--client', valeurs['client'], '--compte', valeurs['compte'],
                     '--compte-local', valeurs['compte_local'], '--connexion', self.valeur_connexion()]
        if self.config and self.config.secours:
            arguments += ['--secours', self.config.secours]
        if groupes:
            arguments += ['--groupes', groupes]
        self.executer(etape, arguments)

    def _reprendre(self, etape):
        valeurs, mauvais = self.valeurs_champs()
        local = self._compte_local()
        peut_maintenant = bool(local) and getpass.getuser() != local
        dialogues.reprise(self, local, valeurs.get('compte') or self.champs['compte'].get_text().strip(), peut_maintenant,
                          lambda mode: self.executer(etape, ['--' + mode]))

    def _verifier(self):
        def travail():
            config = self.coeur.config.charger(self.systeme) or self.coeur.config.defauts(self.systeme)
            return self.coeur.verification.controler(self.systeme, config)

        def fini(controles, erreur):
            if erreur is not None:
                self.toast('Vérification impossible : %s' % erreur)
                return
            noter = lambda: self.executer({'id': 'noter-verification', 'action': 'noter-verification'}, [])
            dialogues.verification(self, controles, noter)
        lanceur.en_arriere(travail, fini)

    def desactiver(self):
        dialogues.confirmer(self, 'Désactiver la connexion Entra ?',
                            'La connexion par Entra est coupée, sans rien désinstaller. L’étape « Configurer la connexion '
                            'Entra » la rétablit.', 'Désactiver',
                            lambda: self.executer({'id': 'desactiver', 'action': 'desactiver'}, []))

    def annuler_reprise(self):
        dialogues.confirmer(self, 'Annuler la reprise ?',
                            'Le compte local est rétabli à partir de la sauvegarde et le compte Entra retrouve son propre '
                            'identifiant. À utiliser si la reprise a mal tourné.', 'Annuler la reprise',
                            lambda: self.executer({'id': 'annuler-reprise', 'action': 'annuler-reprise'}, []))

    def ouvrir_guide(self):
        dialogues.guide_portail(self, self.coeur)

    def executer(self, etape, arguments, stdin=None):
        """Lance une action de sesame-racine par pkexec. Une seule à la fois."""
        action = donnees.action_de_etape(etape)
        argv = donnees.commande_racine(action, arguments)
        self.action_en_cours = etape['id']
        self.expandeur.set_expanded(True)
        self._ecrire('etape', '\n=== %s ===\n' % (etape.get('titre') or action))
        ok = self.lanceur.lancer(argv, stdin, self._evenement, lambda code, fin: self._action_finie(action, arguments, code, fin))
        if not ok:
            self.toast('Une action est déjà en cours')
            return
        self._maj_boutons()

    def _ecrire(self, balise, texte):
        fin = self.tampon.get_end_iter()
        self.tampon.insert_with_tags_by_name(fin, texte, balise)
        adj = self.defilement.get_vadjustment()
        GLib.idle_add(lambda: adj.set_value(adj.get_upper() - adj.get_page_size()) and False)

    def _evenement(self, evenement):
        balise, texte = donnees.mise_en_forme(evenement)
        self._ecrire(balise, texte)

    def _action_finie(self, action, arguments, code, fin):
        self.action_en_cours = None
        if code in lanceur.CODES_ANNULE:
            self.toast('Authentification annulée')
            self._ecrire('avertissement', '! Authentification annulée\n')
        elif fin is not None:
            self.toast(fin['message'] or ('Terminé' if fin['ok'] else 'L’action a échoué'))
            if fin['ok'] and action == 'reprise' and '--au-demarrage' in arguments:
                dialogues.proposer_redemarrage(self, lambda m: self.toast('Redémarrage impossible : ' + m) if m else None)
        elif code == 0:
            self.toast('Terminé')
        else:
            self.toast('L’action a échoué (code %s)' % code)
            self._ecrire('fin-erreur', '✘ L’action a échoué (code %s)\n' % code)
        self._maj_boutons()
        self.actualiser()
