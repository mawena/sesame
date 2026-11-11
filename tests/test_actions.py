"""Actions root : sauvegarde, secours, nom de la machine, AD, dépôt, installation, configuration, rejoindre."""
import json
import os

from sesame import actions, chemins, config as cfg, etat, himmelblau
from sesame.systeme import ErreurSesame
from tests.commun import A, DOSSIER_COMPIL, EMPREINTE, N, NOM, PAQUETS_DIR, Base


class BaseActions(Base):
    def setUp(self):
        super().setUp()
        self.peupler()
        self.m.recepteur = self.m.ecrit

    def textes(self):
        return [t for _, t in self.m.evenements]

    def sorties_apt(self):
        return [a for a in self.m.appels if a[0] == "apt-get"]


class TestSauvegarde(BaseActions):
    def test_contenu(self):
        self.installer_himmelblau()
        self.ecrire("/etc/hostname", "x\n")
        message = actions.faire_sauvegarde(self.m, "essai")
        dossier = etat.derniere_sauvegarde(self.m)["chemin"]
        self.assertIn(dossier, message)
        for chemin in ("/etc/passwd", "/etc/pam.d/common-auth", "/etc/hosts", "/etc/hostname",
                       himmelblau.CONFIG, himmelblau.USER_MAP):
            self.assertTrue(self.existe(dossier + chemin), chemin)
        self.assertEqual(oct(os.stat(self.m.chemin(dossier)).st_mode & 0o777), "0o700")

    def test_himmelblau_conf_sauvegarde_si_present(self):
        self.ecrire(himmelblau.CONFIG, "[global]\nx = 1\n")
        actions.faire_sauvegarde(self.m)
        dossier = etat.derniere_sauvegarde(self.m)["chemin"]
        self.assertEqual(self.lire(dossier + himmelblau.CONFIG), "[global]\nx = 1\n")


class TestSecours(BaseActions):
    def setUp(self):
        super().setUp()
        self.peupler(secours=False)

    def test_copie_de_l_empreinte(self):
        msg = actions.creer_secours(self.m, "secours", copier_de=A)
        self.assertIn("secours", msg)
        self.assertIn(["chpasswd", "-e"], self.m.appels)
        self.assertEqual(self.m.empreintes["secours"], EMPREINTE)
        self.assertIn("secours", self.m.groupes_locaux()["sudo"].membres)
        self.assertFalse(any(EMPREINTE in " ".join(a) for a in self.m.appels))
        self.assertEqual(cfg.charger(self.m).secours, "secours")

    def test_mot_de_passe_choisi(self):
        actions.creer_secours(self.m, "depannage", "mot-de-passe-9")
        self.assertEqual(self.m.mots_de_passe, {"depannage": "mot-de-passe-9"})
        self.assertNotIn("mot-de-passe-9", " ".join(" ".join(a) for a in self.m.appels))

    def test_empreinte_inutilisable(self):
        for mauvaise in ("!", "*", "", "!$6$x"):
            self.ecrire("/etc/shadow", f"{A}:{mauvaise}:19000:0:99999:7:::\n")
            with self.assertRaises(ErreurSesame) as e:
                actions.creer_secours(self.m, "secours", copier_de=A)
            self.assertIn("mot de passe utilisable", str(e.exception))
        self.assertEqual(self.m.modifiantes(), [])

    def test_sans_mot_de_passe_ni_modele(self):
        with self.assertRaises(ErreurSesame):
            actions.creer_secours(self.m, "secours")
        with self.assertRaises(ErreurSesame):
            actions.creer_secours(self.m, "secours", copier_de="inconnu")
        with self.assertRaises(ErreurSesame):
            actions.creer_secours(self.m, "Mauvais Nom", "mot-de-passe-9")
        with self.assertRaises(ErreurSesame):
            actions.creer_secours(self.m, "secours", "court")

    def test_compte_existant_repare_sans_toucher_au_mot_de_passe(self):
        self.peupler()
        self.ecrire("/etc/group", self.lire("/etc/group").replace(",secours", ""))
        actions.creer_secours(self.m, "secours", copier_de=A)
        self.assertIn("secours", self.m.groupes_locaux()["sudo"].membres)
        self.assertNotIn(["chpasswd", "-e"], self.m.appels)
        self.assertEqual(self.m.empreintes, {})


