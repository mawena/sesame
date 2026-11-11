"""Fenêtre principale de l'assistant : rejoindre Microsoft Entra ID (adresse pro, nom de la machine), compilation et installation d'Himmelblau."""
import getpass

import gi

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Adw, Gio, GLib, Gtk, Pango

from . import dialogues, donnees, lanceur

CODE_ANNULE = 'Authentification annulée : rien n’a été modifié. Vous pouvez réessayer.'


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


class LigneProgression:
    """Une ligne de la progression : spinner (en cours), coche (fait) ou croix (erreur)."""

    def __init__(self, texte):
        self.etat = 'en_cours'
        self.row = Adw.ActionRow(title=GLib.markup_escape_text(texte), title_lines=0)
        self.spinner = Gtk.Spinner(spinning=True, valign=Gtk.Align.CENTER)
        self.icone = Gtk.Image(visible=False)
        self.row.add_prefix(self.spinner)
        self.row.add_prefix(self.icone)

    def definir(self, etat):
        self.etat = etat
        self.spinner.set_spinning(etat == 'en_cours')
        self.spinner.set_visible(etat == 'en_cours')
        self.icone.set_visible(etat != 'en_cours')
        for c in ('success', 'error'):
            self.icone.remove_css_class(c)
        if etat == 'fait':
            self.icone.set_from_icon_name('emblem-ok-symbolic')
            self.icone.add_css_class('success')
        elif etat == 'erreur':
            self.icone.set_from_icon_name('dialog-error-symbolic')
            self.icone.add_css_class('error')


def _bouton_pill(libelle, suggere=True):
    b = Gtk.Button(label=libelle, halign=Gtk.Align.CENTER)
    b.add_css_class('pill')
    if suggere:
        b.add_css_class('suggested-action')
    return b


