"""Systeme : fichiers sous la racine, NSS, /proc, commandes."""
import os
import tempfile
import unittest

from sesame.systeme import ErreurSesame, ErreurSysteme, Resultat, Systeme, lire_groupe, lire_utilisateur
from tests.commun import Base


class TestFichiers(Base):
    def test_tout_passe_par_la_racine(self):
        self.assertEqual(self.m.chemin("/etc/passwd"), self.m.racine / "etc/passwd")
        self.ecrire("/etc/x/y", "contenu")
        self.assertTrue((self.m.racine / "etc/x/y").is_file())
        self.assertEqual(self.lire("/etc/x/y"), "contenu")
        self.assertEqual(self.m.lire("/absent", "defaut"), "defaut")

    def test_modes_et_json(self):
        self.m.ecrire_json("/var/lib/sesame/secret", {"a": "é"}, 0o600)
        self.assertEqual(os.stat(self.m.chemin("/var/lib/sesame/secret")).st_mode & 0o777, 0o600)
        self.assertEqual(self.m.lire_json("/var/lib/sesame/secret"), {"a": "é"})
        self.ecrire("/x", "pas du json")
        self.assertEqual(self.m.lire_json("/x", "d"), "d")

    def test_deplacer_refuse_d_ecraser(self):
        self.ecrire("/a/f", "1")
        self.ecrire("/b/g", "2")
        with self.assertRaises(ErreurSesame):
            self.m.deplacer("/a", "/b")
        self.assertTrue(self.existe("/a/f"))
        self.m.deplacer("/a", "/c")
        self.assertEqual(self.lire("/c/f"), "1")

    def test_copier_supprimer(self):
        self.ecrire("/s/d/f", "1")
        self.m.copier("/s", "/t")
        self.assertEqual(self.lire("/t/d/f"), "1")
        self.m.supprimer("/t")
        self.m.supprimer("/t")
        self.assertFalse(self.existe("/t"))

    def test_processus_lus_dans_proc(self):
        self.ecrire("/proc/10/status", "Name:\tvim\nUid:\t1000\t1000\t1000\t1000\n")
        self.ecrire("/proc/11/status", "Name:\tsu\nUid:\t1000\t0\t0\t0\n")
        self.ecrire("/proc/12/status", "Name:\tcron\nUid:\t0\t0\t0\t0\n")
        self.ecrire("/proc/self/status", "Name:\tx\nUid:\t1000\t1000\t1000\t1000\n")
        self.assertEqual(self.m.processus_uid(1000), [(10, "vim"), (11, "su")])
        self.assertEqual(self.m.processus_uid(5), [])

    def test_lignes_passwd_group(self):
        self.assertEqual(lire_utilisateur("a:x:1:2::/h:/bin/sh").dossier, "/h")
        self.assertIsNone(lire_utilisateur("invalide"))
        self.assertEqual(lire_groupe("g:x:5:a,b").membres, ["a", "b"])
        self.assertIsNone(lire_groupe("g:x:z:"))

    def test_executer_leve_une_erreur(self):
        self.m.forces[("faux",)] = Resultat(3, "", "mauvais")
        with self.assertRaises(ErreurSysteme):
            self.m.executer(["faux"])
        self.assertEqual(self.m.executer(["faux"], tolerant=True).code, 3)

    def test_evenements(self):
        self.m.recepteur = lambda t, x: self.m.evenements.append((t, x))
        self.m.forces[("cmd", "a")] = Resultat(0, "ligne 1\n\nligne 2", "")
        self.m.executer(["cmd", "a"])
        self.assertEqual(self.m.evenements, [("commande", "cmd a"), ("sortie", "ligne 1"), ("sortie", "ligne 2")])


class TestCommandesReelles(unittest.TestCase):
    """La vraie méthode `lancer`, avec des commandes sans effet."""

    def setUp(self):
        self.s = Systeme(tempfile.mkdtemp())

    def test_sortie_code_et_stdin(self):
        r = self.s.lancer(["sh", "-c", "echo bonjour; echo erreur >&2; exit 3"])
        self.assertEqual((r.code, r.sortie, r.erreur), (3, "bonjour", "erreur"))
        self.assertEqual(self.s.lancer(["cat"], entree="vu\n").sortie, "vu")

    def test_commande_absente(self):
        self.assertEqual(self.s.lancer(["commande-qui-n-existe-pas"]).code, 127)

    def test_diffusion(self):
        vus = []
        self.s.recepteur = lambda t, x: vus.append((t, x))
        self.s.executer(["sh", "-c", "echo a; echo b"])
        self.assertEqual(vus, [("commande", "sh -c echo a; echo b"), ("sortie", "a"), ("sortie", "b")])

    def test_getent_reel(self):
        self.assertEqual(self.s.utilisateur("root").uid, 0)
        self.assertIsNone(self.s.utilisateur("compte-qui-n-existe-pas-xyz"))