class TestNomMachine(BaseActions):
    def test_changement(self):
        msg = actions.changer_nom_machine(self.m, NOM)
        self.assertIn(NOM, msg)
        self.assertEqual(self.lire("/etc/hostname"), NOM + "\n")
        self.assertIn(["hostnamectl", "hostname", NOM], self.m.appels)
        self.assertEqual(self.lire("/etc/hosts"), f"127.0.0.1\tlocalhost\n127.0.1.1\t{NOM}\n::1\tip6-localhost\n")
        self.assertEqual(cfg.charger(self.m).nom_machine, NOM)

    def test_ligne_hosts_ajoutee_apres_localhost(self):
        self.ecrire("/etc/hosts", "127.0.0.1 localhost\n::1 ip6\n")
        actions.changer_nom_machine(self.m, "Poste-1")
        self.assertEqual(self.lire("/etc/hosts"), "127.0.0.1 localhost\n127.0.1.1\tPoste-1\n::1 ip6\n")

    def test_deja_a_ce_nom(self):
        self.ecrire("/etc/hostname", NOM + "\n")
        self.assertIn("déjà", actions.changer_nom_machine(self.m, NOM))
        self.assertEqual(self.m.modifiantes(), [])
        self.assertEqual(cfg.charger(self.m).nom_machine, NOM)

    def test_invalide(self):
        for faux in ("", "-pc", "pc-", "a" * 16, "12345", "pc_1"):
            with self.assertRaises(ErreurSesame):
                actions.changer_nom_machine(self.m, faux)
        self.assertEqual(self.m.modifiantes(), [])


class TestQuitterAd(BaseActions):
    def test_quitte_le_domaine(self):
        self.m.domaines_joints = ["cofinacorp.com"]
        self.ecrire(chemins.NSSWITCH, "passwd: files sss\ngroup: files sss\n")
        actions.quitter_ad(self.m)
        self.assertEqual(self.m.domaines_joints, [])
        self.assertIn(["realm", "leave", "-v", "cofinacorp.com"], self.m.appels)
        self.assertNotIn("sss", self.lire(chemins.NSSWITCH))
        self.assertIn("quitter_ad", etat.lire(self.m))


class TestOutils(BaseActions):
    def test_installation_et_plage(self):
        msg = actions.installer_outils(self.m, A)
        self.assertIn("outils", msg)
        self.assertIn(["apt-get", "install", "-y", "podman", "uidmap", "git", "make"], self.m.appels)
        self.assertIn(["usermod", "--add-subuids", "100000-165535", "--add-subgids", "100000-165535", A],
                      self.m.appels)
        self.assertTrue(set(himmelblau.OUTILS) <= self.m.paquets)

    def test_plage_deja_presente(self):
        self.installer_outils()
        actions.installer_outils(self.m, A)
        self.assertFalse(any(a[0] == "usermod" for a in self.m.appels))

    def test_une_seule_des_deux_plages(self):
        self.ecrire("/etc/subuid", f"{A}:100000:65536\n")
        actions.installer_outils(self.m, A)
        self.assertTrue(any(a[0] == "usermod" for a in self.m.appels))

    def test_compte_local_par_defaut_et_inconnu(self):
        actions.installer_outils(self.m)
        self.assertIn(A, self.m.appels[-1])
        with self.assertRaises(ErreurSesame):
            actions.installer_outils(self.m, "inconnu")

    def test_echec_du_reseau(self):
        self.m.panne_a = 0
        with self.assertRaises(ErreurSesame) as e:
            actions.installer_outils(self.m, A)
        self.assertIn("a échoué", str(e.exception))


