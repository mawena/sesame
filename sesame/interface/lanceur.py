"""Lancement asynchrone des actions root (pkexec), fermeture de session et redémarrage."""
import threading

import gi

gi.require_version('Gio', '2.0')
from gi.repository import Gio, GLib

from . import donnees

CODES_ANNULE = (126, 127)  # pkexec : authentification refusée ou annulée / commande introuvable


class Lanceur:
    """Une seule action à la fois. Lecture ligne par ligne sans jamais bloquer la boucle principale."""

    def __init__(self):
        self.processus = None
        self._fin = None
        self._fin_evenement = None

    @property
    def occupe(self):
        return self.processus is not None

    def lancer(self, argv, stdin_texte, sur_evenement, sur_fin):
        """Lance argv. sur_evenement(dict) reçoit chaque ligne décodée ; sur_fin(code, evenement_fin) à la fin
        (evenement_fin est le dernier événement « fin », ou None). Rend False si une action tourne déjà."""
        if self.occupe:
            return False
        drapeaux = Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_MERGE
        if stdin_texte is not None:
            drapeaux |= Gio.SubprocessFlags.STDIN_PIPE
        try:
            proc = Gio.Subprocess.new(argv, drapeaux)
        except GLib.Error as erreur:
            sur_evenement({'type': 'avertissement', 'texte': erreur.message, 'ok': False, 'message': ''})
            sur_fin(-1, {'type': 'fin', 'texte': '', 'ok': False, 'message': 'Impossible de lancer la commande : ' + erreur.message})
            return True
        self.processus = proc
        self._fin = sur_fin
        self._fin_evenement = None
        if stdin_texte is not None:
            entree = proc.get_stdin_pipe()
            try:
                entree.write_bytes(GLib.Bytes.new(stdin_texte.encode()), None)
            except GLib.Error:
                pass
            try:
                entree.close(None)
            except GLib.Error:
                pass
        flux = Gio.DataInputStream.new(proc.get_stdout_pipe())
        self._lire(flux, sur_evenement)
        return True

    def _lire(self, flux, sur_evenement):
        def recu(source, resultat):
            try:
                ligne, _ = source.read_line_finish_utf8(resultat)
            except GLib.Error:
                ligne = None
            if ligne is None:
                self.processus.wait_async(None, self._termine)
                return
            evenement = donnees.decoder_ligne(ligne)
            if evenement['type'] == 'fin':
                self._fin_evenement = evenement
            sur_evenement(evenement)
            self._lire(flux, sur_evenement)
        flux.read_line_async(GLib.PRIORITY_DEFAULT, None, recu)

    def _termine(self, processus, resultat):
        try:
            processus.wait_finish(resultat)
            code = processus.get_exit_status() if processus.get_if_exited() else -1
        except GLib.Error:
            code = -1
        fin, evenement = self._fin, self._fin_evenement
        self.processus, self._fin, self._fin_evenement = None, None, None
        if fin:
            fin(code, evenement)

    def arreter(self):
        if self.processus:
            self.processus.force_exit()


def en_arriere(travail, rappel):
    """Exécute travail() dans un fil et rend (resultat, erreur) à rappel dans la boucle principale."""
    def fil():
        try:
            resultat, erreur = travail(), None
        except Exception as e:  # noqa: BLE001 : l'interface affiche l'erreur, elle ne plante pas
            resultat, erreur = None, e
        GLib.idle_add(lambda: rappel(resultat, erreur) and False)
    threading.Thread(target=fil, daemon=True).start()


def fermer_session(rappel=None):
    """Ferme la session GNOME (déconnexion) par D-Bus : org.gnome.SessionManager.Logout(0), sans confirmation.
    Repli : gnome-session-quit --logout --no-prompt. rappel(message_erreur) si les deux échouent."""
    def repli():
        try:
            Gio.Subprocess.new(['gnome-session-quit', '--logout', '--no-prompt'], Gio.SubprocessFlags.NONE)
        except GLib.Error as erreur:
            if rappel:
                rappel(erreur.message)

    def fini(source, resultat):
        try:
            source.call_finish(resultat)
        except GLib.Error:
            repli()

    def connecte(source, resultat):
        try:
            connexion = Gio.bus_get_finish(resultat)
        except GLib.Error:
            repli()
            return
        connexion.call('org.gnome.SessionManager', '/org/gnome/SessionManager', 'org.gnome.SessionManager',
                       'Logout', GLib.Variant('(u)', (0,)), None, Gio.DBusCallFlags.NONE, -1, None, fini)
    Gio.bus_get(Gio.BusType.SESSION, None, connecte)
