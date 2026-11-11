#!/usr/bin/python3
"""Capture de l'assistant graphique : page « Rejoindre » avec des valeurs d'exemple, dans docs/captures/apercu.png (640 × 760).

Construit la fenêtre avec un faux cœur (état de démonstration), la fait dessiner hors écran dans un Xvfb quand il
est disponible (sinon sur l'affichage courant) et enregistre le rendu en PNG. Aucune action réelle n'est lancée.
Lancer : gagarine file "sesame capture" 1 1 -- python3 scripts/capture-interface.py
"""
import os
import shutil
import sys
import types
from dataclasses import dataclass

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

LARGEUR, HAUTEUR = 640, 760

ETATS = [
    ('sauvegarde', 'Sauvegarder la configuration', 'a_faire', '', 'sauvegarde', 'Copie les fichiers de comptes et de connexion.'),
    ('secours', 'Créer le compte de secours', 'a_faire', '', 'secours', 'Un compte administrateur local de dépannage.'),
    ('nom_machine', 'Nommer la machine', 'a_faire', '', 'nom-machine', 'Donne son nom au poste.'),
    ('quitter_ad', 'Quitter le domaine Active Directory', 'sans_objet', 'Aucun domaine', 'quitter-ad', 'Retire le poste de l’ancien domaine.'),
    ('outils', 'Installer les outils de compilation', 'a_faire', '', 'outils', 'Installe podman, git et make.'),
    ('compiler', 'Compiler Himmelblau', 'a_faire', '', None, 'Compile Himmelblau sur ce poste.'),
    ('installer', 'Installer Himmelblau', 'a_faire', '', 'installer', 'Installe Himmelblau.'),
    ('configurer', 'Relier votre compte à Entra', 'a_faire', '', 'configurer', 'Relie votre compte local à Entra.'),
    ('premiere_connexion', 'Première connexion', 'a_faire', '', 'noter-premiere-connexion', 'Connectez-vous une fois avec Entra.'),
]


@dataclass
class Config:
    compte: str = ''
    nom_machine: str = ''
    secours: str = 'secours'


def installer_faux_coeur():
    def module(nom, **attributs):
        m = types.ModuleType(nom)
        m.__dict__.update(attributs)
        sys.modules[nom] = m
    module('sesame.systeme', Systeme=lambda *a, **k: object())
    module('sesame.config', charger=lambda s: Config(), defauts=lambda s: Config(),
           valider_nom_machine=lambda t: bool(t) and len(t) <= 15, valider_upn=lambda t: '@' in t)
    module('sesame.etapes', etape_suivante=lambda e: 'sauvegarde',
           lire_etat=lambda s: [{'id': i, 'titre': t, 'statut': st, 'detail': d, 'explication': x, 'action': a}
                                for i, t, st, d, a, x in ETATS])
    module('sesame.verification', controler=lambda s, c: [])
    module('sesame.version', VERSION='2.0.0')
    module('sesame.compilation', dossier_par_defaut=lambda: '/tmp/himmelblau', a_jour=lambda d, l: True)


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
    fenetre.champs['compte'].set_text('prenom.nom@exemple.com')
    fenetre.champs['nom_machine'].set_text('LPCFNTG-00123')
    fenetre.set_focus(None)
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
