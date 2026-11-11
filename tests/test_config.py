"""Réglages : validation, sesame.conf, valeurs par défaut, broker.conf."""
from sesame import chemins, config as cfg
from tests.commun import A, CLIENT, H, LOCATAIRE, N, U, Base


class TestValidation(Base):
    def test_guid(self):
        self.assertTrue(cfg.valider_guid(LOCATAIRE))
        self.assertTrue(cfg.valider_guid("AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE"))
        for faux in ("", None, "1234", LOCATAIRE + "0", LOCATAIRE[:-1] + "g", " " + LOCATAIRE, LOCATAIRE.replace("-", "")):
            self.assertFalse(cfg.valider_guid(faux), faux)

    def test_upn(self):
        for bon in (N, "A.B@exemple.fr", "a_b-c@sous.domaine.org", " x@y.com "):
            self.assertTrue(cfg.valider_upn(bon), bon)
        for faux in ("", None, "sans-arobase", "a@b", "a b@c.com", "a@@c.com", "@c.com", "a@c.", "a;b@c.com"):
            self.assertFalse(cfg.valider_upn(faux), faux)

    def test_normaliser_upn(self):
        self.assertEqual(cfg.normaliser_upn("  Charles.Gamligo@CofinaCorp.com "), N)

    def test_valider_nom(self):
        self.assertTrue(cfg.valider_nom("secours"))
        self.assertTrue(cfg.valider_nom("charles-gamligo"))
        for faux in ("", "Majuscule", "a b", "1abc", "a;b", "x" * 40):
            self.assertFalse(cfg.valider_nom(faux), faux)


class TestFichier(Base):
    def test_ecrire_et_charger(self):
        c = cfg.Config(LOCATAIRE, CLIENT, "Charles.Gamligo@Cofinacorp.com", A, U, U, H, "secours", ["sudo", "docker"])
        cfg.ecrire(self.m, c)
        texte = self.lire(chemins.SESAME_CONF)
        for ligne in (f"locataire = {LOCATAIRE}", f"client = {CLIENT}", f"compte = {N}", f"compte = {A}", "uid = 1000",
                      f"dossier = {H}", "secours = secours", "supplementaires = sudo,docker", "[entra]", "[local]",
                      "[groupes]"):
            self.assertIn(ligne, texte)
        self.assertEqual(oct(self.m.chemin(chemins.SESAME_CONF).stat().st_mode & 0o777), "0o644")
        charge = cfg.charger(self.m)
        self.assertEqual(charge.compte, N)
        self.assertEqual((charge.uid, charge.gid, charge.dossier), (U, U, H))
        self.assertEqual(charge.groupes, ["sudo", "docker"])

    def test_charger_commentaires_en_fin_de_ligne(self):
        self.ecrire(chemins.SESAME_CONF, f"[entra]\nlocataire = {LOCATAIRE}   ; ID\ncompte = X@Y.com\n[groupes]\n"
                                         "supplementaires = a, b ,\n")
        c = cfg.charger(self.m)
        self.assertEqual(c.locataire, LOCATAIRE)
        self.assertEqual(c.compte, "x@y.com")
        self.assertEqual(c.groupes, ["a", "b"])
        self.assertEqual(c.secours, "secours")

    def test_charger_absent_ou_casse(self):
        self.assertIsNone(cfg.charger(self.m))
        self.ecrire(chemins.SESAME_CONF, "pas un ini")
        self.assertIsNone(cfg.charger(self.m))


class TestBroker(Base):
    def test_texte_broker(self):
        c = cfg.Config(LOCATAIRE, CLIENT, N.upper(), A, U, U, H, "secours", ["sudo", "docker"])
        self.assertEqual(cfg.texte_broker(c), (
            "# Module Microsoft Entra ID pour authd — écrit par Sésame. Original : broker.conf.origine\n"
            "[oidc]\n"
            f"issuer = https://login.microsoftonline.com/{LOCATAIRE}/v2.0\n"
            f"client_id = {CLIENT}\n\n"
            "[users]\nallowed_users = OWNER\n"
            f"owner = {N}\n"
            "home_base_dir = /home\nowner_extra_groups = sudo,docker\n\n"
            "[msentraid]\nregister_device = true\n\n"
            "[flows]\ndevice_code = true\nentra_auth = true\n"))

    def test_texte_broker_code(self):
        c = cfg.Config(LOCATAIRE, CLIENT, N, A, U, U, H, "secours", [], cfg.CODE)
        self.assertTrue(cfg.texte_broker(c).endswith(
            "[msentraid]\nregister_device = false\n\n[flows]\ndevice_code = true\nentra_auth = false\n"))


