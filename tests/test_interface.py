"""Tests de l'assistant graphique, avec un faux cœur injecté ici seulement (sys.modules).

La fenêtre n'est construite que si GTK, libadwaita et un affichage sont disponibles ; sinon skipTest.
"""
import os
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

ETATS = [
    {'id': 'sauvegarde', 'titre': 'Sauvegarder', 'statut': 'fait', 'detail': 'Sauvegarde du jour', 'explication': 'e', 'action': 'sauvegarde'},
    {'id': 'secours', 'titre': 'Compte de secours', 'statut': 'a_faire', 'detail': '', 'explication': 'e', 'action': 'secours'},
    {'id': 'quitter_ad', 'titre': 'Quitter AD', 'statut': 'sans_objet', 'detail': 'Aucun domaine', 'explication': 'e', 'action': 'quitter-ad'},
    {'id': 'installer', 'titre': 'Installer authd', 'statut': 'bloquee', 'detail': 'Il faut d\'abord : Compte de secours.', 'explication': 'e', 'action': 'installer'},
]


@dataclass
class FauxConfig:
    locataire: str = '11111111-2222-3333-4444-555555555555'
    client: str = ''
    compte: str = 'a.b@exemple.com'
    compte_local: str = 'charles'
    secours: str = 'secours'
    groupes: list = field(default_factory=lambda: ['sudo'])


def faux_coeur():
    """Modules sesame.* de remplacement : rend {nom complet: module}."""
    def module(nom, **attributs):
        m = types.ModuleType(nom)
        m.__dict__.update(attributs)
        return m
    etapes = [types.SimpleNamespace(id=e['id'], titre=e['titre'], explication='Explication', action_racine=e['action']) for e in ETATS]
    return {
        'sesame.systeme': module('sesame.systeme', Systeme=lambda *a, **k: object()),
        'sesame.config': module('sesame.config', charger=lambda s: FauxConfig(), defauts=lambda s: FauxConfig(),
                                valider_guid=lambda t: len(t) == 36, valider_upn=lambda t: '@' in t),
        'sesame.etapes': module('sesame.etapes', ETAPES=etapes, lire_etat=lambda s: [dict(e) for e in ETATS],
                                etape_suivante=lambda etats: 'secours', derniere_reprise=lambda s: None),
        'sesame.verification': module('sesame.verification', controler=lambda s, c: [(True, 'ok')]),
        'sesame.guide': module('sesame.guide', PORTAIL=[('Titre', 'Détail')], URL_PORTAIL='https://entra.microsoft.com'),
        'sesame.version': module('sesame.version', VERSION='1.0.0'),
    }


