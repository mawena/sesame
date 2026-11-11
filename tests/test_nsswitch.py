"""Édition de nsswitch.conf."""
import unittest

from sesame import nsswitch as ns

ORIGINE = """# /etc/nsswitch.conf
passwd:         files systemd sss
group:          files systemd sss
shadow:         files sss
netgroup:       nis sss
sudoers:        files sss
hosts:          files dns   # sss ici ne compte pas
"""


class TestNsswitch(unittest.TestCase):
    def test_retrait_de_sss(self):
        t = ns.retirer_service(ORIGINE, ns.BASES_SSS, "sss")
        self.assertIn("passwd:         files systemd\n", t)
        self.assertIn("shadow:         files\n", t)
        self.assertIn("netgroup:       nis\n", t)
        self.assertIn("sudoers:        files\n", t)
        self.assertIn("hosts:          files dns   # sss ici ne compte pas", t)
        self.assertFalse(ns.contient(t, "sss"))

    def test_retrait_idempotent(self):
        une = ns.retirer_service(ORIGINE, ns.BASES_SSS, "sss")
        self.assertEqual(ns.retirer_service(une, ns.BASES_SSS, "sss"), une)

    def test_retrait_ne_touche_pas_un_nom_proche(self):
        t = "passwd: files sss-extra mysss\n"
        self.assertEqual(ns.retirer_service(t, ns.BASES_SSS, "sss"), t)

    def test_ajout_d_authd(self):
        t = ns.ajouter_service("passwd: files systemd\ngroup: files\nshadow: files\nhosts: files dns\n",
                               ns.BASES_AUTHD, "authd")
        self.assertEqual(t, "passwd: files systemd authd\ngroup: files authd\nshadow: files authd\nhosts: files dns\n")

    def test_ajout_idempotent(self):
        une = ns.ajouter_service(ORIGINE, ns.BASES_AUTHD, "authd")
        self.assertEqual(ns.ajouter_service(une, ns.BASES_AUTHD, "authd"), une)
        self.assertEqual(une.count("authd"), 3)

    def test_ajout_avant_commentaire(self):
        t = ns.ajouter_service("passwd: files # note\n", ns.BASES_AUTHD, "authd")
        self.assertEqual(t, "passwd: files authd # note\n")

    def test_manque_et_service_de(self):
        t = "passwd: files authd\ngroup: files\n"
        self.assertEqual(ns.manque(t, "authd"), ["group"])
        self.assertEqual(ns.service_de(t, "passwd"), ["files", "authd"])
        self.assertEqual(ns.service_de(t, "hosts"), [])

    def test_contient(self):
        self.assertTrue(ns.contient(ORIGINE, "sss"))
        self.assertFalse(ns.contient("hosts: sss\n", "sss"))
