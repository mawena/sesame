"""Application GTK : instance unique, icônes du dépôt, boîte « À propos »."""
import os

import gi

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Adw, Gdk, Gio, GLib, Gtk

from . import donnees


class Application(Adw.Application):
    def __init__(self):
        super().__init__(application_id=donnees.APPLICATION_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        GLib.set_application_name('Sésame')
        GLib.set_prgname(donnees.APPLICATION_ID)
        self.fenetre = None

    def do_startup(self):
        Adw.Application.do_startup(self)
        depot = donnees.dossier_depot()
        if depot and Gdk.Display.get_default():
            Gtk.IconTheme.get_for_display(Gdk.Display.get_default()).add_search_path(os.path.join(depot, 'data', 'icons'))
        Gtk.Window.set_default_icon_name(donnees.APPLICATION_ID)
        a = Gio.SimpleAction.new('a-propos', None)
        a.connect('activate', lambda *_: self.a_propos())
        self.add_action(a)
        q = Gio.SimpleAction.new('quitter', None)
        q.connect('activate', lambda *_: self.quit())
        self.add_action(q)
        self.set_accels_for_action('app.quitter', ['<Control>q'])

    def do_activate(self):
        if self.fenetre is None:
            from .fenetre import Fenetre
            self.fenetre = Fenetre(self)
        self.fenetre.present()

    def a_propos(self):
        try:
            version = donnees.charger_coeur().version.VERSION
        except ImportError:
            version = '1.0.0'
        d = Adw.AboutDialog(application_name='Sésame', application_icon=donnees.APPLICATION_ID, version=version,
                            developer_name='mawena', developers=['mawena'], copyright='© 2026 mawena',
                            license_type=Gtk.License.MIT_X11, website=donnees.SITE, issue_url=donnees.DEPOT + '/issues',
                            comments='Connecte le poste à Microsoft Entra ID par authd, et fait reprendre au compte '
                                     'Entra le compte local existant.')
        d.present(self.fenetre)


def principal(argv):
    return Application().run(argv)
