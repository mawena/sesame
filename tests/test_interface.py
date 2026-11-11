"""Tests de l'assistant graphique, avec un faux cœur injecté ici seulement (sys.modules).

La fenêtre n'est construite que si GTK, libadwaita et un affichage sont disponibles ; sinon skipTest.
"""
import getpass
import os
import socket
import sys
import time
import types
import unittest
from dataclasses import dataclass, field

from sesame.interface import donnees

try:
    import gi
    gi.require_version('Gtk', '4.0')
    gi.require_version('Adw', '1')
    from gi.repository import Adw, Gdk, GLib, Gtk
    from sesame.interface import lanceur
    GI = True
    Gtk.init_check()
    AFFICHAGE = Gdk.Display.get_default() is not None
except (ImportError, ValueError):
    GI = AFFICHAGE = False

def etat(id_, statut, titre=None, detail=''):
    return {'id': id_, 'titre': titre or id_, 'statut': statut, 'detail': detail, 'explication': 'Explication',
            'action': id_.replace('_', '-')}


IDS = ('sauvegarde', 'secours', 'nom_machine', 'quitter_ad', 'outils', 'compiler', 'installer', 'configurer',
       'premiere_connexion')
COURANT = {'etats': None, 'a_jour': True, 'compilations': []}


def etats_initiaux(**statuts):
    """Les étapes, toutes « a_faire » sauf celles données (ex. installer='fait')."""
    return [etat(i, statuts.get(i, 'a_faire')) for i in IDS]


@dataclass
class FauxConfig:
    compte: str = 'a.b@exemple.com'
    nom_machine: str = ''
    secours: str = 'secours'


def faux_coeur():
    """Modules sesame.* de remplacement : rend {nom complet: module}."""
    def module(nom, **attributs):
        m = types.ModuleType(nom)
        m.__dict__.update(attributs)
        return m
    return {
        'sesame.systeme': module('sesame.systeme', Systeme=lambda *a, **k: object()),
        'sesame.config': module('sesame.config', charger=lambda s: FauxConfig(), defauts=lambda s: FauxConfig(),
                                valider_nom_machine=lambda t: len(t) <= 15 and not t.startswith('-'),
                                valider_upn=lambda t: '@' in t),
        'sesame.etapes': module('sesame.etapes', lire_etat=lambda s: [dict(e) for e in COURANT['etats']]),
        'sesame.verification': module('sesame.verification', controler=lambda s, c: [(True, 'ok')]),
        'sesame.version': module('sesame.version', VERSION='2.0.0'),
        'sesame.compilation': module(
            'sesame.compilation', dossier_par_defaut=lambda: '/tmp/sesame-himmelblau',
            commande_file=lambda d: None,
            commande_directe=lambda d: ['sh', '-c', COURANT.get('script_compilation', 'exit 0'), 'x', d],
            a_jour=lambda d, lancer=None: COURANT['a_jour']),
    }


class Injection(unittest.TestCase):
    """Installe le faux cœur le temps de la classe."""

    @classmethod
    def setUpClass(cls):
        cls._sauve = {n: sys.modules.get(n) for n in faux_coeur()}
        sys.modules.update(faux_coeur())
        COURANT.update(etats=etats_initiaux(), a_jour=True)
        COURANT.pop('script_compilation', None)

    @classmethod
    def tearDownClass(cls):
        for nom, ancien in cls._sauve.items():
            if ancien is None:
                sys.modules.pop(nom, None)
            else:
                sys.modules[nom] = ancien


def attendre(condition, delai=10.0):
    contexte = GLib.MainContext.default()
    fin = time.monotonic() + delai
    while time.monotonic() < fin:
        while contexte.pending():
            contexte.iteration(False)
        if condition():
            return True
        time.sleep(0.01)
    return False