class TestInstaller(BaseActions):
    def test_installation(self):
        self.fabriquer_debs()
        msg = actions.installer(self.m, PAQUETS_DIR)
        self.assertEqual(msg, "Himmelblau 4.0.1 est installé.")
        self.assertEqual(self.m.paquets, set(himmelblau.PAQUETS))
        self.assertEqual(self.sorties_apt(), [["apt-get", "install", "-y"] + [
            f"{PAQUETS_DIR}/{p}_4.0.1_amd64.deb" for p in himmelblau.PAQUETS]])
        self.assertIn(["dpkg-deb", "-f", f"{PAQUETS_DIR}/himmelblau_4.0.1_amd64.deb", "Package"], self.m.appels)
        self.assertIn("installer", etat.lire(self.m))

    def test_dossier_inexistant(self):
        with self.assertRaises(ErreurSesame) as e:
            actions.installer(self.m, PAQUETS_DIR)
        self.assertIn("n'existe pas", str(e.exception))
        with self.assertRaises(ErreurSesame):
            actions.installer(self.m, "")
        self.assertEqual(self.m.modifiantes(), [])

    def test_paquet_manquant(self):
        self.fabriquer_debs(noms=["himmelblau", "pam-himmelblau"])
        with self.assertRaises(ErreurSesame) as e:
            actions.installer(self.m, PAQUETS_DIR)
        self.assertIn("nss-himmelblau", str(e.exception))
        self.assertEqual(self.m.modifiantes(), [])

    def test_fichier_qui_n_est_pas_le_bon_paquet(self):
        self.fabriquer_debs()
        self.ecrire(f"{PAQUETS_DIR}/nss-himmelblau_4.0.1_amd64.deb", "autre-paquet\n")
        with self.assertRaises(ErreurSesame) as e:
            actions.installer(self.m, PAQUETS_DIR)
        self.assertIn("n'est pas le paquet nss-himmelblau", str(e.exception))
        self.assertEqual(self.m.modifiantes(), [])

    def test_ubuntu_trop_ancien(self):
        self.fabriquer_debs()
        self.ecrire("/etc/os-release", 'VERSION_ID="22.04"\n')
        with self.assertRaises(ErreurSesame):
            actions.installer(self.m, PAQUETS_DIR)

    def test_apparmor_present(self):
        self.fabriquer_debs(noms=himmelblau.PAQUETS + ["himmelblau-apparmor"])
        self.ecrire("/sys/module/apparmor/version", "3\n")
        actions.installer(self.m, PAQUETS_DIR)
        self.assertIn(["apt-get", "install", "-y", f"{PAQUETS_DIR}/himmelblau-apparmor_4.0.1_amd64.deb"],
                      self.m.appels)
        self.assertIn("himmelblau-apparmor", self.m.paquets)

    def test_apparmor_non_construit_ou_absent(self):
        self.fabriquer_debs(noms=himmelblau.PAQUETS + ["himmelblau-apparmor"])
        actions.installer(self.m, PAQUETS_DIR)  # AppArmor absent du poste
        self.assertNotIn("himmelblau-apparmor", self.m.paquets)
        self.ecrire("/sys/module/apparmor/version", "3\n")
        self.m.paquets.clear()
        self.m.supprimer(f"{PAQUETS_DIR}/himmelblau-apparmor_4.0.1_amd64.deb")
        actions.installer(self.m, PAQUETS_DIR)  # AppArmor présent mais paquet non construit
        self.assertNotIn("himmelblau-apparmor", self.m.paquets)

    def test_apparmor_echec_tolere(self):
        self.fabriquer_debs(noms=himmelblau.PAQUETS + ["himmelblau-apparmor"])
        self.ecrire("/sys/module/apparmor/version", "3\n")
        self.m.apparmor_echoue = True
        actions.installer(self.m, PAQUETS_DIR)
        self.assertIn("avertissement", [t for t, _ in self.m.evenements])

    def test_echec_de_l_installation(self):
        self.fabriquer_debs()
        self.m.panne_a = 0
        with self.assertRaises(ErreurSesame) as e:
            actions.installer(self.m, PAQUETS_DIR)
        self.assertIn("a échoué", str(e.exception))
        self.assertIn("Relancer", str(e.exception))


