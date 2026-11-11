"""Protocole de sesame-racine : root obligatoire, JSON ligne par ligne, codes de sortie, sous-commandes."""
import io
import json
import os
import subprocess
import sys
from pathlib import Path

from sesame import chemins, himmelblau, racine
from sesame.version import VERSION
from tests.commun import A, DOSSIER_COMPIL, EMPREINTE, N, NOM, PAQUETS_DIR, Base

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

    def test_chaque_evenement_a_un_texte(self):
        _, evts = self.evenements("sauvegarde")
        for e in evts[:-1]:
            self.assertIsInstance(e["texte"], str)
        self.assertEqual(set(evts[-1]), {"type", "ok", "message"})

    def test_echec_code_1_et_fin_ok_faux(self):
        self.ecrire("/etc/os-release", 'VERSION_ID="22.04"\n')
        self.fabriquer_debs()
        code, evts = self.evenements("installer", "--paquets", PAQUETS_DIR)
        self.assertEqual(code, 1)
        self.assertFalse(evts[-1]["ok"])
        self.assertIn("24.04", evts[-1]["message"])

    def test_erreur_inattendue_donne_quand_meme_fin(self):
        self.m.lire = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boum"))
        code, evts = self.evenements("sauvegarde")
        self.assertEqual(code, 1)
        self.assertEqual(evts[-1]["type"], "fin")
        self.assertIn("boum", evts[-1]["message"])

    def test_usage_code_2(self):
        for argv in ([], ["inconnue"], ["reprise"], ["annuler-reprise"], ["configurer"], ["nom-machine"],
                     ["rejoindre"], ["rejoindre", "--compte", N], ["rejoindre", "--nom-machine", NOM], ["installer"], ["depot"],
                     ["configurer", "--locataire", "x", "--client", "y", "--compte", "z"]):
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
        self.assertEqual([e["id"] for e in etat["etapes"]],
                         ["sauvegarde", "secours", "nom_machine", "quitter_ad", "outils", "compiler", "installer",
                          "configurer", "premiere_connexion"])
        self.assertNotIn("derniere_reprise", etat)
        self.assertEqual(evts[-1]["type"], "fin")
        self.assertEqual(self.m.modifiantes(), [])


