"""Réglages : validations, écriture, lecture (dont sesame.conf de la 1.x) et valeurs détectées."""
from sesame import chemins, config as cfg
from tests.commun import A, DOSSIER_COMPIL, G, H, N, NOM, U, Base


class TestValidations(Base):
    def test_upn(self):
        self.assertTrue(cfg.valider_upn(N))
        self.assertTrue(cfg.valider_upn("  Prenom.Nom@Entreprise.COM "))
        for faux in ("", None, "sans-arobase", "a@b", "a b@c.com", "a@@c.com"):
            self.assertFalse(cfg.valider_upn(faux), faux)
        self.assertEqual(cfg.normaliser_upn("  A.B@X.Com "), "a.b@x.com")

    def test_nom_de_compte(self):
        self.assertTrue(cfg.valider_nom("secours"))
        self.assertFalse(cfg.valider_nom("Secours"))
        self.assertFalse(cfg.valider_nom("1abc"))

    def test_nom_de_machine(self):
        for bon in ("PC", "pc-charles", "A1", "a" * 15, "Poste-42", "1a"):
            self.assertTrue(cfg.valider_nom_machine(bon), bon)
        for faux in ("", None, "-pc", "pc-", "a" * 16, "12345", "pc_1", "pc.local", "pc 1", "é", "pc\n"):
            self.assertFalse(cfg.valider_nom_machine(faux), faux)


class TestFichier(Base):
    def test_aller_retour(self):
        c = cfg.Config(N, A, U, G, H, "secours", NOM, DOSSIER_COMPIL)
        cfg.ecrire(self.m, c)
        self.assertEqual(cfg.charger(self.m), c)
        self.assertNotIn("authd", self.lire(chemins.SESAME_CONF))

    def test_absent_ou_illisible(self):
        self.assertIsNone(cfg.charger(self.m))
        self.ecrire(chemins.SESAME_CONF, "pas un ini")
        self.assertIsNone(cfg.charger(self.m))

    def test_lit_un_sesame_conf_1x_en_ignorant_les_cles_inconnues(self):
        self.ecrire(chemins.SESAME_CONF, f"""# Réglages de Sésame 1.1.0
[entra]
locataire = 11111111-2222-3333-4444-555555555555
client = aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee
compte = {N.upper()}
connexion = mot-de-passe

[local]
compte = {A}
uid = {U}
gid = {G}
dossier = {H}
secours = secours

[groupes]
supplementaires = sudo,docker
""")
        c = cfg.charger(self.m)
        self.assertEqual((c.compte, c.compte_local, c.uid, c.gid, c.dossier, c.secours, c.nom_machine, c.dossier_compilation),
                         (N, A, U, G, H, "secours", "", ""))

    def test_valeurs_manquantes(self):
        self.ecrire(chemins.SESAME_CONF, "[local]\nuid = abc\n")
        c = cfg.charger(self.m)
        self.assertEqual((c.compte, c.uid, c.secours, c.nom_machine), ("", 0, "secours", ""))


class TestDefauts(Base):
    def setUp(self):
        super().setUp()
        self.peupler()

    def test_premier_compte_ordinaire(self):
        d = cfg.defauts(self.m)
        self.assertEqual((d.compte_local, d.uid, d.gid, d.dossier), (A, U, G, H))
        self.assertEqual(d.compte, "")

    def test_compte_de_l_appelant(self):
        self.ecrire("/etc/passwd", self.lire("/etc/passwd") + "autre:x:1002:1002::/home/autre:/bin/bash\n")
        self.m.env["PKEXEC_UID"] = "1002"
        self.assertEqual(cfg.defauts(self.m).compte_local, "autre")

    def test_adresse_suggeree_depuis_le_domaine_ad(self):
        self.m.domaines_joints = ["Acmecorp.com"]
        self.assertEqual(cfg.defauts(self.m).compte, "charles.gamligo@acmecorp.com")
