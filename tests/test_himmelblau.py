"""Fonctions pures de Himmelblau : paquets, himmelblau.conf, user-map."""
import unittest

from sesame import himmelblau as h



class TestPaquets(unittest.TestCase):
    def test_constantes(self):
        self.assertEqual(h.PAQUETS, ["himmelblau", "pam-himmelblau", "nss-himmelblau"])
        self.assertEqual(h.PAQUETS_OPTIONNELS, ("himmelblau-apparmor",))
        self.assertEqual(h.OUTILS, ("podman", "uidmap", "git", "make"))
        self.assertEqual(h.CONFIG, "/etc/himmelblau/himmelblau.conf")
        self.assertEqual(h.USER_MAP, "/etc/himmelblau/user-map")

    def test_debs_dans(self):
        noms = ["himmelblau_4.0.1_amd64.deb", "pam-himmelblau_4.0.1_amd64.deb", "nss-himmelblau_4.0.1_amd64.deb",
                "himmelblau-apparmor_4.0.1_amd64.deb", "himmelblau-sso_4.0.1_amd64.deb", "sesame-compilation.json"]
        d = h.debs_dans(noms)
        self.assertEqual(d, {"himmelblau": "himmelblau_4.0.1_amd64.deb",
                             "pam-himmelblau": "pam-himmelblau_4.0.1_amd64.deb",
                             "nss-himmelblau": "nss-himmelblau_4.0.1_amd64.deb",
                             "himmelblau-apparmor": "himmelblau-apparmor_4.0.1_amd64.deb"})

    def test_debs_dans_incomplet_et_versions(self):
        self.assertEqual(h.debs_dans(["himmelblau_1_amd64.deb", "himmelblau_2_amd64.deb"]),
                         {"himmelblau": "himmelblau_2_amd64.deb"})
        self.assertEqual(h.debs_dans([]), {})
        self.assertEqual(h.debs_dans(["himmelblau-sso_1_amd64.deb", "himmelblau.txt"]), {})

    def test_debs_dans_accepte_les_noms_de_paquets(self):
        self.assertEqual(sorted(h.debs_dans(["himmelblau", "pam-himmelblau", "nss-himmelblau"])), sorted(h.PAQUETS))


class TestDomaine(unittest.TestCase):
    def test_domaine(self):
        self.assertEqual(h.domaine("Charles.G@AcmeCorp.com"), "acmecorp.com")
        self.assertEqual(h.domaine("sans-arobase"), "")
        self.assertEqual(h.domaine(""), "")


class TestConfig(unittest.TestCase):
    def test_fichier_vide(self):
        self.assertEqual(h.texte_config("", "a.com", "/m"),
                         "[global]\ndomain = a.com\nuser_map_file = /m\nhome_attr = SPN\nhome_alias = UUID\n")

    def test_garde_le_reste_et_remplace(self):
        avant = "# note\n[global]\nlog_level = debug\ndomain = vieux.com\n# domain = commente\n\n[autre]\ndomain = x\n"
        t = h.texte_config(avant, "a.com", "/m")
        self.assertIn("log_level = debug\n", t)
        self.assertIn("domain = a.com\n", t)
        self.assertNotIn("vieux.com", t)
        self.assertIn("# domain = commente", t)
        self.assertIn("[autre]\ndomain = x\n", t)
        self.assertIn("user_map_file = /m\n", t)
        self.assertEqual(t.count("domain = a.com"), 1)

    def test_ne_confond_pas_domains(self):
        t = h.texte_config("[global]\ndomains = liste.com\n", "a.com", "/m")
        self.assertIn("domains = liste.com", t)
        self.assertIn("domain = a.com", t)

    def test_section_absente_ajoutee(self):
        t = h.texte_config("[autre]\nx = 1\n", "a.com", "/m")
        self.assertEqual(t, "[autre]\nx = 1\n\n[global]\ndomain = a.com\nuser_map_file = /m\nhome_attr = SPN\nhome_alias = UUID\n")

    def test_idempotent_et_lecture(self):
        une = h.texte_config("[global]\nlog_level = x\n", "a.com", "/m")
        self.assertEqual(h.texte_config(une, "a.com", "/m"), une)
        self.assertEqual(h.lire_config(une, "domain"), "a.com")
        self.assertEqual(h.lire_config(une, "absent"), "")
        self.assertEqual(h.lire_config(une, "domain", "autre"), "")


class TestDossier(unittest.TestCase):
    def test_reglages_du_dossier_ecrits_et_remplaces(self):
        t = h.texte_config("[global]\nhome_attr = UUID\nhome_alias = spn\nhome_prefix = /home/\n", "a.com", "/m")
        self.assertEqual(h.lire_config(t, "home_attr"), "SPN")
        self.assertEqual(h.lire_config(t, "home_alias"), "UUID")
        self.assertEqual(t.count("home_attr"), 1)
        self.assertTrue(h.dossier_bien_range(t))
        self.assertFalse(h.dossier_bien_range("[global]\ndomain = a.com\n"))
        self.assertTrue(h.dossier_bien_range("[global]\nhome_attr = spn\nhome_alias = uuid\n"))

    def test_dossier_de_l_adresse(self):
        self.assertEqual(h.dossier_adresse("", "a@b.com"), "/home/a@b.com")
        self.assertEqual(h.dossier_adresse("[global]\nhome_prefix = /srv/home/\n", "a@b.com"), "/srv/home/a@b.com")

    def test_cibles(self):
        self.assertEqual(h.cible_du_lien("/home/a@b.com", "a"), "/home/a")
        self.assertEqual(h.cible_du_lien("/home/a@b.com", "/srv/a"), "/srv/a")
        self.assertEqual(h.cible_a_ecrire("/home/a@b.com", "/home/a/"), "a")
        self.assertEqual(h.cible_a_ecrire("/home/a@b.com", "/srv/a"), "/srv/a")


class TestUserMap(unittest.TestCase):
    def test_ajout(self):
        self.assertEqual(h.texte_user_map("", "charles", "c@x.com"), "charles:c@x.com\n")
        self.assertEqual(h.texte_user_map("# note\nalice:a@x.com\n", "charles", "c@x.com"),
                         "# note\nalice:a@x.com\ncharles:c@x.com\n")

    def test_remplace_la_ligne_du_compte(self):
        t = h.texte_user_map("charles:vieux@x.com\nalice:a@x.com\ncharles:encore@x.com\n", "charles", "c@x.com")
        self.assertEqual(t, "charles:c@x.com\nalice:a@x.com\n")

    def test_retrait(self):
        t = h.retirer_user_map("# note\ncharles:c@x.com\nalice:a@x.com\n", "charles")
        self.assertEqual(t, "# note\nalice:a@x.com\n")
        self.assertEqual(h.retirer_user_map("charles:c@x.com\n", "charles"), "")

    def test_lecture(self):
        self.assertEqual(h.lire_user_map("# n\ncharles: c@x.com\nalice:a@x.com\nbizarre\n"),
                         {"charles": "c@x.com", "alice": "a@x.com"})