class TestSousCommandes(BaseRacine):
    def test_secours_lit_le_mot_de_passe_sur_stdin(self):
        code, evts = self.evenements("secours", "--nom", "depannage", entree="mot-de-passe-9\n")
        self.assertEqual(code, 0, evts)
        self.assertEqual(self.m.mots_de_passe, {"depannage": "mot-de-passe-9"})
        self.assertNotIn("mot-de-passe-9", json.dumps(evts))

    def test_secours_vide_copie_le_mot_de_passe_actuel(self):
        self.peupler(secours=False)
        self.m.env["PKEXEC_UID"] = "1000"
        code, evts = self.evenements("secours", entree="\n")
        self.assertEqual(code, 0, evts)
        self.assertEqual(self.m.empreintes["secours"], EMPREINTE)
        self.assertNotIn(EMPREINTE, json.dumps(evts))

    def test_secours_sans_stdin_copie_aussi(self):
        self.peupler(secours=False)
        code, evts = self.evenements("secours", entree="")
        self.assertEqual(code, 0, evts)
        self.assertEqual(self.m.empreintes["secours"], EMPREINTE)

    def test_nom_machine(self):
        code, evts = self.evenements("nom-machine", "--nom", NOM)
        self.assertEqual(code, 0, evts)
        self.assertEqual(self.lire("/etc/hostname"), NOM + "\n")
        code, evts = self.evenements("nom-machine", "--nom=-mauvais")
        self.assertEqual(code, 1)
        self.assertIn("invalide", evts[-1]["message"])

    def test_outils(self):
        code, evts = self.evenements("outils")
        self.assertEqual(code, 0, evts)
        textes = [e["texte"] for e in evts if e["type"] == "commande"]
        self.assertTrue(any(t.startswith("apt-get install -y -o Dpkg::Options::=--force-confdef")
                            and t.endswith("podman uidmap git make") for t in textes), textes)
        self.assertTrue(any(t.startswith("usermod --add-subuids") for t in textes))

    def test_installer(self):
        self.fabriquer_debs()
        code, evts = self.evenements("installer", "--paquets", PAQUETS_DIR)
        self.assertEqual(code, 0, evts)
        textes = [e["texte"] for e in evts if e["type"] == "commande"]
        self.assertTrue(any(t.startswith("apt-get install -y ") and t.endswith("nss-himmelblau_4.0.1_amd64.deb")
                            for t in textes), textes)
        self.assertLessEqual({e["type"] for e in evts}, {"etape", "commande", "sortie", "avertissement", "fin"})

    def test_installer_dossier_absent(self):
        code, evts = self.evenements("installer", "--paquets", "/nulle/part")
        self.assertEqual(code, 1)
        self.assertIn("n'existe pas", evts[-1]["message"])

    def test_configurer(self):
        self.installer_himmelblau(lier=False)
        code, evts = self.evenements("configurer", "--compte", N, "--compte-local", A)
        self.assertEqual(code, 0, evts)
        self.assertEqual(self.lire(himmelblau.USER_MAP), f"{A}:{N}\n")

    def test_configurer_sans_installation(self):
        code, evts = self.evenements("configurer", "--compte", N)
        self.assertEqual(code, 1)
        self.assertIn("installé", evts[-1]["message"])

    def test_quitter_ad(self):
        self.m.domaines_joints = ["cofinacorp.com"]
        self.assertEqual(self.evenements("quitter-ad")[0], 0)
        self.assertEqual(self.m.domaines_joints, [])

    def test_noter_premiere_connexion_et_desactiver(self):
        self.assertEqual(self.evenements("noter-premiere-connexion")[0], 0)
        self.config()
        self.installer_himmelblau()
        self.assertEqual(self.evenements("desactiver")[0], 0)
        self.assertEqual(self.lire(himmelblau.USER_MAP), "")

    def test_rejoindre_demande_la_compilation(self):
        code, evts = self.evenements("rejoindre", "--compte", N, "--nom-machine", NOM)
        self.assertEqual(code, 0, evts)
        self.assertEqual(evts[-1]["message"], "Préparation terminée : Himmelblau doit maintenant être compilé.")
        requis = [e for e in evts if e["type"] == "compilation_requise"]
        self.assertEqual(requis, [{"type": "compilation_requise", "texte": ""}])
        self.assertEqual(evts[-2], requis[0])  # juste avant la fin
        self.assertFalse(self.existe(himmelblau.USER_MAP))

    def test_rejoindre_avec_paquets(self):
        self.fabriquer_debs()
        code, evts = self.evenements("rejoindre", "--compte", N, "--nom-machine", NOM, "--paquets", PAQUETS_DIR)
        self.assertEqual(code, 0, evts)
        self.assertIn(f"Le poste {NOM} est prêt.", evts[-1]["message"])
        self.assertEqual(self.lire(himmelblau.USER_MAP), f"{A}:{N}\n")
        self.assertFalse(any(e["type"] == "compilation_requise" for e in evts))
        self.assertIn(f"dossier = {DOSSIER_COMPIL}", self.lire(chemins.SESAME_CONF))

    def test_rejoindre_texte_lisible_pour_compilation_requise(self):
        code, sortie, _ = self.lancer("rejoindre", "--compte", N, "--nom-machine", NOM)
        self.assertEqual(code, 0)
        self.assertIn("Compilation requise", sortie)

    def test_rejoindre_nom_de_machine_invalide(self):
        code, evts = self.evenements("rejoindre", "--compte", N, "--nom-machine", "12345")
        self.assertEqual(code, 1)
        self.assertEqual(self.m.modifiantes(), [])

    def test_plus_de_jeton_ni_de_depot(self):
        for argv in (["rejoindre", "--compte", N, "--nom-machine", NOM, "--jeton", "x"], ["depot"]):
            self.assertEqual(self.lancer(*argv)[0], 2)


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