class TestDonnees(Injection):
    def test_statut_icone(self):
        self.assertEqual(donnees.icone_statut('fait')[0], 'emblem-ok-symbolic')
        self.assertEqual(donnees.icone_statut('bloquee')[0], 'action-unavailable-symbolic')
        self.assertEqual(donnees.icone_statut('inattendu'), donnees.STATUTS['inconnu'])
        for statut, (icone, classe, libelle) in donnees.STATUTS.items():
            self.assertTrue(icone.endswith('-symbolic'), statut)

    def test_boutons(self):
        self.assertEqual(donnees.libelle_bouton('a_faire'), 'Lancer')
        self.assertEqual(donnees.libelle_bouton('fait'), 'Refaire')
        self.assertIsNone(donnees.libelle_bouton('sans_objet'))

    def test_decodage_journal(self):
        e = donnees.decoder_ligne('{"type": "fin", "ok": true, "message": "Terminé"}\n')
        self.assertEqual((e['type'], e['ok'], e['message']), ('fin', True, 'Terminé'))
        self.assertEqual(donnees.decoder_ligne('{"type": "etape", "texte": "Sauvegarde"}')['texte'], 'Sauvegarde')
        brut = donnees.decoder_ligne('pkexec: Error')
        self.assertEqual((brut['type'], brut['texte']), ('sortie', 'pkexec: Error'))
        self.assertEqual(donnees.decoder_ligne('[1, 2]')['type'], 'sortie')
        self.assertEqual(donnees.decoder_ligne('{"type": 3}')['type'], 'sortie')

    def test_mise_en_forme(self):
        self.assertEqual(donnees.mise_en_forme({'type': 'commande', 'texte': 'apt'})[1], '$ apt\n')
        self.assertEqual(donnees.mise_en_forme({'type': 'fin', 'ok': False, 'message': 'x'})[0], 'fin-erreur')
        self.assertEqual(donnees.mise_en_forme({'type': 'avertissement', 'texte': 'a'})[0], 'avertissement')

    def test_validation_champs(self):
        coeur = donnees.charger_coeur()
        self.assertEqual(donnees.valider_champ(coeur, 'compte', '')[0], 'vide')
        self.assertEqual(donnees.valider_champ(coeur, 'compte', ' Prenom.Nom@Exemple.com ')[1:], ('prenom.nom@exemple.com', ''))
        self.assertEqual(donnees.valider_champ(coeur, 'compte', 'sans-arobase')[0], 'erreur')
        self.assertEqual(donnees.valider_champ(coeur, 'nom_machine', 'LPCFNTG-00123')[0], 'ok')
        self.assertEqual(donnees.valider_champ(coeur, 'nom_machine', '-mauvais')[0], 'erreur')

    def test_deja_relie_et_texte_final(self):
        self.assertTrue(donnees.deja_relie(etats_initiaux(configurer='fait')))
        self.assertFalse(donnees.deja_relie(etats_initiaux()))
        texte = donnees.texte_final('PC-1', 'a@b.com')
        self.assertIn('Le poste PC-1 est prêt', texte)
        self.assertIn('mot de passe Entra de a@b.com', texte)

    def test_actions(self):
        self.assertEqual(donnees.action_de_etape({'id': 'premiere_connexion', 'action': None}), 'noter-premiere-connexion')
        self.assertEqual(donnees.action_de_etape({'id': 'nom_machine'}), 'nom-machine')
        self.assertEqual(donnees.action_de_etape({'id': 'outils'}), 'outils')

    def test_commande_compilation_sous_utilisateur(self):
        coeur = donnees.charger_coeur()
        argv = donnees.argv_compilation(coeur, '/d')
        self.assertEqual(argv[-1], '--json')
        self.assertNotIn('pkexec', argv)
        self.assertEqual(donnees.argv_paquets('/d'), ['--paquets', '/d/packaging'])

    def test_validation_secours(self):
        self.assertIn('8', donnees.valider_secours('court', 'court'))
        self.assertIn('identiques', donnees.valider_secours('longmotdepasse', 'autremotdepasse'))
        self.assertIsNone(donnees.valider_secours('longmotdepasse', 'longmotdepasse'))

    def test_commande_racine(self):
        argv = donnees.commande_racine('secours', ['--nom', 'x'])
        self.assertEqual(argv[0], 'pkexec')
        self.assertTrue(argv[1].endswith('sesame-racine'))
        self.assertEqual(argv[2:], ['--json', 'secours', '--nom', 'x'])
        self.assertNotIn('sudo', argv)
        self.assertEqual(donnees.action_de_etape({'id': 'quitter_ad'}), 'quitter-ad')
        self.assertEqual(donnees.action_de_etape({'id': 'x', 'action': 'y'}), 'y')
        self.assertNotIn('authd', ' '.join(donnees.commande_racine('rejoindre')))


