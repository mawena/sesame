"""Contrôles de vérification, sans root."""
from sesame import chemins, himmelblau, verification
from tests.commun import A, N, NOM, Base


class TestVerification(Base):
    def setUp(self):
        super().setUp()
        self.peupler()
        self.installer_himmelblau()
        self.ecrire("/etc/hostname", NOM + "\n")
        self.c = self.config()

    def resultats(self):
        return dict((t, ok) for ok, t in verification.controler(self.m, self.c))

    def test_pas_configure(self):
        res = verification.controler(self.m, None)
        self.assertEqual(res, [(False, "Sésame n'est pas encore configuré")])

    def test_tout_est_en_place(self):
        res = verification.controler(self.m, self.c)
        self.assertTrue(all(ok for ok, _ in res), res)
        textes = " | ".join(t for _, t in res)
        for attendu in ("himmelblaud", "pour passwd", "pour group", "pam_himmelblau", "user-map", "aad-tool",
                        NOM, "secours", f"Le dossier de {N} mène à /home/{A}"):
            self.assertIn(attendu, textes)

    def test_service_arrete(self):
        self.m.actifs.discard("himmelblaud")
        res = self.resultats()
        self.assertFalse(res["Le service himmelblaud est actif"])
        self.assertFalse(res["aad-tool status répond"])

    def test_nss_manquant(self):
        self.ecrire(chemins.NSSWITCH, "passwd: files himmelblau\ngroup: files\n")
        res = self.resultats()
        self.assertTrue(res["nsswitch.conf consulte himmelblau pour passwd"])
        self.assertFalse(res["nsswitch.conf consulte himmelblau pour group"])

    def test_pam_manquant(self):
        self.ecrire(chemins.PAM_COMMON_AUTH, "auth pam_unix.so\n")
        self.assertFalse(self.resultats()["PAM utilise pam_himmelblau (common-auth)"])

    def test_user_map(self):
        self.ecrire(himmelblau.USER_MAP, "autre:x@y.com\n")
        self.assertFalse(self.resultats()[f"user-map : {A} est relié à {N}"])
        self.ecrire(himmelblau.USER_MAP, f"{A}:{N.upper()}\n")  # casse ignorée
        self.assertTrue(self.resultats()[f"user-map : {A} est relié à {N}"])

    def test_aad_tool_absent_n_est_pas_controle(self):
        self.m.aad_present = False
        self.assertFalse(any("aad-tool" in t for t in self.resultats()))

    def test_nom_de_la_machine(self):
        self.ecrire("/etc/hostname", "ubuntu-pc\n")
        res = [(ok, t) for ok, t in verification.controler(self.m, self.c) if "nom de la machine" in t]
        self.assertFalse(res[0][0])
        self.assertIn("ubuntu-pc", res[0][1])

    def test_secours(self):
        self.ecrire("/etc/group", self.lire("/etc/group").replace(",secours", ""))
        self.assertFalse([ok for ok, t in verification.controler(self.m, self.c) if "secours" in t][0])

    def test_ne_modifie_rien(self):
        verification.controler(self.m, self.c)
        self.assertEqual(self.m.modifiantes(), [])

    def test_est_connecte(self):
        self.m.uid = 1000
        self.assertTrue(verification.est_connecte(self.m, self.c))
        self.m.uid = 1001
        self.assertFalse(verification.est_connecte(self.m, self.c))

    def test_lien_du_dossier(self):
        self.m.supprimer(f"/home/{N}")
        self.assertFalse(self.resultats()[f"Le dossier de {N} mène à /home/{A}"])