class TestConfigurer(BaseActions):
    def setUp(self):
        super().setUp()
        self.installer_himmelblau(lier=False)

    def test_configuration(self):
        msg = actions.configurer(self.m, N, A)
        self.assertIn(A, msg)
        conf = self.lire(himmelblau.CONFIG)
        self.assertEqual(himmelblau.lire_config(conf, "domain"), "cofinacorp.com")
        self.assertEqual(himmelblau.lire_config(conf, "user_map_file"), himmelblau.USER_MAP)
        self.assertEqual(self.lire(himmelblau.USER_MAP), f"{A}:{N}\n")
        self.assertIn(["systemctl", "enable", "--now", "himmelblaud", "himmelblaud-tasks"], self.m.appels)
        self.assertIn(["systemctl", "restart", "himmelblaud", "himmelblaud-tasks"], self.m.appels)
        self.assertTrue(self.m.service_actif("himmelblaud"))
        c = cfg.charger(self.m)
        self.assertEqual((c.compte, c.compte_local, c.uid, c.dossier), (N, A, 1000, "/home/" + A))
        self.assertNotIn("avertissement", [t for t, _ in self.m.evenements])
        self.assertIn("configurer", etat.lire(self.m))

    def test_himmelblau_conf_existant_preserve(self):
        self.ecrire(himmelblau.CONFIG, "[global]\nlog_level = debug\ndomain = vieux.fr\n[autre]\nx = 1\n")
        actions.configurer(self.m, N, A)
        conf = self.lire(himmelblau.CONFIG)
        self.assertIn("log_level = debug", conf)
        self.assertIn("[autre]\nx = 1", conf)
        self.assertNotIn("vieux.fr", conf)
        self.assertEqual(self.lire(himmelblau.CONFIG + ".sesame-origine"),
                         "[global]\nlog_level = debug\ndomain = vieux.fr\n[autre]\nx = 1\n")
        actions.configurer(self.m, N, A)  # la copie d'origine n'est pas écrasée
        self.assertIn("vieux.fr", self.lire(himmelblau.CONFIG + ".sesame-origine"))

    def test_pas_de_copie_si_pas_de_fichier(self):
        actions.configurer(self.m, N, A)
        self.assertFalse(self.existe(himmelblau.CONFIG + ".sesame-origine"))

    def test_user_map_remplace_la_ligne_du_compte(self):
        self.ecrire(himmelblau.USER_MAP, f"# liens\nautre:autre@x.com\n{A}:ancien@x.com\n")
        actions.configurer(self.m, N, A)
        self.assertEqual(self.lire(himmelblau.USER_MAP), f"# liens\nautre:autre@x.com\n{A}:{N}\n")

    def test_adresse_en_majuscules_normalisee(self):
        actions.configurer(self.m, " Charles.Gamligo@CofinaCorp.com ", A)
        self.assertEqual(self.lire(himmelblau.USER_MAP), f"{A}:{N}\n")

    def test_compte_local_par_defaut(self):
        actions.configurer(self.m, N)
        self.assertEqual(himmelblau.lire_user_map(self.lire(himmelblau.USER_MAP)), {A: N})

    def test_compte_local_de_l_appelant(self):
        self.ecrire("/etc/passwd", self.lire("/etc/passwd") + "autre:x:1002:1002::/home/autre:/bin/bash\n")
        self.m.env["PKEXEC_UID"] = "1002"
        actions.configurer(self.m, N)
        self.assertEqual(himmelblau.lire_user_map(self.lire(himmelblau.USER_MAP)), {"autre": N})

    def test_avertit_si_nss_ou_pam_manquent(self):
        self.ecrire(chemins.NSSWITCH, "passwd: files\ngroup: files\n")
        self.ecrire(chemins.PAM_COMMON_AUTH, "auth pam_unix.so\n")
        actions.configurer(self.m, N, A)
        avertissements = [t for ty, t in self.m.evenements if ty == "avertissement"]
        self.assertEqual(len(avertissements), 2)
        self.assertTrue(self.lire(himmelblau.USER_MAP))  # la configuration est écrite malgré tout

    def test_erreurs(self):
        for args in (("pas-une-adresse", A), (N, "inconnu")):
            with self.assertRaises(ErreurSesame):
                actions.configurer(self.m, *args)
        self.m.paquets.discard("nss-himmelblau")
        with self.assertRaises(ErreurSesame) as e:
            actions.configurer(self.m, N, A)
        self.assertIn("nss-himmelblau", str(e.exception))
        self.assertEqual(self.m.modifiantes(), [])
        self.assertFalse(self.existe(himmelblau.USER_MAP))