@unittest.skipUnless(GI, 'PyGObject, GTK 4 ou libadwaita absent')
class TestLanceur(unittest.TestCase):
    def test_lecture_ligne_par_ligne_et_stdin(self):
        lanceur_ = lanceur.Lanceur()
        evenements, fins = [], []
        script = 'read mdp; echo \'{"type": "etape", "texte": "début"}\'; echo "mdp=$mdp"; echo \'{"type": "fin", "ok": true, "message": "bien"}\'; exit 0'
        self.assertTrue(lanceur_.lancer(['sh', '-c', script], 'secret\n', evenements.append, lambda c, f: fins.append((c, f))))
        self.assertTrue(lanceur_.occupe)
        self.assertFalse(lanceur_.lancer(['true'], None, print, print))  # une seule action à la fois
        self.assertTrue(attendre(lambda: fins))
        self.assertFalse(lanceur_.occupe)
        self.assertEqual([e['type'] for e in evenements], ['etape', 'sortie', 'fin'])
        self.assertEqual(evenements[1]['texte'], 'mdp=secret')
        self.assertEqual(fins[0][0], 0)
        self.assertTrue(fins[0][1]['ok'])

    def test_code_de_sortie(self):
        lanceur_ = lanceur.Lanceur()
        fins = []
        lanceur_.lancer(['sh', '-c', 'exit 126'], None, lambda e: None, lambda c, f: fins.append((c, f)))
        self.assertTrue(attendre(lambda: fins))
        self.assertEqual(fins[0], (126, None))
        self.assertIn(126, lanceur.CODES_ANNULE)

    def test_commande_introuvable(self):
        fins = []
        lanceur.Lanceur().lancer(['/nexiste/pas'], None, lambda e: None, lambda c, f: fins.append((c, f)))
        self.assertTrue(attendre(lambda: fins))
        self.assertEqual(fins[0][0], -1)
        self.assertFalse(fins[0][1]['ok'])


