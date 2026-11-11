"""Détection de chaque statut de chaque étape."""
import json

from sesame import chemins, etapes, etat, himmelblau, sauvegarde
from sesame.version import VERSION
from tests.commun import A, DOSSIER_COMPIL, N, NOM, Base


class BaseEtapes(Base):
    def setUp(self):
        super().setUp()
        self.peupler()
        self.c = self.config()

    def detecte(self, id_):
        return etapes.DETECTIONS[id_](self.m, self.c)

    def statut(self, id_):
        return self.detecte(id_)[0]

    def lire_etat(self):
        return {e["id"]: e for e in etapes.lire_etat(self.m)}


class TestStatuts(BaseEtapes):
    def test_sauvegarde(self):
        self.assertEqual(self.statut("sauvegarde"), "a_faire")
        sauvegarde.faire(self.m, A)
        self.assertEqual(self.statut("sauvegarde"), "fait")

    def test_secours(self):
        self.ecrire("/etc/passwd", self.lire("/etc/passwd").replace("secours:", "autre:"))
        self.assertEqual(self.statut("secours"), "a_faire")
        self.peupler()
        self.ecrire("/etc/group", self.lire("/etc/group").replace(",secours", ""))
        self.assertEqual(self.statut("secours"), "a_faire")
        self.peupler()
        self.assertEqual(self.statut("secours"), "fait")

    def test_nom_machine(self):
        statut, detail = self.detecte("nom_machine")
        self.assertEqual(statut, "a_faire")
        self.assertIn("ubuntu-pc", detail)
        self.ecrire("/etc/hostname", NOM + "\n")
        self.assertEqual(self.statut("nom_machine"), "fait")
        self.ecrire("/etc/hostname", NOM + ".exemple.com\n")  # domaine ignoré
        self.assertEqual(self.statut("nom_machine"), "fait")
        self.c.nom_machine = ""  # sesame.conf sans nom
        self.assertEqual(self.statut("nom_machine"), "a_faire")

    def test_quitter_ad(self):
        self.assertEqual(self.statut("quitter_ad"), "sans_objet")
        self.m.domaines_joints = ["cofinacorp.com"]
        self.assertEqual(self.statut("quitter_ad"), "a_faire")
        self.m.domaines_joints = []
        self.ecrire(chemins.NSSWITCH, "passwd: files sss\n")
        self.assertEqual(self.statut("quitter_ad"), "a_faire")
        self.ecrire(chemins.NSSWITCH, "passwd: files\n")
        etat.noter(self.m, "quitter_ad", {"date": "x"})
        self.assertEqual(self.statut("quitter_ad"), "fait")

    def test_outils(self):
        statut, detail = self.detecte("outils")
        self.assertEqual(statut, "a_faire")
        self.assertIn("podman", detail)
        self.m.paquets.update({"podman", "uidmap", "git"})
        self.assertIn("make", self.detecte("outils")[1])
        self.m.paquets.add("make")
        self.assertEqual(self.statut("outils"), "fait")

    def marque_compilation(self, paquets=("himmelblau", "pam-himmelblau", "nss-himmelblau"), dossier=DOSSIER_COMPIL):
        self.ecrire(f"{dossier}/packaging/sesame-compilation.json",
                    json.dumps({"commit": "abc", "date": "x", "paquets": list(paquets)}))
        self.c.dossier_compilation = dossier

    def test_compiler(self):
        self.assertEqual(self.statut("compiler"), "a_faire")
        self.marque_compilation(("himmelblau", "pam-himmelblau"))
        self.assertEqual(self.statut("compiler"), "a_faire")  # un paquet manque
        self.marque_compilation()
        self.assertEqual(self.statut("compiler"), "fait")
        self.marque_compilation(("himmelblau_4.0.1_amd64.deb", "pam-himmelblau_4.0.1_amd64.deb",
                                 "nss-himmelblau_4.0.1_amd64.deb"))
        self.assertEqual(self.statut("compiler"), "fait")
        self.c.dossier_compilation = "/ailleurs"
        self.assertEqual(self.statut("compiler"), "a_faire")

    def test_compiler_fait_si_himmelblau_est_installe(self):
        self.installer_himmelblau()
        statut, detail = self.detecte("compiler")
        self.assertEqual(statut, "fait")
        self.assertIn("déjà installé", detail)

    def test_installer(self):
        statut, detail = self.detecte("installer")
        self.assertEqual(statut, "a_faire")
        self.assertIn("himmelblau, pam-himmelblau, nss-himmelblau", detail)
        self.m.paquets.update({"himmelblau", "pam-himmelblau"})
        self.assertIn("nss-himmelblau", self.detecte("installer")[1])
        self.assertEqual(self.statut("installer"), "a_faire")
        self.m.paquets.add("nss-himmelblau")
        statut, detail = self.detecte("installer")
        self.assertEqual(statut, "fait")
        self.assertIn("4.0.1", detail)

    def test_installer_ubuntu_trop_ancien(self):
        self.ecrire("/etc/os-release", 'VERSION_ID="22.04"\n')
        self.assertEqual(self.statut("installer"), "bloquee")

    def test_configurer(self):
        self.assertEqual(self.statut("configurer"), "a_faire")
        self.installer_himmelblau()
        self.assertEqual(self.statut("configurer"), "fait")
        self.m.actifs.discard("himmelblaud")
        statut, detail = self.detecte("configurer")
        self.assertEqual(statut, "a_faire")
        self.assertIn("himmelblaud", detail)
        self.m.actifs.add("himmelblaud")
        self.ecrire(himmelblau.USER_MAP, "autre:x@y.com\n")
        self.assertEqual(self.statut("configurer"), "a_faire")
        self.ecrire(himmelblau.USER_MAP, f"{A}:{N}\n")
        self.ecrire(himmelblau.CONFIG, "[global]\ndomain = a.com\n")
        self.assertEqual(self.statut("configurer"), "a_faire")

    def test_premiere_connexion(self):
        statut, detail = self.detecte("premiere_connexion")
        self.assertEqual(statut, "a_faire")
        self.assertIn(N, detail)
        etat.noter(self.m, "premiere_connexion", {"date": "x"})
        self.assertEqual(self.statut("premiere_connexion"), "fait")


