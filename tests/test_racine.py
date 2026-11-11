"""Protocole de sesame-racine : root obligatoire, JSON ligne par ligne, codes de sortie."""
import io
import json
import os
import subprocess
import sys
from pathlib import Path

from sesame import chemins, racine
from tests.commun import A, CLIENT, LOCATAIRE, N, Base
from sesame.version import VERSION

DEPOT = Path(__file__).resolve().parent.parent


class BaseRacine(Base):
    def setUp(self):
        super().setUp()
        self.peupler()

    def lancer(self, *argv, entree=""):
        sortie, erreur = io.StringIO(), io.StringIO()
        code = racine.main(list(argv), self.m, sortie, erreur, io.StringIO(entree))
        return code, sortie.getvalue(), erreur.getvalue()

    def evenements(self, *argv, entree=""):
        code, sortie, _ = self.lancer("--json", *argv, entree=entree)
        return code, [json.loads(l) for l in sortie.splitlines()]


class TestProtocole(BaseRacine):
    def test_refuse_sans_root(self):
        self.m.root = False
        code, sortie, erreur = self.lancer("sauvegarde")
        self.assertEqual(code, 1)
        self.assertIn("root", erreur)
        self.assertEqual(self.m.appels, [])
        self.assertFalse(self.existe(chemins.SAUVEGARDES))

    def test_refuse_sans_root_en_json(self):
        self.m.root = False
        code, evts = self.evenements("etat")
        self.assertEqual(code, 1)
        self.assertEqual(evts[-1]["type"], "fin")
        self.assertFalse(evts[-1]["ok"])

    def test_json_une_ligne_par_evenement_et_fin_en_dernier(self):
        self.config()
        code, evts = self.evenements("sauvegarde", "--motif", "essai")
        self.assertEqual(code, 0)
        self.assertEqual([e["type"] for e in evts][-1], "fin")
        self.assertEqual([e["type"] for e in evts].count("fin"), 1)
        self.assertEqual(evts[0], {"type": "etape", "texte": "Sauvegarde de la configuration"})
        self.assertTrue(evts[-1]["ok"])
        self.assertIn("essai", evts[-1]["message"])

    def test_commandes_et_sorties(self):
        self.m.paquets.clear()
        self.m.snaps.clear()
        self.m.lancer_reel = self.m.lancer
        code, evts = self.evenements("installer")
        self.assertEqual(code, 0, evts)
        types = {e["type"] for e in evts}
        self.assertLessEqual(types, {"etape", "commande", "sortie", "avertissement", "fin"})
        textes = [e["texte"] for e in evts if e["type"] == "commande"]
        self.assertIn("apt-get update", textes)
        self.assertIn("snap install authd-msentraid", textes)

    def test_chaque_evenement_a_un_texte(self):
        _, evts = self.evenements("sauvegarde")
        for e in evts[:-1]:
            self.assertIsInstance(e["texte"], str)
        self.assertEqual(set(evts[-1]), {"type", "ok", "message"})

    def test_echec_code_1_et_fin_ok_faux(self):
        self.ecrire("/etc/os-release", 'VERSION_ID="22.04"\n')
        code, evts = self.evenements("installer")
        self.assertEqual(code, 1)
        self.assertFalse(evts[-1]["ok"])
        self.assertIn("24.04", evts[-1]["message"])
        self.assertEqual(evts[-1]["type"], "fin")

    def test_erreur_inattendue_donne_quand_meme_fin(self):
        self.m.lire = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boum"))
        code, evts = self.evenements("sauvegarde")
        self.assertEqual(code, 1)
        self.assertEqual(evts[-1]["type"], "fin")
        self.assertIn("boum", evts[-1]["message"])

    def test_usage_code_2(self):
        for argv in ([], ["inconnue"], ["reprise"], ["configurer"], ["reprise", "--maintenant", "--au-demarrage"],
                     ["configurer", "--locataire", "x"],
                     ["configurer", "--locataire", "x", "--client", "y", "--compte", "z", "--connexion", "windows"]):
            with self.subTest(argv=argv):
                code, _, erreur = self.lancer(*argv)
                self.assertEqual(code, 2)
                self.assertTrue(erreur)

    def test_usage_en_json_finit_par_fin(self):
        code, evts = self.evenements("inconnue")
        self.assertEqual(code, 2)
        self.assertEqual(evts[-1]["type"], "fin")
        self.assertFalse(evts[-1]["ok"])

    def test_texte_lisible_sans_json(self):
        code, sortie, _ = self.lancer("sauvegarde")
        self.assertEqual(code, 0)
        self.assertIn("== Sauvegarde de la configuration", sortie)
        self.assertNotIn("{", sortie)

    def test_etat(self):
        self.config()
        code, evts = self.evenements("etat")
        self.assertEqual(code, 0)
        etat = json.loads(evts[0]["texte"])
        self.assertEqual(etat["version"], VERSION)
        self.assertEqual(len(etat["etapes"]), 8)
        self.assertEqual(evts[-1]["type"], "fin")


