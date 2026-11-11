"""Contrôles de vérification, sans root."""
import os

from sesame import chemins, etat, reprise, verification
from tests.commun import A, N, U, H, Base


class TestVerification(Base):
    def setUp(self):
        super().setUp()
        self.peupler()
        self.c = self.config()
        self.m.actifs.add(chemins.SERVICE_BROKER)

    def apres_reprise(self):
        self.m.env["PKEXEC_UID"] = "1001"
        self.assertTrue(reprise.reprendre(self.m, self.parametres(), "maintenant")[0])
        self.ecrire("/etc/group", f"sudo:x:27:secours,{N}\ndocker:x:999:{N}\n")

    def resultats(self):
        return dict((t, ok) for ok, t in verification.controler(self.m, self.c))

    def test_pas_configure(self):
        self.assertEqual(verification.controler(self.m, None)[0][0], False)

    def test_hors_session_entra_ne_controle_que_la_configuration(self):
        self.apres_reprise()
        res = verification.controler(self.m, self.c)
        self.assertIn("pas connecté", res[0][1])
        self.assertTrue(all(ok for ok, _ in res), res)
        self.assertFalse(any("$HOME" in t for _, t in res))
        self.assertFalse(verification.est_connecte(self.m, self.c))

    def test_ancien_compte_encore_la(self):
        res = self.resultats()
        self.assertFalse(res[f"L'ancien compte {A} n'existe plus"])

    def test_services_inactifs(self):
        self.apres_reprise()
        self.m.actifs.discard("authd")
        res = self.resultats()
        self.assertFalse(res["Le service authd est actif"])
        self.assertTrue(res["Le service du module Entra est actif"])

    def test_compte_de_secours(self):
        self.apres_reprise()
        self.ecrire("/etc/group", f"sudo:x:27:{N}\ndocker:x:999:{N}\n")
        self.assertFalse(self.resultats()["Le compte de secours secours existe et est administrateur"])

    def test_groupes_manquants(self):
        self.apres_reprise()
        self.ecrire("/etc/group", f"sudo:x:27:secours\ndocker:x:999:{N}\n")
        res = self.resultats()
        self.assertFalse(res[f"{N} fait partie du groupe sudo"])
        self.assertTrue(res[f"{N} fait partie du groupe docker"])

    def test_unite_modifiee_inactive(self):
        self.apres_reprise()
        self.m.actifs.discard("app.service")
        self.assertFalse(self.resultats()["L'unité app.service est active"])
        self.m.actives.discard("app.service")
        self.assertNotIn("L'unité app.service est active", self.resultats())

    def test_crontab(self):
        self.apres_reprise()
        self.m.uid, self.m.env["HOME"] = U, H
        self.assertTrue(self.resultats()["Une crontab existe, comme avant la reprise"])
        self.m.crontabs.clear()
        self.assertFalse(self.resultats()["Une crontab existe, comme avant la reprise"])

    def test_session_du_compte_entra(self):
        self.apres_reprise()
        self.m.uid = U
        self.m.env["HOME"] = H
        # getent de l'UID 1000 renvoie maintenant le compte Entra
        self.assertTrue(verification.est_connecte(self.m, self.c))
        res = self.resultats()
        self.assertTrue(res[f"Le compte Entra a l'UID {U} (actuel : {U})"])
        self.assertTrue(res[f"$HOME vaut {H} (actuel : {H})"])
        self.assertEqual(res[f"{H} appartient à l'UID {U}"], os.stat(self.m.chemin(H)).st_uid == U)

    def test_session_mauvais_home(self):
        self.apres_reprise()
        self.m.uid = U
        self.m.env["HOME"] = "/home/autre"
        self.assertFalse(self.resultats()[f"$HOME vaut {H} (actuel : /home/autre)"])