class TestEnsemble(BaseEtapes):
    def test_ordre_et_identifiants(self):
        self.assertEqual([e.id for e in etapes.ETAPES],
                         ["sauvegarde", "secours", "nom_machine", "quitter_ad", "outils", "compiler", "installer",
                          "configurer", "premiere_connexion"])
        for e in etapes.ETAPES:
            self.assertTrue(e.titre and e.explication)
        self.assertEqual(etapes.PREREQUIS, {
            "secours": ["sauvegarde"], "nom_machine": ["sauvegarde"], "quitter_ad": ["sauvegarde", "secours"],
            "outils": ["sauvegarde"], "compiler": ["outils"], "installer": ["compiler", "quitter_ad"],
            "configurer": ["installer", "secours"],
            "premiere_connexion": ["configurer"]})

    def test_forme_des_elements(self):
        liste = etapes.lire_etat(self.m)
        self.assertEqual([e["id"] for e in liste], [e.id for e in etapes.ETAPES])
        for e in liste:
            self.assertLessEqual({"id", "titre", "explication", "statut", "detail"}, set(e))

    def test_blocage_par_prerequis(self):
        e = self.lire_etat()
        self.assertEqual(e["sauvegarde"]["statut"], "a_faire")
        self.assertEqual(e["secours"]["statut"], "fait")
        self.assertEqual(e["quitter_ad"]["statut"], "sans_objet")
        for id_ in ("nom_machine", "outils", "compiler", "installer", "configurer"):
            self.assertEqual(e[id_]["statut"], "bloquee", id_)
        self.assertIn("Sauvegarder la configuration", e["nom_machine"]["detail"])
        self.assertEqual(e["premiere_connexion"]["statut"], "bloquee")
        sauvegarde.faire(self.m, A)
        e = self.lire_etat()
        self.assertEqual(e["outils"]["statut"], "a_faire")
        self.assertEqual(e["compiler"]["statut"], "bloquee")
        self.assertIn("Installer les outils de compilation", e["compiler"]["detail"])

    def test_etape_suivante(self):
        self.assertEqual(etapes.etat_complet(self.m)["suivante"], "sauvegarde")
        sauvegarde.faire(self.m, A)
        self.assertEqual(etapes.etat_complet(self.m)["suivante"], "nom_machine")

    def test_tout_en_place(self):
        sauvegarde.faire(self.m, A)
        self.installer_himmelblau()
        self.installer_outils()
        self.ecrire("/etc/hostname", NOM + "\n")
        etat.noter(self.m, "premiere_connexion", {"date": "x"})
        d = etapes.etat_complet(self.m)
        self.assertEqual({e["id"]: e["statut"] for e in d["etapes"]},
                         {"sauvegarde": "fait", "secours": "fait", "nom_machine": "fait", "quitter_ad": "sans_objet",
                          "outils": "fait", "compiler": "fait", "installer": "fait", "configurer": "fait", "premiere_connexion": "fait"})
        self.assertIsNone(d["suivante"])

    def test_etat_complet_sans_derniere_reprise(self):
        d = etapes.etat_complet(self.m)
        self.assertEqual(set(d), {"version", "etapes", "suivante"})
        self.assertEqual(d["version"], VERSION)

    def test_la_detection_ne_plante_jamais(self):
        self.m.lancer = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boum"))
        liste = etapes.lire_etat(self.m)
        self.assertIn("inconnu", {e["statut"] for e in liste})
        self.assertTrue(all(isinstance(e["detail"], str) for e in liste))

    def test_detection_sans_root_ne_modifie_rien(self):
        etapes.etat_complet(self.m)
        self.assertEqual(self.m.modifiantes(), [])