class TestActions(BaseRacine):
    def test_secours_lit_le_mot_de_passe_sur_stdin(self):
        self.ecrire("/etc/passwd", "root:x:0:0::/root:/bin/bash\n")
        self.ecrire("/etc/group", "sudo:x:27:\n")
        code, evts = self.evenements("secours", "--nom", "depannage", entree="mot-de-passe-9\n")
        self.assertEqual(code, 0, evts)
        self.assertEqual(self.m.mots_de_passe, {"depannage": "mot-de-passe-9"})
        self.assertNotIn("mot-de-passe-9", json.dumps(evts))

    def test_secours_sans_mot_de_passe(self):
        self.ecrire("/etc/passwd", "root:x:0:0::/root:/bin/bash\n")
        code, evts = self.evenements("secours", entree="")
        self.assertEqual(code, 1)
        self.assertEqual(evts[-1]["type"], "fin")

    def test_configurer(self):
        self.ecrire(chemins.BROKER_MODELE, "[x]\n")
        code, evts = self.evenements("configurer", "--locataire", LOCATAIRE, "--client", CLIENT, "--compte", N,
                                     "--compte-local", A, "--groupes", "sudo,docker")
        self.assertEqual(code, 0, evts)
        self.assertIn(f"owner = {N}", self.lire(chemins.BROKER_CONF))
        self.assertIn("owner_extra_groups = sudo,docker", self.lire(chemins.BROKER_CONF))
        self.assertIn("entra_auth = true", self.lire(chemins.BROKER_CONF))

    def test_configurer_connexion_par_code(self):
        self.ecrire(chemins.BROKER_MODELE, "[x]\n")
        code, evts = self.evenements("configurer", "--locataire", LOCATAIRE, "--client", CLIENT, "--compte", N,
                                     "--compte-local", A, "--connexion", "code")
        self.assertEqual(code, 0, evts)
        self.assertIn("entra_auth = false", self.lire(chemins.BROKER_CONF))
        self.assertIn("code", evts[-1]["message"])

    def test_configurer_valeur_invalide(self):
        code, evts = self.evenements("configurer", "--locataire", "pas-un-guid", "--client", CLIENT, "--compte", N)
        self.assertEqual(code, 1)
        self.assertIn("locataire", evts[-1]["message"])

    def test_reprise_sans_configuration(self):
        code, evts = self.evenements("reprise", "--maintenant")
        self.assertEqual(code, 1)
        self.assertIn("pas configuré", evts[-1]["message"])

    def test_reprise_au_demarrage_puis_execution(self):
        self.config()
        code, evts = self.evenements("reprise", "--au-demarrage")
        self.assertEqual(code, 0, evts)
        self.assertTrue(self.existe(chemins.REPRISE_PROGRAMMEE))
        code, _ = self.evenements("reprise", "--execution-demarrage")
        self.assertEqual(code, 0)
        self.assertFalse(self.existe(chemins.REPRISE_PROGRAMMEE))
        self.assertEqual(self.m.entra[N]["uid"], 1000)

    def test_execution_demarrage_rend_toujours_0(self):
        code, evts = self.evenements("reprise", "--execution-demarrage")  # rien de programmé
        self.assertEqual(code, 0)
        self.assertFalse(evts[-1]["ok"])

    def test_reprise_maintenant_et_annulation(self):
        self.config()
        self.m.env["PKEXEC_UID"] = "1001"
        code, evts = self.evenements("reprise", "--maintenant")
        self.assertEqual(code, 0, evts)
        self.assertEqual(self.m.entra[N]["home"], "/home/" + A)
        self.assertEqual(self.evenements("annuler-reprise")[0], 1)  # plus rien à annuler

    def test_annuler_programmation(self):
        self.config()
        self.evenements("reprise", "--au-demarrage")
        code, _ = self.evenements("reprise", "--annuler-programmation")
        self.assertEqual(code, 0)
        self.assertFalse(self.existe(chemins.REPRISE_PROGRAMMEE))

    def test_noter_verification_et_desactiver(self):
        self.assertEqual(self.evenements("noter-verification")[0], 0)
        self.ecrire(chemins.BROKER_AUTHD, "x")
        self.assertEqual(self.evenements("desactiver")[0], 0)
        self.assertFalse(self.existe(chemins.BROKER_AUTHD))

    def test_quitter_ad(self):
        self.config()
        del self.m.entra[N]
        self.assertEqual(self.evenements("quitter-ad")[0], 0)


class TestLanceur(BaseRacine):
    """Le vrai lanceur, sans root : il refuse de tourner."""

    def test_lanceur_refuse_sans_root(self):
        if os.geteuid() == 0:
            self.skipTest("lancé en root")
        r = subprocess.run([sys.executable, str(DEPOT / "libexec" / "sesame-racine"), "--json", "etat"],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 1)
        ligne = json.loads(r.stdout.strip().splitlines()[-1])
        self.assertEqual((ligne["type"], ligne["ok"]), ("fin", False))

    def test_lanceur_usage(self):
        r = subprocess.run([sys.executable, str(DEPOT / "libexec" / "sesame-racine"), "nimporte"],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 2)

    def test_fichiers_executables(self):
        for chemin in ("bin/sesame", "libexec/sesame-racine"):
            self.assertTrue(os.access(DEPOT / chemin, os.X_OK), chemin)
            self.assertEqual((DEPOT / chemin).read_text().splitlines()[0], "#!/usr/bin/python3")