class TestRejoindre(BaseActions):
    def evenements_de(self, type_):
        return [t for ty, t in self.m.evenements if ty == type_]

    def etapes_vues(self):
        return self.evenements_de("etape")

    def test_preparation_sur_machine_vierge_avec_domaine_ad(self):
        self.peupler(secours=False)
        self.m.domaines_joints = ["cofinacorp.com"]
        self.ecrire(chemins.NSSWITCH, "passwd: files systemd sss\ngroup: files systemd sss\n")
        message = actions.rejoindre(self.m, N, NOM)
        self.assertEqual(message, "Préparation terminée : Himmelblau doit maintenant être compilé.")
        self.assertEqual(self.evenements_de("compilation_requise"), [""])
        self.assertTrue(etat.derniere_sauvegarde(self.m))
        self.assertIn("secours", self.m.groupes_locaux()["sudo"].membres)
        self.assertEqual(self.m.empreintes["secours"], EMPREINTE)
        self.assertEqual(self.lire("/etc/hostname"), NOM + "\n")
        self.assertEqual(self.m.domaines_joints, [])
        self.assertTrue(set(himmelblau.OUTILS) <= self.m.paquets)
        self.assertFalse(set(himmelblau.PAQUETS) & self.m.paquets)
        self.assertFalse(self.existe(himmelblau.USER_MAP))
        self.assertNotIn("rejoindre", etat.lire(self.m))
        self.assertEqual(cfg.charger(self.m).nom_machine, NOM)

    def test_dossier_attendu_dans_l_evenement_et_enregistre(self):
        self.peupler()
        actions.rejoindre(self.m, N, NOM, paquets=PAQUETS_DIR)  # dossier absent : compilation requise
        self.assertEqual(self.evenements_de("compilation_requise"), [PAQUETS_DIR])
        self.assertEqual(cfg.charger(self.m).dossier_compilation, DOSSIER_COMPIL)

    def test_dossier_incomplet_demande_la_compilation(self):
        self.peupler()
        self.fabriquer_debs(noms=["himmelblau", "pam-himmelblau"])
        message = actions.rejoindre(self.m, N, NOM, paquets=PAQUETS_DIR)
        self.assertIn("compilé", message)
        self.assertFalse(set(himmelblau.PAQUETS) & self.m.paquets)

    def test_rejoindre_complet_avec_les_paquets(self):
        self.peupler(secours=False)
        self.m.domaines_joints = ["cofinacorp.com"]
        self.fabriquer_debs()
        message = actions.rejoindre(self.m, N, NOM, paquets=PAQUETS_DIR)
        self.assertTrue(message.startswith(f"Le poste {NOM} est prêt. Déconnectez-vous, choisissez votre compte "
                                           "à l'écran d'accueil, tapez le mot de passe Entra de " + N))
        self.assertIn("code PIN (Windows Hello)", message)
        self.assertEqual(self.evenements_de("compilation_requise"), [])
        self.assertTrue(set(himmelblau.PAQUETS) <= self.m.paquets)
        self.assertEqual(self.lire(himmelblau.USER_MAP), f"{A}:{N}\n")
        self.assertTrue(self.m.service_actif("himmelblaud"))
        c = cfg.charger(self.m)
        self.assertEqual((c.compte, c.compte_local, c.secours, c.nom_machine, c.dossier_compilation),
                         (N, A, "secours", NOM, DOSSIER_COMPIL))
        self.assertFalse(any("déjà fait" in t for t in self.etapes_vues() if "domaine" not in t.lower()))
        self.assertIn("rejoindre", etat.lire(self.m))

    def test_ordre_des_commandes(self):
        self.peupler(secours=False)
        self.fabriquer_debs()
        actions.rejoindre(self.m, N, NOM, paquets=PAQUETS_DIR)
        noms = [" ".join(a[:2]) if a[0] in ("chpasswd", "apt-get") else a[0] for a in self.m.modifiantes()]
        dernier = len(noms) - 1 - noms[::-1].index("systemctl")
        ordre = [noms.index(x) for x in ("useradd", "chpasswd -e", "hostnamectl", "apt-get install")]
        ordre += [dernier]
        self.assertEqual(ordre, sorted(ordre))
        # les outils (premier apt-get) avant les paquets compilés (deuxième)
        apt = [a for a in self.m.modifiantes() if a[0] == "apt-get"]
        self.assertEqual(apt[0][3:], list(himmelblau.OUTILS))
        self.assertTrue(apt[1][3].endswith(".deb"))

    def test_relance_apres_compilation(self):
        self.peupler(secours=False)
        actions.rejoindre(self.m, N, NOM)
        n = len(self.m.modifiantes())
        self.m.evenements.clear()
        self.fabriquer_debs()
        actions.rejoindre(self.m, N, NOM, paquets=PAQUETS_DIR)
        vues = self.etapes_vues()
        for debut in ("Sauvegarde", "Compte de secours", "Nom de la machine", "Outils de compilation"):
            self.assertTrue(any(t.startswith(debut) and t.endswith("déjà fait") for t in vues), debut)
        self.assertFalse(any(a[0] in ("useradd", "hostnamectl") for a in self.m.modifiantes()[n:]))
        self.assertEqual(self.lire(himmelblau.USER_MAP), f"{A}:{N}\n")

    def test_relance_apres_echec_d_installation(self):
        self.peupler(secours=False)
        self.m.domaines_joints = ["cofinacorp.com"]
        self.fabriquer_debs()
        # commandes modifiantes : useradd, chpasswd -e, hostnamectl, realm leave, systemctl disable sssd,
        # pam-auth-update, apt-get outils (6), usermod subuids (7), apt-get install des .deb (8)
        self.m.panne_a = 8
        with self.assertRaises(ErreurSesame) as e:
            actions.rejoindre(self.m, N, NOM, paquets=PAQUETS_DIR)
        self.assertIn("a échoué", str(e.exception))
        self.assertFalse(set(himmelblau.PAQUETS) <= self.m.paquets)
        self.assertFalse(self.existe(himmelblau.USER_MAP))
        self.m.panne_a = None
        self.m.evenements.clear()
        n = len(self.m.modifiantes())
        actions.rejoindre(self.m, N, NOM, paquets=PAQUETS_DIR)
        vues = self.etapes_vues()
        self.assertTrue(any(t.startswith("Sauvegarde") and t.endswith("déjà fait") for t in vues))
        self.assertTrue(any(t.startswith("Outils") and t.endswith("déjà fait") for t in vues))
        self.assertFalse(any(t.startswith("Installation") and "déjà" in t for t in vues))
        self.assertFalse(any(a[0] in ("useradd", "usermod") for a in self.m.modifiantes()[n:]))
        self.assertEqual(sum(1 for a in self.m.modifiantes() if a[:2] == ["realm", "leave"]), 1)
        self.assertEqual(self.lire(himmelblau.USER_MAP), f"{A}:{N}\n")

    def test_deuxieme_passage_saute_tout(self):
        self.peupler(secours=False)
        self.fabriquer_debs()
        actions.rejoindre(self.m, N, NOM, paquets=PAQUETS_DIR)
        avant = len(self.m.modifiantes())
        self.m.evenements.clear()
        actions.rejoindre(self.m, N, NOM, paquets=PAQUETS_DIR)
        self.assertTrue(all("déjà fait" in t for t in self.etapes_vues()), self.etapes_vues())
        self.assertEqual(len(self.m.modifiantes()), avant)

    def verifie_rien_modifie(self, *args, **kw):
        with self.assertRaises(ErreurSesame):
            actions.rejoindre(self.m, *args, **kw)
        self.assertEqual(self.m.modifiantes(), [])
        self.assertFalse(self.existe(chemins.SESAME_CONF))
        self.assertFalse(self.existe(chemins.SAUVEGARDES))

    def test_validation_avant_toute_modification(self):
        self.peupler(secours=False)
        self.verifie_rien_modifie(N, "-mauvais")
        self.verifie_rien_modifie(N, "a" * 16)
        self.verifie_rien_modifie(N, "12345")
        self.verifie_rien_modifie("pas-une-adresse", NOM)
        self.verifie_rien_modifie(N, NOM, compte_local="inconnu")
        self.ecrire("/etc/shadow", f"{A}:!:19000:0:99999:7:::\n")  # mot de passe non copiable
        self.verifie_rien_modifie(N, NOM)
        self.ecrire("/etc/shadow", f"{A}:{EMPREINTE}:19000:0:99999:7:::\n")
        self.ecrire("/etc/os-release", 'VERSION_ID="22.04"\n')
        self.verifie_rien_modifie(N, NOM)
        self.assertEqual(self.lire("/etc/hostname"), "ubuntu-pc\n")

    def test_himmelblau_deja_installe_n_exige_pas_de_paquets(self):
        self.peupler()
        self.installer_himmelblau(lier=False)
        actions.rejoindre(self.m, N, NOM)
        self.assertEqual(self.evenements_de("compilation_requise"), [])
        self.assertEqual(self.lire(himmelblau.USER_MAP), f"{A}:{N}\n")
        self.assertFalse(any(a[:3] == ["apt-get", "install", "-y"] and a[3].endswith(".deb") for a in self.m.appels))

    def test_compte_local_choisi(self):
        self.peupler()
        self.installer_himmelblau(lier=False)
        self.ecrire("/etc/passwd", self.lire("/etc/passwd") + "autre:x:1002:1002::/home/autre:/bin/bash\n")
        actions.rejoindre(self.m, N, NOM, compte_local="autre")
        self.assertEqual(himmelblau.lire_user_map(self.lire(himmelblau.USER_MAP)), {"autre": N})

    def test_changement_d_adresse_refait_la_liaison(self):
        self.peupler()
        self.fabriquer_debs()
        actions.rejoindre(self.m, N, NOM, paquets=PAQUETS_DIR)
        actions.rejoindre(self.m, "autre.adresse@exemple.org", NOM, paquets=PAQUETS_DIR)
        self.assertEqual(self.lire(himmelblau.USER_MAP), f"{A}:autre.adresse@exemple.org\n")
        self.assertEqual(himmelblau.lire_config(self.lire(himmelblau.CONFIG), "domain"), "exemple.org")


