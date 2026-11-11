"""Détection de chaque statut de chaque étape."""
from sesame import chemins, etapes, etat, reprise, sauvegarde
from tests.commun import A, N, NU, U, H, Base


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

    def test_installer(self):
        self.m.snaps.clear()
        self.assertEqual(self.statut("installer"), "a_faire")
        self.assertIn("module", self.detecte("installer")[1])
        self.m.snaps.add("authd-msentraid")
        self.m.paquets.clear()
        self.assertEqual(self.statut("installer"), "a_faire")
        self.m.paquets.add("authd")
        self.assertEqual(self.statut("installer"), "fait")

    def test_installer_ubuntu_trop_ancien(self):
        self.ecrire("/etc/os-release", 'VERSION_ID="22.04"\n')
        self.assertEqual(self.statut("installer"), "bloquee")

    def test_configurer(self):
        self.assertEqual(self.statut("configurer"), "a_faire")  # le module n'est pas déclaré
        self.ecrire(chemins.BROKER_AUTHD, "[x]\n")
        self.assertEqual(self.statut("configurer"), "fait")
        self.m.actifs.discard(chemins.SERVICE_BROKER)
        self.assertEqual(self.statut("configurer"), "a_faire")
        self.m.actifs.add(chemins.SERVICE_BROKER)
        self.ecrire(chemins.SESAME_CONF, "[entra]\nlocataire = non\n")
        self.assertEqual(self.statut("configurer"), "a_faire")

    def test_premiere_connexion(self):
        self.ecrire(chemins.NSSWITCH, "passwd: files systemd authd\n")
        self.assertEqual(self.statut("premiere_connexion"), "fait")
        del self.m.entra[N]
        self.assertEqual(self.statut("premiere_connexion"), "a_faire")
        self.c.compte = ""
        self.assertEqual(self.statut("premiere_connexion"), "a_faire")

    def test_premiere_connexion_exige_authd_dans_nsswitch(self):
        self.assertEqual(self.statut("premiere_connexion"), "a_faire")

    def test_premiere_connexion_refuse_un_compte_local(self):
        self.ecrire(chemins.NSSWITCH, "passwd: files authd\n")
        self.ecrire("/etc/passwd", self.lire("/etc/passwd") + f"{N}:x:5000:5000::/home/x:/bin/sh\n")
        self.assertEqual(self.statut("premiere_connexion"), "a_faire")

    def test_reprise(self):
        self.assertEqual(self.statut("reprise"), "a_faire")
        reprise.programmer(self.m, self.parametres())
        self.assertEqual(self.statut("reprise"), "programmee")
        self.m.supprimer(chemins.REPRISE_PROGRAMMEE)
        self.assertTrue(reprise.reprendre(self.m, self.parametres(), "maintenant")[0])
        self.assertEqual(self.statut("reprise"), "fait")

    def test_reprise_interrompue(self):
        self.ecrire(chemins.REPRISE_ETAT, "{}")
        statut, detail = self.detecte("reprise")
        self.assertEqual(statut, "a_faire")
        self.assertIn("annuler-reprise", detail)

    def test_verification(self):
        self.assertEqual(self.statut("verification"), "a_faire")
        etat.noter(self.m, "verification", {"date": "x"})
        self.assertEqual(self.statut("verification"), "fait")