@unittest.skipUnless(GI and AFFICHAGE, 'GTK ou affichage absent')
class TestFenetre(Injection):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Adw.init()
        cls.app = Adw.Application(application_id='io.github.mawena.SesameTest')
        cls.app.register(None)

    def construire(self, **statuts):
        COURANT['etats'] = etats_initiaux(**statuts)
        from sesame.interface.fenetre import Fenetre
        f = Fenetre(self.app)
        self.assertTrue(attendre(lambda: f.etats))
        return f

    @staticmethod
    def espion(f):
        lancements = []
        f.executer = lambda *a, **k: lancements.append((a, k))
        return lancements

    @staticmethod
    def remplir(f, compte='prenom.nom@exemple.com', nom='LPCFNTG-00123'):
        f.champs['compte'].set_text(compte)
        f.champs['nom_machine'].set_text(nom)

    def page(self, f):
        return f.pages.get_visible_child_name()

    def test_construction_et_preremplissage(self):
        f = self.construire()
        self.assertEqual(f.champs['compte'].get_text(), 'a.b@exemple.com')
        self.assertEqual(f.champs['nom_machine'].get_text(), socket.gethostname().split('.')[0])
        self.assertEqual(self.page(f), 'formulaire')
        self.assertEqual(f.bouton_rejoindre.get_label(), 'Rejoindre')
        self.assertTrue(f.bouton_rejoindre.has_css_class('suggested-action'))
        self.assertTrue(f.bouton_rejoindre.has_css_class('pill'))
        self.assertNotIn('jeton', f.champs)  # plus de dépôt payant

    def test_validation_en_direct(self):
        f = self.construire()
        f.champs['compte'].set_text('pas-une-adresse')
        self.assertTrue(f.champs['compte'].has_css_class('error'))
        self.assertFalse(f.bouton_rejoindre.get_sensitive())
        f.champs['compte'].set_text('a@b.com')
        self.assertFalse(f.champs['compte'].has_css_class('error'))
        f.champs['nom_machine'].set_text('-mauvais')
        self.assertTrue(f.champs['nom_machine'].has_css_class('error'))
        self.assertFalse(f.bouton_rejoindre.get_sensitive())
        f.champs['nom_machine'].set_text('PC-1')
        self.assertTrue(f.bouton_rejoindre.get_sensitive())
        f.champs['compte'].set_text('')
        self.assertFalse(f.bouton_rejoindre.get_sensitive())

    def test_rejoindre_arguments_sans_stdin(self):
        f = self.construire()
        self.remplir(f, ' Prenom.Nom@Exemple.com ', 'LPCFNTG-00123')
        lancements = self.espion(f)
        f.bouton_rejoindre.emit('clicked')
        (args, kw), = lancements
        self.assertEqual(args[0], 'rejoindre')
        self.assertEqual(args[1], ['--compte', 'prenom.nom@exemple.com', '--nom-machine', 'LPCFNTG-00123',
                                   '--compte-local', getpass.getuser()])
        self.assertNotIn('stdin', kw)

    def test_rejoindre_refuse_champ_invalide(self):
        f = self.construire()
        f.champs['compte'].set_text('')
        lancements = self.espion(f)
        f.rejoindre()
        self.assertEqual(lancements, [])

    def lancer_faux(self, f, script):
        """Fait tourner « rejoindre » avec un faux sesame-racine (script sh) à la place de pkexec ; les arguments
        sont passés au script ($@) et chaque appel est noté dans self.appels."""
        self.remplir(f)
        self.appels = []
        reel = donnees.commande_racine

        def faux(action, arguments=()):
            self.appels.append((action, list(arguments)))
            return ['sh', '-c', script, 'x', action, *arguments]
        donnees.commande_racine = faux
        self.addCleanup(setattr, donnees, 'commande_racine', reel)
        f.rejoindre()

    def test_progression_puis_page_finale(self):
        f = self.construire()
        script = ('echo \'{"type": "etape", "texte": "Sauvegarde"}\'; '
                  'echo \'{"type": "etape", "texte": "Installation"}\'; '
                  'echo \'{"type": "fin", "ok": true, "message": "Prêt"}\'; exit 0')
        self.lancer_faux(f, script)
        self.assertEqual(self.page(f), 'progression')
        self.assertTrue(attendre(lambda: self.page(f) == 'final'))
        self.assertEqual([l.etat for l in f.lignes], ['fait', 'fait'])
        self.assertEqual(f.lignes[0].icone.get_icon_name(), 'emblem-ok-symbolic')
        self.assertIn('Le poste LPCFNTG-00123 est prêt', f.statut_final.get_description())
        self.assertIn('prenom.nom@exemple.com', f.statut_final.get_description())
        self.assertEqual(f.bouton_deconnexion.get_label(), 'Se déconnecter')
        self.assertIn('✔ Prêt', f.tampon.get_text(f.tampon.get_start_iter(), f.tampon.get_end_iter(), False))
        self.assertTrue(f.page_figee)

    SCRIPT_CHAINE = (
        'case "$*" in *--paquets*) echo \'{"type": "etape", "texte": "Installation"}\'; '
        'echo \'{"type": "fin", "ok": true, "message": "Prêt"}\';; '
        '*) echo \'{"type": "etape", "texte": "Outils"}\'; echo \'{"type": "compilation_requise"}\'; '
        'echo \'{"type": "fin", "ok": true, "message": "Préparation terminée"}\';; esac')

    def test_compilation_puis_seconde_passe(self):
        f = self.construire()
        COURANT['script_compilation'] = ('echo \'{"type": "etape", "texte": "Image"}\'; '
                                         'echo \'{"type": "sortie", "texte": "cargo build"}\'; '
                                         'echo \'{"type": "fin", "ok": true, "message": "Compilé"}\'')
        self.lancer_faux(f, self.SCRIPT_CHAINE)
        self.assertTrue(attendre(lambda: self.page(f) == 'final'))
        self.assertEqual([a for a, _ in self.appels], ['rejoindre', 'rejoindre'])
        self.assertNotIn('--paquets', self.appels[0][1])
        self.assertEqual(self.appels[1][1][-2:], ['--paquets', '/tmp/sesame-himmelblau/packaging'])
        titres = [l.row.get_title() for l in f.lignes]
        self.assertEqual(titres, ['Outils', 'Compiler Himmelblau', 'Installation'])
        self.assertTrue(all(l.etat == 'fait' for l in f.lignes))
        journal = f.tampon.get_text(f.tampon.get_start_iter(), f.tampon.get_end_iter(), False)
        self.assertIn('cargo build', journal)

    def test_compilation_en_echec(self):
        f = self.construire()
        COURANT['script_compilation'] = ('echo \'{"type": "fin", "ok": false, "message": "podman a échoué"}\'; exit 1')
        self.lancer_faux(f, self.SCRIPT_CHAINE)
        self.assertTrue(attendre(lambda: self.page(f) == 'erreur'))
        self.assertIn('podman a échoué', f.statut_erreur.get_description())
        self.assertEqual([a for a, _ in self.appels], ['rejoindre'])  # pas de seconde passe
        self.assertEqual(f.lignes[-1].etat, 'erreur')

    def test_details_outils_compiler_installer(self):
        f = self.construire()
        lancements = self.espion(f)
        f.lancer_etape('outils')
        f.lancer_etape('installer')
        self.assertEqual(lancements[0][0], ('outils', []))
        self.assertEqual(lancements[1][0], ('installer', ['--paquets', '/tmp/sesame-himmelblau/packaging']))
        appels = []
        f.compiler = lambda *a, **k: appels.append(a)
        f.lancer_etape('compiler')
        self.assertEqual(len(appels), 1)

    def test_mettre_a_jour_compile_puis_installe(self):
        f = self.construire(installer='fait', configurer='fait')
        self.assertIsNotNone(f.lookup_action('mettre-a-jour'))
        lancements = self.espion(f)
        COURANT['script_compilation'] = 'echo \'{"type": "fin", "ok": true, "message": "Compilé"}\''
        f.mettre_a_jour()
        self.assertTrue(attendre(lambda: lancements))
        self.assertEqual(lancements[0][0], ('installer', ['--paquets', '/tmp/sesame-himmelblau/packaging']))

    def test_bandeau_nouvelle_version(self):
        COURANT['a_jour'] = False
        f = self.construire(installer='fait', configurer='fait')
        self.assertTrue(attendre(lambda: f.bandeau.get_revealed()))
        COURANT['a_jour'] = True
        f2 = self.construire(installer='fait', configurer='fait')
        attendre(lambda: False, 0.5)
        self.assertFalse(f2.bandeau.get_revealed())

    def test_bandeau_absent_si_pas_installe(self):
        COURANT['a_jour'] = False
        f = self.construire()
        attendre(lambda: False, 0.5)
        self.assertFalse(f.bandeau.get_revealed())

    def test_evenements_simules(self):
        f = self.construire()
        f._demarrer_progression('rejoindre')
        f._evenement(donnees.decoder_ligne('{"type": "etape", "texte": "Un"}'))
        self.assertEqual([l.etat for l in f.lignes], ['en_cours'])
        f._evenement(donnees.decoder_ligne('{"type": "etape", "texte": "Deux"}'))
        self.assertEqual([l.etat for l in f.lignes], ['fait', 'en_cours'])
        f._evenement(donnees.decoder_ligne('{"type": "fin", "ok": false, "message": "Raté"}'))
        self.assertEqual([l.etat for l in f.lignes], ['fait', 'erreur'])
        self.assertEqual(f.lignes[1].icone.get_icon_name(), 'dialog-error-symbolic')

    def test_erreur_message_et_reessayer(self):
        f = self.construire()
        script = ('echo \'{"type": "etape", "texte": "Outils"}\'; '
                  'echo \'{"type": "fin", "ok": false, "message": "Jeton refusé"}\'; exit 1')
        self.lancer_faux(f, script)
        self.assertTrue(attendre(lambda: self.page(f) == 'erreur'))
        self.assertIn('Jeton refusé', f.statut_erreur.get_description())
        self.assertEqual(f.lignes[-1].etat, 'erreur')
        self.assertEqual(f.bouton_reessayer.get_label(), 'Réessayer')
        f.bouton_reessayer.emit('clicked')
        self.assertEqual(self.page(f), 'formulaire')
        self.assertEqual(f.champs['compte'].get_text(), 'prenom.nom@exemple.com')  # les champs sont gardés
        self.assertTrue(f.bouton_rejoindre.get_sensitive())

    def test_authentification_annulee(self):
        f = self.construire()
        self.lancer_faux(f, 'exit 126')
        self.assertTrue(attendre(lambda: self.page(f) == 'erreur'))
        self.assertIn('annulée', f.statut_erreur.get_description())

    def test_page_deja_relie(self):
        f = self.construire(installer='fait', configurer='fait')
        self.assertEqual(self.page(f), 'relie')
        self.assertIn('a.b@exemple.com', f.statut_relie.get_description())
        self.assertIn('première connexion', f.statut_relie.get_description())
        self.assertTrue(f.bouton_premiere.get_visible())
        self.assertEqual(f.bouton_premiere.get_label(), 'J’ai fait ma première connexion')
        lancements = self.espion(f)
        f.bouton_premiere.emit('clicked')
        self.assertEqual(lancements[0][0], ('noter-premiere-connexion', []))

    def test_page_relie_premiere_connexion_faite(self):
        f = self.construire(installer='fait', configurer='fait', premiere_connexion='fait')
        self.assertEqual(self.page(f), 'relie')
        self.assertFalse(f.bouton_premiere.get_visible())

    def test_details(self):
        f = self.construire(sauvegarde='fait')
        self.assertEqual(set(f.rangees), set(IDS))
        self.assertEqual(len(f.rangees), 9)
        self.assertEqual(f.rangees['sauvegarde'].bouton.get_label(), 'Refaire')
        self.assertEqual(f.rangees['sauvegarde'].icone.get_icon_name(), 'emblem-ok-symbolic')
        self.assertEqual(f.rangees['secours'].bouton.get_label(), 'Lancer')
        f.ouvrir_details()
        self.assertEqual(f.navigation.get_visible_page().get_tag(), 'details')
        lancements = self.espion(f)
        f.lancer_etape('sauvegarde')
        f.lancer_etape('installer')
        f.lancer_etape('quitter_ad')
        self.assertEqual([a for a, _ in lancements], [('sauvegarde', []), ('installer', ['--paquets', '/tmp/sesame-himmelblau/packaging']),
                          ('quitter-ad', [])])
        f.champs['nom_machine'].set_text('PC-9')
        f.lancer_etape('nom_machine')
        self.assertEqual(lancements[3][0], ('nom-machine', ['--nom', 'PC-9']))
        f.lancer_etape('configurer')
        self.assertEqual(lancements[4][0][1], ['--compte', 'a.b@exemple.com', '--compte-local', getpass.getuser()])

    def test_etape_bloquee_desactivee(self):
        COURANT['etats'] = etats_initiaux()
        COURANT['etats'][IDS.index('installer')] = etat('installer', 'bloquee', detail='Il faut d’abord : Compte de secours.')
        from sesame.interface.fenetre import Fenetre
        f = Fenetre(self.app)
        self.assertTrue(attendre(lambda: f.etats))
        b = f.rangees['installer'].bouton
        self.assertFalse(b.get_sensitive())
        self.assertIn('Compte de secours', b.get_tooltip_text())

    def test_une_seule_action(self):
        f = self.construire()
        f.lanceur.processus = object()  # une action tourne
        lancements = self.espion(f)
        f.lancer_etape('sauvegarde')
        f.rejoindre()
        self.assertEqual(lancements, [])
        f.lanceur.processus = None

    def test_menu_et_actions(self):
        f = self.construire()
        for nom in ('details', 'verifier', 'mettre-a-jour', 'desactiver'):
            self.assertIsNotNone(f.lookup_action(nom), nom)
        for ancien in ('guide', 'annuler-reprise'):
            self.assertIsNone(f.lookup_action(ancien), ancien)

    def test_texte_premiere_connexion(self):
        from sesame.interface import dialogues
        texte = dialogues.texte_premiere_connexion('a@b.com')
        self.assertIn('mot de passe Entra de a@b.com', texte)
        self.assertIn('PIN', texte)

    def test_journal(self):
        f = self.construire()
        f._evenement(donnees.decoder_ligne('{"type": "commande", "texte": "apt-get update"}'))
        f._evenement(donnees.decoder_ligne('{"type": "fin", "ok": true, "message": "Fini"}'))
        texte = f.tampon.get_text(f.tampon.get_start_iter(), f.tampon.get_end_iter(), False)
        self.assertIn('$ apt-get update', texte)
        self.assertIn('✔ Fini', texte)


if __name__ == '__main__':
    unittest.main()