class TestPremiereConnexionEtDesactiver(BaseActions):
    def test_noter(self):
        actions.noter_premiere_connexion(self.m)
        self.assertIn("date", etat.lire(self.m)["premiere_connexion"])

    def test_desactiver(self):
        self.config()
        self.installer_himmelblau()
        self.ecrire(himmelblau.USER_MAP, f"autre:a@x.com\n{A}:{N}\n")
        self.ecrire("/usr/share/pam-configs/himmelblau", "Name: Himmelblau\nAuth: pam_himmelblau.so\n")
        etat.noter(self.m, "configurer", {"date": "x"})
        msg = actions.desactiver(self.m)
        self.assertIn("rien n'est désinstallé", msg)
        self.assertEqual(self.lire(himmelblau.USER_MAP), "autre:a@x.com\n")
        self.assertIn(["pam-auth-update", "--disable", "himmelblau"], self.m.appels)
        self.assertIn(["systemctl", "disable", "--now", "himmelblaud", "himmelblaud-tasks"], self.m.appels)
        self.assertFalse(self.m.service_actif("himmelblaud"))
        self.assertTrue(set(himmelblau.PAQUETS) <= self.m.paquets)
        self.assertTrue(self.existe(himmelblau.CONFIG))
        self.assertNotIn("configurer", etat.lire(self.m))
        self.assertNotIn("pam_himmelblau", self.lire(chemins.PAM_COMMON_AUTH))

    def test_desactiver_puis_rejoindre_retablit_tout(self):
        self.peupler()
        self.fabriquer_debs()
        actions.rejoindre(self.m, N, NOM, paquets=PAQUETS_DIR)
        actions.desactiver(self.m)
        actions.rejoindre(self.m, N, NOM, paquets=PAQUETS_DIR)
        self.assertEqual(self.lire(himmelblau.USER_MAP), f"{A}:{N}\n")
        self.assertTrue(self.m.service_actif("himmelblaud"))
        self.assertIn("pam_himmelblau", self.lire(chemins.PAM_COMMON_AUTH))  # PAM rétabli
        self.assertIn(["pam-auth-update", "--enable", "himmelblau"], self.m.appels)