class Injection(unittest.TestCase):
    """Installe le faux cœur le temps de la classe."""

    @classmethod
    def setUpClass(cls):
        cls._sauve = {n: sys.modules.get(n) for n in faux_coeur()}
        sys.modules.update(faux_coeur())

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
        self.assertEqual(donnees.valider_champ(coeur, 'locataire', '')[0], 'vide')
        self.assertEqual(donnees.valider_champ(coeur, 'locataire', 'abc')[0], 'erreur')
        self.assertEqual(donnees.valider_champ(coeur, 'locataire', 'x' * 36)[0], 'ok')
        self.assertEqual(donnees.valider_champ(coeur, 'compte', ' Prenom.Nom@Exemple.com ')[1:], ('prenom.nom@exemple.com', ''))
        self.assertEqual(donnees.valider_champ(coeur, 'compte', 'sans-arobase')[0], 'erreur')
        self.assertEqual(donnees.valider_champ(coeur, 'compte_local', 'charles-gamligo')[0], 'ok')
        self.assertEqual(donnees.valider_champ(coeur, 'compte_local', 'Charles')[0], 'erreur')

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

    def construire(self):
        from sesame.interface.fenetre import Fenetre
        f = Fenetre(self.app)
        self.assertTrue(attendre(lambda: f.etats))
        return f

    def test_import_et_construction(self):
        f = self.construire()
        self.assertEqual(set(f.rangees), {e['id'] for e in ETATS})
        self.assertEqual(f.champs['locataire'].get_text(), '11111111-2222-3333-4444-555555555555')
        self.assertEqual(f.bandeau.get_title(), 'Étape suivante : Compte de secours')

    def test_icones_et_boutons(self):
        f = self.construire()
        self.assertEqual(f.rangees['sauvegarde'].icone.get_icon_name(), 'emblem-ok-symbolic')
        self.assertEqual(f.rangees['sauvegarde'].bouton.get_label(), 'Refaire')
        self.assertEqual(f.rangees['secours'].bouton.get_label(), 'Lancer')
        self.assertEqual(f.rangees['secours'].icone.get_icon_name(), 'media-record-symbolic')
        self.assertFalse(f.rangees['quitter_ad'].bouton.get_visible())

    def test_etape_bloquee_desactivee(self):
        f = self.construire()
        b = f.rangees['installer'].bouton
        self.assertFalse(b.get_sensitive())
        self.assertIn('Compte de secours', b.get_tooltip_text())
        self.assertTrue(f.rangees['secours'].bouton.get_sensitive())

    def test_validation_en_direct(self):
        f = self.construire()
        champ = f.champs['locataire']
        champ.set_text('pas-un-guid')
        self.assertTrue(champ.has_css_class('error'))
        champ.set_text('x' * 36)
        self.assertFalse(champ.has_css_class('error'))
        valeurs, mauvais = f.valeurs_champs()
        self.assertIn('ID client (application)', mauvais)  # client vide
        self.assertNotIn('ID du locataire (annuaire)', mauvais)

    def test_configurer_refuse_champ_invalide(self):
        f = self.construire()
        lancements = []
        f.executer = lambda *a, **k: lancements.append(a)
        f.lancer_etape('configurer')
        self.assertEqual(lancements, [])  # le client est vide

    def test_configurer_passe_le_mode_de_connexion(self):
        f = self.construire()
        self.assertEqual(f.valeur_connexion(), 'mot-de-passe')  # FauxConfig n'a pas de mode : comme sur Windows
        f.champs['client'].set_text('6' * 36)
        lancements = []
        f.executer = lambda *a, **k: lancements.append(a)
        f.lancer_etape('configurer')
        mode = lambda arguments: arguments[arguments.index('--connexion') + 1]
        self.assertEqual(mode(lancements[0][1]), 'mot-de-passe')
        f.connexion.set_selected(1)
        f.lancer_etape('configurer')
        self.assertEqual(mode(lancements[1][1]), 'code')

    def test_texte_premiere_connexion(self):
        from sesame.interface import dialogues
        texte = dialogues.texte_premiere_connexion('a@b.com')
        self.assertIn('(a@b.com)', texte)
        self.assertIn('mot de passe Entra', texte)
        self.assertNotIn('QR code', texte)
        self.assertIn('QR code', dialogues.texte_premiere_connexion('', 'code'))

    def test_une_seule_action(self):
        f = self.construire()
        f.lanceur.processus = object()  # une action tourne
        lancements = []
        f.executer = lambda *a, **k: lancements.append(a)
        f.lancer_etape('sauvegarde')
        self.assertEqual(lancements, [])
        f.lanceur.processus = None

    def test_journal(self):
        f = self.construire()
        f._evenement(donnees.decoder_ligne('{"type": "commande", "texte": "apt-get update"}'))
        f._evenement(donnees.decoder_ligne('{"type": "fin", "ok": true, "message": "Fini"}'))
        texte = f.tampon.get_text(f.tampon.get_start_iter(), f.tampon.get_end_iter(), False)
        self.assertIn('$ apt-get update', texte)
        self.assertIn('✔ Fini', texte)


if __name__ == '__main__':
    unittest.main()