class TestConnexion(Base):
    def test_valider(self):
        self.assertEqual(cfg.Config().connexion, cfg.MOT_DE_PASSE)
        for bon in ("mot-de-passe", "code"):
            self.assertTrue(cfg.valider_connexion(bon))
        for faux in ("", None, "Code", "windows"):
            self.assertFalse(cfg.valider_connexion(faux), faux)

    def test_sesame_conf(self):
        c = cfg.Config(LOCATAIRE, CLIENT, N, A, U, U, H, "secours", [], cfg.CODE)
        cfg.ecrire(self.m, c)
        self.assertIn("connexion = code\n", self.lire(chemins.SESAME_CONF))
        self.assertEqual(cfg.charger(self.m).connexion, cfg.CODE)

    def test_sesame_conf_1_0_ou_valeur_inconnue(self):
        for valeur in ("", "connexion = windows\n"):
            self.ecrire(chemins.SESAME_CONF, f"[entra]\nlocataire = {LOCATAIRE}\n{valeur}")
            self.assertEqual(cfg.charger(self.m).connexion, cfg.MOT_DE_PASSE, valeur)

    def test_version(self):
        self.assertEqual(cfg.version("0.7.1~24.04"), (0, 7, 1))
        self.assertEqual(cfg.version("0.5.0+git3"), (0, 5, 0))
        self.assertEqual(cfg.version("1.2"), (1, 2, 0))
        for faux in ("", None, "v1", "abc"):
            self.assertIsNone(cfg.version(faux), faux)
        self.assertEqual(cfg.texte_version((0, 7, 0)), "0.7.0")
        self.assertEqual(cfg.texte_version(None), "?")

    def test_versions_installees(self):
        self.m.paquets.add("authd")
        self.m.snaps.add("authd-msentraid")
        self.assertEqual(cfg.versions_installees(self.m), {"authd": (0, 7, 1), "module": (0, 5, 0)})
        self.m.paquets.clear()
        self.m.snaps.clear()
        self.assertEqual(cfg.versions_installees(self.m), {"authd": None, "module": None})

    def test_trop_anciens(self):
        self.assertEqual(cfg.trop_anciens({"authd": (0, 7, 0), "module": (0, 5, 0)}), "")
        self.assertEqual(cfg.trop_anciens({"authd": (1, 0, 0), "module": (0, 6, 2)}), "")
        texte = cfg.trop_anciens({"authd": (0, 6, 3), "module": None})
        self.assertIn("authd 0.6.3 (il faut 0.7.0)", texte)
        self.assertIn("le module Entra ? (il faut 0.5.0)", texte)


class TestDefauts(Base):
    def setUp(self):
        super().setUp()
        self.peupler()

    def test_compte_courant(self):
        self.m.uid = U
        d = cfg.defauts(self.m)
        self.assertEqual((d.compte_local, d.uid, d.gid, d.dossier), (A, U, U, H))
        self.assertEqual(d.secours, "secours")

    def test_groupes_supplementaires_existants(self):
        self.m.uid = U
        d = cfg.defauts(self.m)
        self.assertEqual(sorted(d.groupes), ["docker", "lpadmin", "sudo"])
        self.assertNotIn(A, d.groupes)

    def test_pkexec_uid_et_sudo_user(self):
        self.m.env["PKEXEC_UID"] = str(U)
        self.assertEqual(cfg.defauts(self.m).compte_local, A)
        self.m.env = {"SUDO_USER": A}
        self.assertEqual(cfg.defauts(self.m).compte_local, A)

    def test_repli_premier_compte_ordinaire(self):
        d = cfg.defauts(self.m)  # l'UID 4242 n'existe pas
        self.assertEqual(d.compte_local, A)  # root (UID 0) et secours (1001) : A a le plus petit UID >= 1000

    def test_aucun_compte(self):
        self.ecrire("/etc/passwd", "root:x:0:0::/root:/bin/bash\n")
        self.assertEqual(cfg.defauts(self.m), cfg.Config())

    def test_upn_suggere_avec_domaine(self):
        self.m.domaines_joints = ["cofinacorp.com"]
        self.assertEqual(cfg.defauts(self.m).compte, "charles.gamligo@cofinacorp.com")

    def test_upn_vide_sans_domaine(self):
        self.assertEqual(cfg.defauts(self.m).compte, "")