class TestEnsemble(BaseEtapes):
    def test_forme_des_elements(self):
        liste = etapes.lire_etat(self.m)
        self.assertEqual([e["id"] for e in liste], [e.id for e in etapes.ETAPES])
        self.assertEqual([e.id for e in etapes.ETAPES], ["sauvegarde", "secours", "quitter_ad", "installer", "configurer",
                                                          "premiere_connexion", "reprise", "verification"])
        for e in liste:
            self.assertEqual(set(e), {"id", "titre", "statut", "detail", "explication", "action"})
            self.assertIn(e["statut"], {"a_faire", "fait", "sans_objet", "programmee", "bloquee", "inconnu"})
        self.assertEqual({e["id"]: e["action"] for e in liste}["premiere_connexion"], None)
        self.assertEqual({e["id"]: e["action"] for e in liste}["quitter_ad"], "quitter-ad")

    def test_etapes_bloquees_disent_pourquoi(self):
        e = self.lire_etat()
        self.assertEqual(e["sauvegarde"]["statut"], "a_faire")
        self.assertEqual(e["secours"]["statut"], "fait")  # fait reste fait
        self.assertEqual(e["reprise"]["statut"], "bloquee")
        self.assertIn("Première connexion par Entra", e["reprise"]["detail"])
        self.assertEqual(e["verification"]["statut"], "bloquee")

    def test_sans_objet_ne_bloque_pas(self):
        sauvegarde.faire(self.m, A)
        e = self.lire_etat()
        self.assertEqual(e["quitter_ad"]["statut"], "sans_objet")
        self.m.snaps.clear()
        self.assertEqual(self.lire_etat()["installer"]["statut"], "a_faire")

    def test_etape_suivante(self):
        liste = etapes.lire_etat(self.m)
        self.assertEqual(etapes.etape_suivante(liste), "sauvegarde")
        sauvegarde.faire(self.m, A)
        self.assertEqual(etapes.etape_suivante(etapes.lire_etat(self.m)), "configurer")
        self.assertIsNone(etapes.etape_suivante([{"statut": "fait"}, {"statut": "sans_objet"}, {"statut": "bloquee"}]))
        self.assertEqual(etapes.etape_suivante([{"id": "x", "statut": "programmee"}]), "x")

    def test_tout_en_place(self):
        sauvegarde.faire(self.m, A)
        self.ecrire(chemins.BROKER_AUTHD, "x")
        self.ecrire(chemins.NSSWITCH, "passwd: files authd\n")
        self.m.actifs.add(chemins.SERVICE_BROKER)
        self.assertTrue(reprise.reprendre(self.m, self.parametres(), "maintenant")[0])
        etat.noter(self.m, "verification", {"date": "x"})
        liste = etapes.lire_etat(self.m)
        self.assertIsNone(etapes.etape_suivante(liste), liste)

    def test_la_detection_ne_plante_jamais(self):
        def casse(*a, **k):
            raise OSError("disque en panne")
        self.m.lancer = casse
        self.m.lire = casse
        liste = etapes.lire_etat(self.m)
        self.assertEqual(len(liste), 8)
        self.assertEqual({e["statut"] for e in liste}, {"inconnu"})
        self.assertIn("disque en panne", liste[0]["detail"])

    def test_une_etape_qui_plante_est_inconnue(self):
        def casse(systeme, c):
            raise ValueError("boum")
        d = dict(etapes.DETECTIONS, installer=casse)
        ancien, etapes.DETECTIONS = etapes.DETECTIONS, d
        self.addCleanup(setattr, etapes, "DETECTIONS", ancien)
        e = self.lire_etat()
        self.assertEqual(e["installer"]["statut"], "inconnu")
        self.assertIn("boum", e["installer"]["detail"])
        self.assertNotEqual(e["sauvegarde"]["statut"], "inconnu")

    def test_sans_sesame_conf_les_defauts_servent(self):
        self.m.supprimer(chemins.SESAME_CONF)
        self.m.uid = U
        self.assertEqual(etapes._config(self.m).compte_local, A)
        self.assertEqual(self.lire_etat()["premiere_connexion"]["statut"], "bloquee")

    def test_etat_complet_et_derniere_reprise(self):
        self.assertIsNone(etapes.derniere_reprise(self.m))
        self.assertTrue(reprise.reprendre(self.m, self.parametres(), "maintenant")[0])
        donnees = etapes.etat_complet(self.m)
        self.assertEqual(donnees["version"], "1.0.0")
        self.assertTrue(donnees["derniere_reprise"]["ok"])
        self.assertEqual(len(donnees["etapes"]), 8)
        self.assertIn("suivante", donnees)
