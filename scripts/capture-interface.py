#!/usr/bin/python3
"""Capture de l'assistant graphique : docs/captures/apercu.png (720 × 1040 : toutes les étapes visibles).

Construit la fenêtre avec un faux cœur (état de démonstration), la fait dessiner hors écran dans un Xvfb quand il
est disponible (sinon sur l'affichage courant) et enregistre le rendu en PNG. Aucune action réelle n'est lancée.
Lancer : gagarine file "sesame capture" 1 1 -- python3 scripts/capture-interface.py
"""
import os
import shutil
import sys
import types
from dataclasses import dataclass, field

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Sous Xvfb : pas de fenêtre sur l'écran réel. On se relance une fois dans xvfb-run si c'est possible.
if not os.environ.get('SESAME_CAPTURE_XVFB') and shutil.which('xvfb-run'):
    os.environ['SESAME_CAPTURE_XVFB'] = '1'
    os.environ['GDK_BACKEND'] = 'x11'
    os.execvp('xvfb-run', ['xvfb-run', '-a', '-s', '-screen 0 1280x1024x24', sys.executable, os.path.abspath(__file__)])

sys.path.insert(0, RACINE)

import gi

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
gi.require_version('Graphene', '1.0')
from gi.repository import Adw, Gdk, GLib, Graphene, Gtk

LARGEUR, HAUTEUR = 720, 1040  # un peu plus haut que la fenêtre par défaut, pour montrer toutes les étapes

ETATS = [
    ('sauvegarde', 'Sauvegarder la configuration', 'fait', 'Sauvegarde du 11/11/2026 à 09:12', 'sauvegarde',
     'Copie les fichiers de comptes et de connexion avant toute modification.'),
    ('secours', 'Créer le compte de secours', 'fait', 'Le compte « secours » existe et est dans sudo', 'secours',
     'Un compte administrateur local de dépannage.'),
    ('quitter_ad', 'Quitter le domaine Active Directory', 'fait', 'Le poste a quitté le domaine cofina.local', 'quitter-ad',
     'Retire le poste de l’ancien domaine.'),
    ('installer', 'Installer authd et le module Entra', 'fait', 'authd 0.5.3 et authd-msentraid installés', 'installer',
     'Installe authd et le module Microsoft Entra.'),
    ('configurer', 'Configurer la connexion Entra', 'a_faire', 'Renseignez les champs ci-dessus, puis lancez', 'configurer',
     'Écrit la configuration d’authd pour votre annuaire.'),
    ('premiere_connexion', 'Première connexion par Entra', 'bloquee', 'Il faut d’abord : Configurer la connexion Entra.',
     None, 'Connectez-vous une fois avec votre compte Entra.'),
    ('reprise', 'Reprendre le compte local', 'bloquee', 'Il faut d’abord : Première connexion par Entra.', 'reprise',
     'Le compte Entra remplace le compte local, avec le même dossier personnel.'),
    ('verification', 'Vérifier', 'bloquee', 'Il faut d’abord : Reprendre le compte local.', None,
     'Contrôle que tout est en place.'),
]


@dataclass
class Config:
    locataire: str = '3f2a9c1e-7b54-4d08-9a6e-1c5d82f04b37'
    client: str = 'a81d6e90-2c4f-47b3-8e15-d9f0637ab2c4'
    compte: str = 'prenom.nom@exemple.com'
    compte_local: str = 'prenom-nom'
    secours: str = 'secours'
    groupes: list = field(default_factory=lambda: ['sudo', 'lpadmin'])


def installer_faux_coeur():
    def module(nom, **attributs):
        m = types.ModuleType(nom)
        m.__dict__.update(attributs)
        sys.modules[nom] = m
    etapes = [types.SimpleNamespace(id=i, titre=t, explication=x, action_racine=a) for i, t, _, _, a, x in ETATS]
    module('sesame.systeme', Systeme=lambda *a, **k: object())
    module('sesame.config', charger=lambda s: Config(), defauts=lambda s: Config(),
           valider_guid=lambda t: len(t) == 36, valider_upn=lambda t: '@' in t)
    module('sesame.etapes', ETAPES=etapes, derniere_reprise=lambda s: None, etape_suivante=lambda e: 'configurer',
           lire_etat=lambda s: [{'id': i, 'titre': t, 'statut': st, 'detail': d, 'explication': x, 'action': a}
                                for i, t, st, d, a, x in ETATS])
    module('sesame.verification', controler=lambda s, c: [])
    module('sesame.guide', PORTAIL=[], URL_PORTAIL='https://entra.microsoft.com')
    module('sesame.version', VERSION='1.0.0')


def main():
    if Gdk.Display.get_default() is None and not Gtk.init_check():
        print('Pas d’affichage : capture impossible.', file=sys.stderr)
        return 1
    installer_faux_coeur()
    from sesame.interface import donnees
    from sesame.interface.fenetre import Fenetre
    Adw.init()
    depot = donnees.dossier_depot()
    if depot:
        Gtk.IconTheme.get_for_display(Gdk.Display.get_default()).add_search_path(os.path.join(depot, 'data', 'icons'))
    app = Adw.Application(application_id=donnees.APPLICATION_ID + '.Capture')
    app.register(None)
    fenetre = Fenetre(app)
    fenetre.set_default_size(LARGEUR, HAUTEUR)
    fenetre.present()
    contexte = GLib.MainContext.default()

    def tourner(secondes):
        import time
        fin = time.monotonic() + secondes
        while time.monotonic() < fin:
            while contexte.pending():
                contexte.iteration(False)
            time.sleep(0.01)

    tourner(1.5)
    if not fenetre.etats:
        print('L’état de démonstration n’a pas été chargé.', file=sys.stderr)
        return 1
    fenetre.set_focus(None)
    fenetre.expandeur.set_expanded(False)
    tourner(0.5)
    paintable = Gtk.WidgetPaintable.new(fenetre)
    largeur, hauteur = fenetre.get_width(), fenetre.get_height()
    snapshot = Gtk.Snapshot()
    paintable.snapshot(snapshot, largeur, hauteur)
    noeud = snapshot.to_node()
    if noeud is None:
        print('Rendu vide : capture impossible.', file=sys.stderr)
        return 1
    texture = fenetre.get_renderer().render_texture(noeud, Graphene.Rect().init(0, 0, largeur, hauteur))
    sortie = os.path.join(RACINE, 'docs', 'captures', 'apercu.png')
    os.makedirs(os.path.dirname(sortie), exist_ok=True)
    texture.save_to_png(sortie)
    print('Capture écrite : %s (%d × %d)' % (sortie, texture.get_width(), texture.get_height()))
    return 0


if __name__ == '__main__':
    sys.exit(main())