class Fenetre(Adw.ApplicationWindow):
    def __init__(self, application, coeur=None):
        super().__init__(application=application, title='Sésame', default_width=640, default_height=760)
        self.set_size_request(360, 400)
        self.coeur = coeur or donnees.charger_coeur()
        self.systeme = self.coeur.systeme.Systeme()
        self.lanceur = lanceur.Lanceur()
        self.etats = []
        self.config = None
        self.rangees = {}
        self.champs = {}
        self.lignes = []
        self.champs_remplis = False
        self.action_en_cours = None
        self.rejoindre_en_cours = False
        self.page_figee = False      # progression, page finale ou erreur affichée : l'état relu ne change plus de page
        self.dernier_rejoindre = None  # (compte, nom) du dernier lancement, pour la page finale
        self.arguments_rejoindre = []
        self.compilation_requise = False
        self.suite_compilation = None
        self.en_compilation = False
        self.mise_a_jour_proposee = False
        self._lecture = False
        self._relire = False
        self._construire()
        self.actualiser()

    # --- construction --------------------------------------------------------------------------------------------

    def _construire(self):
        self.toasts = Adw.ToastOverlay()
        self.navigation = Adw.NavigationView()
        vue = Adw.ToolbarView()
        entete = Adw.HeaderBar()
        self.bouton_actualiser = Gtk.Button(icon_name='view-refresh-symbolic', tooltip_text='Actualiser')
        self.bouton_actualiser.connect('clicked', lambda *_: self.actualiser())
        entete.pack_start(self.bouton_actualiser)
        menu = Gio.Menu()
        menu.append('Détails', 'win.details')
        menu.append('Vérifier', 'win.verifier')
        menu.append('Mettre à jour Himmelblau', 'win.mettre-a-jour')
        menu.append('Désactiver la connexion Entra', 'win.desactiver')
        a_propos = Gio.Menu()
        a_propos.append('À propos de Sésame', 'app.a-propos')
        menu.append_section(None, a_propos)
        entete.pack_end(Gtk.MenuButton(icon_name='open-menu-symbolic', menu_model=menu, tooltip_text='Menu principal',
                                       primary=True))
        vue.add_top_bar(entete)
        self.bandeau = Adw.Banner(title='Une nouvelle version stable de Himmelblau est disponible', revealed=False,
                                  button_label='Mettre à jour')
        self.bandeau.connect('button-clicked', lambda *_: self.mettre_a_jour())
        vue.add_top_bar(self.bandeau)
        for nom, rappel in (('details', lambda *_: self.ouvrir_details()), ('verifier', lambda *_: self.verifier()),
                            ('mettre-a-jour', lambda *_: self.mettre_a_jour()),
                            ('desactiver', lambda *_: self.desactiver())):
            a = Gio.SimpleAction.new(nom, None)
            a.connect('activate', rappel)
            self.add_action(a)

        self.pages = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, vhomogeneous=False)
        self.pages.add_named(self._page_formulaire(), 'formulaire')
        self.pages.add_named(self._page_progression(), 'progression')
        self.pages.add_named(self._page_finale(), 'final')
        self.pages.add_named(self._page_erreur(), 'erreur')
        self.pages.add_named(self._page_relie(), 'relie')
        self.pages.set_visible_child_name('formulaire')
        vue.set_content(self.pages)
        racine = Adw.NavigationPage(title='Sésame', child=vue, tag='principal')
        self.navigation.add(racine)
        self.navigation.add(self._page_details())
        self.toasts.set_child(self.navigation)
        self.set_content(self.toasts)

    @staticmethod
    def _defilante(contenu):
        clamp = Adw.Clamp(maximum_size=520, tightening_threshold=420, margin_start=16, margin_end=16, margin_top=24,
                          margin_bottom=24, child=contenu)
        return Gtk.ScrolledWindow(child=clamp, hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)

    def _page_formulaire(self):
        boite = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        icone = Gtk.Image.new_from_icon_name(donnees.APPLICATION_ID)
        icone.set_pixel_size(72)
        titre = Gtk.Label(label='Rejoindre Microsoft Entra ID', wrap=True, justify=Gtk.Justification.CENTER)
        titre.add_css_class('title-1')
        intro = Gtk.Label(label='Comme sur un PC Windows : vous gardez votre compte, votre dossier personnel et vos '
                          'réglages, et vous vous connectez avec votre adresse pro.', wrap=True,
                          justify=Gtk.Justification.CENTER)
        intro.add_css_class('dim-label')
        boite.append(icone)
        boite.append(titre)
        boite.append(intro)
        groupe = Adw.PreferencesGroup()
        self.champs['compte'] = Adw.EntryRow(title='Adresse pro')
        self.champs['nom_machine'] = Adw.EntryRow(title='Nom de la machine')
        for cle in ('compte', 'nom_machine'):
            self.champs[cle].connect('changed', self._champ_modifie, cle)
            groupe.add(self.champs[cle])
        self.champs['nom_machine'].set_text(donnees.nom_machine_actuel())
        boite.append(groupe)
        self.bouton_rejoindre = _bouton_pill('Rejoindre')
        self.bouton_rejoindre.set_sensitive(False)
        self.bouton_rejoindre.connect('clicked', lambda *_: self.rejoindre())
        boite.append(self.bouton_rejoindre)
        note = Gtk.Label(label='Une fenêtre vous demandera votre mot de passe Ubuntu actuel. Himmelblau est ensuite '
                         'compilé sur ce poste (environ 30 à 60 minutes), puis installé.', wrap=True,
                         justify=Gtk.Justification.CENTER)
        note.add_css_class('caption')
        note.add_css_class('dim-label')
        boite.append(note)
        return self._defilante(boite)

    def _page_progression(self):
        boite = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        self.titre_progression = Gtk.Label(label='Configuration en cours…', wrap=True)
        self.titre_progression.add_css_class('title-2')
        boite.append(self.titre_progression)
        self.liste = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.liste.add_css_class('boxed-list')
        boite.append(self.liste)
        self.note_compilation = Gtk.Label(wrap=True, xalign=0, visible=False,
                                          label='Compilation de Himmelblau : environ 30 à 60 minutes. Vous pouvez fermer '
                                                'Sésame, la compilation continue dans la file Gagarine.')
        self.note_compilation.add_css_class('dim-label')
        boite.append(self.note_compilation)

        journal = Adw.PreferencesGroup()
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
        self.defilement = Gtk.ScrolledWindow(child=self.texte, min_content_height=220, hscrollbar_policy=Gtk.PolicyType.NEVER)
        self.expandeur.add_row(Gtk.ListBoxRow(child=self.defilement, activatable=False, selectable=False))
        journal.add(self.expandeur)
        boite.append(journal)
        return self._defilante(boite)

    def _page_status(self, icone, classe=None):
        page = Adw.StatusPage(icon_name=icone, vexpand=True)
        if classe:
            page.add_css_class(classe)
        return page

    def _page_finale(self):
        self.statut_final = self._page_status('emblem-ok-symbolic', 'success')
        self.statut_final.set_title('Le poste est prêt')
        self.bouton_deconnexion = _bouton_pill('Se déconnecter')
        self.bouton_deconnexion.connect('clicked', lambda *_: lanceur.fermer_session(
            lambda m: self.toast('Déconnexion impossible : ' + m)))
        plus_tard = Gtk.Button(label='Plus tard', halign=Gtk.Align.CENTER)
        plus_tard.add_css_class('flat')
        plus_tard.connect('clicked', lambda *_: self._fin_affichage())
        boite = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        boite.append(self.bouton_deconnexion)
        boite.append(plus_tard)
        self.statut_final.set_child(boite)
        return self.statut_final

    def _page_erreur(self):
        self.statut_erreur = self._page_status('dialog-error-symbolic', 'error')
        self.statut_erreur.set_title('Le poste n’a pas pu être relié')
        self.bouton_reessayer = _bouton_pill('Réessayer')
        self.bouton_reessayer.connect('clicked', lambda *_: self._fin_affichage())
        boite = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        boite.append(self.bouton_reessayer)
        journal = Gtk.Button(label='Voir le journal', halign=Gtk.Align.CENTER)
        journal.add_css_class('flat')
        journal.connect('clicked', lambda *_: self.pages.set_visible_child_name('progression'))
        boite.append(journal)
        self.statut_erreur.set_child(boite)
        return self.statut_erreur

    def _page_relie(self):
        self.statut_relie = self._page_status('emblem-ok-symbolic', 'success')
        self.statut_relie.set_title('Le poste est relié à Microsoft Entra ID')
        self.bouton_premiere = _bouton_pill('J’ai fait ma première connexion')
        self.bouton_premiere.connect('clicked', lambda *_: self.executer('noter-premiere-connexion', []))
        self.bouton_deconnexion_relie = _bouton_pill('Se déconnecter', suggere=False)
        self.bouton_deconnexion_relie.connect('clicked', lambda *_: lanceur.fermer_session(
            lambda m: self.toast('Déconnexion impossible : ' + m)))
        autre = Gtk.Button(label='Rejoindre avec une autre adresse', halign=Gtk.Align.CENTER)
        autre.add_css_class('flat')
        autre.connect('clicked', lambda *_: self.montrer_formulaire())
        boite = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        for b in (self.bouton_premiere, self.bouton_deconnexion_relie, autre):
            boite.append(b)
        self.statut_relie.set_child(boite)
        return self.statut_relie

    def _page_details(self):
        self.groupe_details = Adw.PreferencesGroup(title='Les étapes', description='Chaque étape détecte si elle est '
                                                   'déjà faite : on peut la relancer sans risque.')
        page = Adw.PreferencesPage()
        page.add(self.groupe_details)
        vue = Adw.ToolbarView()
        vue.add_top_bar(Adw.HeaderBar())
        vue.set_content(page)
        return Adw.NavigationPage(title='Détails', child=vue, tag='details')

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
            etats = donnees.lire_etats(coeur, systeme)
            config = coeur.config.charger(systeme) or coeur.config.defauts(systeme)
            return etats, config

        lanceur.en_arriere(lire, self._etat_lu)

    def _etat_lu(self, resultat, erreur):
        self._lecture = False
        self.bouton_actualiser.set_sensitive(True)
        if erreur is not None:
            self.toast('Impossible de lire l’état : %s' % erreur)
        else:
            self.etats, self.config = resultat
            if not self.champs_remplis:
                self._remplir_champs()
            self._afficher()
            self.verifier_mise_a_jour()
        if self._relire:
            self._relire = False
            self.actualiser()
        return False

    def _remplir_champs(self):
        self.champs_remplis = True
        c = self.config
        compte = getattr(c, 'compte', '') or ''
        if compte:
            self.champs['compte'].set_text(compte)
        nom = getattr(c, 'nom_machine', '') or ''
        if nom:
            self.champs['nom_machine'].set_text(nom)

    def _afficher(self):
        self._maj_details()
        self._maj_relie()
        self._maj_bouton_rejoindre()
        if not self.page_figee and not self.lanceur.occupe:
            self.pages.set_visible_child_name('relie' if donnees.deja_relie(self.etats) else 'formulaire')
        self._maj_boutons()

    def _maj_details(self):
        for etat in self.etats:
            r = self.rangees.get(etat['id'])
            if r is None:
                r = Rangee(etat['id'], etat.get('titre') or etat['id'], etat.get('explication') or '', self.lancer_etape)
                self.rangees[etat['id']] = r
                self.groupe_details.add(r.row)
            r.mettre_a_jour(etat)

    def _maj_relie(self):
        compte = (getattr(self.config, 'compte', '') or self.champs['compte'].get_text().strip()
                  or 'votre adresse pro')
        premiere = donnees.statut_etape(self.etats, 'premiere_connexion')
        if premiere == 'fait':
            self.statut_relie.set_description('Le compte de %s est relié à Microsoft Entra ID, et votre première '
                                              'connexion est faite. Connectez-vous comme d’habitude.' % compte)
        else:
            self.statut_relie.set_description(
                'Le compte de %s est relié à Microsoft Entra ID. Pour la première connexion :\n\n%s'
                % (compte, dialogues.texte_premiere_connexion(compte)))
        self.bouton_premiere.set_visible(premiere != 'fait')
        self.bouton_deconnexion_relie.set_visible(premiere != 'fait')

    def _maj_boutons(self):
        occupe = self.lanceur.occupe
        for identifiant, r in self.rangees.items():
            bloquee = r.statut == 'bloquee'
            r.bouton.set_sensitive(not occupe and not bloquee)
            if bloquee:
                r.bouton.set_tooltip_text('Impossible pour l’instant : ' + (r.detail or 'une étape précédente manque'))
            elif occupe:
                r.bouton.set_tooltip_text('Une action est déjà en cours')
            else:
                r.bouton.set_tooltip_text(None)
            r.occupee(occupe and identifiant == self.action_en_cours)
        self.bouton_premiere.set_sensitive(not occupe)
        self._maj_bouton_rejoindre()

    # --- champs --------------------------------------------------------------------------------------------------

    def _champ_modifie(self, champ, cle):
        etat, _, message = donnees.valider_champ(self.coeur, cle, champ.get_text())
        if etat == 'erreur':
            champ.add_css_class('error')
            champ.set_tooltip_text(message)
        else:
            champ.remove_css_class('error')
            champ.set_tooltip_text(None)
        self._maj_bouton_rejoindre()

    def champs_utiles(self):
        return ('compte', 'nom_machine')

    def valeurs_champs(self):
        """(valeurs normalisées, titres des champs manquants ou invalides)."""
        titres = {'compte': 'Adresse pro', 'nom_machine': 'Nom de la machine'}
        valeurs, mauvais = {}, []
        for cle in self.champs_utiles():
            etat, norme, _ = donnees.valider_champ(self.coeur, cle, self.champs[cle].get_text())
            valeurs[cle] = norme
            if etat != 'ok':
                mauvais.append(titres[cle])
        return valeurs, mauvais

    def _maj_bouton_rejoindre(self):
        if not hasattr(self, 'bouton_rejoindre'):  # champs remplis pendant la construction
            return
        _, mauvais = self.valeurs_champs()
        self.bouton_rejoindre.set_sensitive(not mauvais and not self.lanceur.occupe)

    @staticmethod
    def compte_local():
        return getpass.getuser()

    # --- actions -------------------------------------------------------------------------------------------------

    def rejoindre(self):
        if self.lanceur.occupe:
            self.toast('Une action est déjà en cours')
            return
        valeurs, mauvais = self.valeurs_champs()
        if mauvais:
            self.toast('Champ à corriger : ' + mauvais[0])
            return
        arguments = ['--compte', valeurs['compte'], '--nom-machine', valeurs['nom_machine'],
                     '--compte-local', self.compte_local()]
        self.dernier_rejoindre = (valeurs['compte'], valeurs['nom_machine'])
        self.arguments_rejoindre = arguments
        self.rejoindre_en_cours = True
        self.compilation_requise = False
        self.executer('rejoindre', arguments)

    def lancer_etape(self, identifiant):
        """Une étape de la page Détails, lancée seule."""
        if self.lanceur.occupe:
            self.toast('Une action est déjà en cours')
            return
        etape = next((e for e in self.etats if e['id'] == identifiant), {'id': identifiant})
        action = donnees.action_de_etape(etape)
        compte = self.champs['compte'].get_text().strip()
        if identifiant == 'secours':
            nom = (getattr(self.config, 'secours', '') or 'secours')
            dialogues.secours(self, nom, lambda mdp: self.executer(action, ['--nom', nom], mdp + '\n'))
        elif identifiant == 'compiler':
            self.compiler()
        elif identifiant == 'installer':
            self.executer(action, donnees.argv_paquets(self.dossier_compilation()))
        elif identifiant == 'nom_machine':
            etat, norme, _ = donnees.valider_champ(self.coeur, 'nom_machine', self.champs['nom_machine'].get_text())
            if etat != 'ok':
                self.toast('Corrigez d’abord le nom de la machine')
                return
            self.executer(action, ['--nom', norme])
        elif identifiant == 'configurer':
            etat, norme, _ = donnees.valider_champ(self.coeur, 'compte', compte)
            if etat != 'ok':
                self.toast('Corrigez d’abord l’adresse pro')
                return
            self.executer(action, ['--compte', norme, '--compte-local', self.compte_local()])
        elif identifiant == 'premiere_connexion':
            dialogues.premiere_connexion(self, compte, lambda: self.executer(action, []))
        else:
            self.executer(action, [])

    def verifier(self):
        def travail():
            config = self.coeur.config.charger(self.systeme) or self.coeur.config.defauts(self.systeme)
            return self.coeur.verification.controler(self.systeme, config)

        def fini(controles, erreur):
            if erreur is not None:
                self.toast('Vérification impossible : %s' % erreur)
                return
            dialogues.verification(self, controles, None)
        lanceur.en_arriere(travail, fini)

    def desactiver(self):
        dialogues.confirmer(self, 'Désactiver la connexion Entra ?',
                            'La connexion par Entra est coupée et vous vous connectez avec le compte local seul, sans '
                            'rien désinstaller. « Rejoindre » la rétablit.', 'Désactiver',
                            lambda: self.executer('desactiver', []))

    def ouvrir_details(self):
        self.navigation.push_by_tag('details')

    def montrer_formulaire(self):
        self.page_figee = False
        self.pages.set_visible_child_name('formulaire')

    def _fin_affichage(self):
        """Quitte la page finale ou l'erreur : retour au formulaire (ou à « relié » si c'est fait)."""
        self.page_figee = False
        self.rejoindre_en_cours = False
        self._afficher()
        self.actualiser()

    def executer(self, action, arguments, stdin=None, garder=False):
        """Lance une action de sesame-racine par pkexec (action : nom de la sous-commande). Une seule à la fois."""
        if isinstance(action, dict):  # ancien appel avec le dict d'une étape
            action = donnees.action_de_etape(action)
        argv = donnees.commande_racine(action, arguments)
        if self.lanceur.occupe:
            self.toast('Une action est déjà en cours')
            return
        self.action_en_cours = action
        self.page_figee = True
        self._demarrer_progression(action, garder)
        ok = self.lanceur.lancer(argv, stdin, self._evenement, lambda code, fin: self._action_finie(action, arguments, code, fin))
        if not ok:
            self.toast('Une action est déjà en cours')
            return
        self._maj_boutons()

    # --- progression ---------------------------------------------------------------------------------------------

    TITRES_ACTIONS = {'rejoindre': 'Le poste rejoint Microsoft Entra ID…', 'desactiver': 'Désactivation de la connexion Entra…'}

    def _demarrer_progression(self, action, garder=False):
        if not garder:
            while (ligne := self.liste.get_first_child()) is not None:
                self.liste.remove(ligne)
            self.lignes = []
            self.tampon.set_text('')
        self.note_compilation.set_visible(False)
        self.titre_progression.set_text(self.TITRES_ACTIONS.get(action, 'Action en cours : %s…' % action))
        if not garder:
            self.expandeur.set_expanded(False)
        if self.navigation.get_visible_page().get_tag() != 'principal':
            self.navigation.pop_to_tag('principal')
        self.pages.set_visible_child_name('progression')

    def _nouvelle_ligne(self, texte):
        if self.lignes and self.lignes[-1].etat == 'en_cours':
            self.lignes[-1].definir('fait')
        ligne = LigneProgression(texte)
        self.lignes.append(ligne)
        self.liste.append(ligne.row)

    def _terminer_lignes(self, ok):
        if self.lignes and self.lignes[-1].etat == 'en_cours':
            self.lignes[-1].definir('fait' if ok else 'erreur')

    def _ecrire(self, balise, texte):
        fin = self.tampon.get_end_iter()
        self.tampon.insert_with_tags_by_name(fin, texte, balise)
        adj = self.defilement.get_vadjustment()
        GLib.idle_add(lambda: adj.set_value(adj.get_upper() - adj.get_page_size()) and False)

    def _evenement(self, evenement):
        balise, texte = donnees.mise_en_forme(evenement)
        self._ecrire(balise, texte)
        if evenement['type'] == 'compilation_requise':
            self.compilation_requise = True
        elif evenement['type'] == 'etape' and self.en_compilation:
            if self.lignes:
                self.lignes[-1].row.set_subtitle(GLib.markup_escape_text(evenement['texte']))
        elif evenement['type'] == 'etape':
            self._nouvelle_ligne(evenement['texte'])
        elif evenement['type'] == 'fin':
            self._terminer_lignes(evenement['ok'])

    def _action_finie(self, action, arguments, code, fin):
        self.action_en_cours = None
        annule = code in lanceur.CODES_ANNULE
        reussi = (fin['ok'] if fin is not None else code == 0) and not annule
        self._terminer_lignes(reussi)
        if annule:
            self._ecrire('avertissement', '! Authentification annulée\n')
        elif fin is None and code != 0:
            self._ecrire('fin-erreur', '✘ L’action a échoué (code %s)\n' % code)
        if action == 'rejoindre' and reussi and self.compilation_requise:
            self.compilation_requise = False
            self.compiler(lambda: self.executer('rejoindre', self.arguments_rejoindre + donnees.argv_paquets(
                self.dossier_compilation()), garder=True), rejoindre=True)
            return
        if action == 'rejoindre':
            self.rejoindre_en_cours = False
            if reussi:
                self._page_finale_rejoindre()
            else:
                self.statut_erreur.set_description(self._message_erreur(code, fin, annule))
                self.pages.set_visible_child_name('erreur')
        else:
            self.page_figee = False
            self.toast((fin['message'] if fin and fin['message'] else None)
                       or (CODE_ANNULE if annule else ('Terminé' if reussi else 'L’action a échoué')))
        self._maj_boutons()
        self.actualiser()

    # --- compilation de Himmelblau (sous l'utilisateur, sans pkexec) ---------------------------------------------

    def dossier_compilation(self):
        return donnees.dossier_compilation(self.coeur, self.config)

    def compiler(self, suite=None, rejoindre=False):
        """Compile Himmelblau (file Gagarine si présente), puis appelle suite() si elle réussit."""
        if self.lanceur.occupe:
            self.toast('Une action est déjà en cours')
            return
        if getattr(self.coeur, 'compilation', None) is None:
            self.toast('Compilation impossible : module de compilation absent')
            return
        argv = donnees.argv_compilation(self.coeur, self.dossier_compilation())
        self.suite_compilation = suite
        self.rejoindre_en_cours = rejoindre
        self.en_compilation = True
        self.action_en_cours = 'compiler'
        self.page_figee = True
        self._demarrer_progression('compiler', garder=rejoindre)
        self.titre_progression.set_text('Compilation de Himmelblau…')
        self._nouvelle_ligne('Compiler Himmelblau')
        self.note_compilation.set_visible(True)
        self.lanceur.lancer(argv, None, self._evenement, self._compilation_finie)
        self._maj_boutons()

    def _compilation_finie(self, code, fin):
        self.en_compilation = False
        self.action_en_cours = None
        reussi = (fin['ok'] if fin is not None else code == 0)
        self._terminer_lignes(reussi)
        self.note_compilation.set_visible(False)
        suite, self.suite_compilation = self.suite_compilation, None
        if reussi and suite is not None:
            suite()
            return
        if self.rejoindre_en_cours:
            self.rejoindre_en_cours = False
            if reussi:
                self._page_finale_rejoindre()
            else:
                message = (fin['message'] if fin and fin.get('message') else
                           'La compilation de Himmelblau s’est arrêtée (code %s).' % code)
                self.statut_erreur.set_description(message + '\n\nOuvrez le journal pour voir pourquoi, puis réessayez : '
                                                   'l’assistant reprend où il s’est arrêté.')
                self.pages.set_visible_child_name('erreur')
        else:
            self.page_figee = False
            self.toast((fin['message'] if fin and fin.get('message') else None)
                       or ('Compilation terminée' if reussi else 'La compilation a échoué'))
        self._maj_boutons()
        self.actualiser()

    def _page_finale_rejoindre(self):
        compte, nom = self.dernier_rejoindre or ('', '')
        self.statut_final.set_description(donnees.texte_final(nom, compte))
        self.pages.set_visible_child_name('final')

    def mettre_a_jour(self):
        """Menu « Mettre à jour Himmelblau » : compilation de la dernière version stable, puis installation."""
        self.bandeau.set_revealed(False)
        paquets = donnees.argv_paquets(self.dossier_compilation())
        self.compiler(lambda: self.executer('installer', paquets, garder=True))

    def verifier_mise_a_jour(self):
        """Au démarrage : propose la mise à jour si une nouvelle version stable existe (silencieux sinon)."""
        compilation = getattr(self.coeur, 'compilation', None)
        if compilation is None or self.mise_a_jour_proposee or donnees.statut_etape(self.etats, 'installer') != 'fait':
            return
        self.mise_a_jour_proposee = True
        dossier = self.dossier_compilation()

        def travail():
            return not compilation.a_jour(dossier)

        def fini(nouvelle, erreur):
            if erreur is None and nouvelle:
                self.bandeau.set_revealed(True)
        lanceur.en_arriere(travail, fini)

    @staticmethod
    def _message_erreur(code, fin, annule):
        if annule:
            return CODE_ANNULE
        if fin is not None and fin.get('message'):
            return fin['message'] + '\n\nRien n’est perdu : vous pouvez réessayer, l’assistant reprend où il s’est arrêté.'
        return ('L’opération s’est arrêtée (code %s). Ouvrez le journal pour voir pourquoi, puis réessayez : l’assistant '
                'reprend où il s’est arrêté.' % code)
