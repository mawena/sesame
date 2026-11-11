"""Actions root : sauvegarde, secours, quitter-ad, installer, configurer, désactiver."""
import tarfile

from sesame import actions, chemins, config as cfg, etat, sauvegarde
from sesame.systeme import ErreurSesame, Resultat
from tests.commun import A, CLIENT, H, LOCATAIRE, N, U, Base


class TestSauvegarde(Base):
    def setUp(self):
        super().setUp()
        self.peupler()

    def test_contenu(self):
        dossier = sauvegarde.faire(self.m, A, "Mon Motif!")
        self.assertRegex(dossier, r"/var/lib/sesame/sauvegardes/\d{8}-\d{6}-mon-motif-$")
        self.assertEqual(oct(self.m.chemin(dossier).stat().st_mode & 0o777), "0o700")
        for chemin in ("/etc/passwd", "/etc/shadow", "/etc/group", "/etc/subuid", "/etc/nsswitch.conf", "/etc/login.defs",
                       "/etc/gdm3/custom.conf", "/etc/systemd/system/app.service",
                       "/etc/vmware/hostd/authorization.xml", f"/var/lib/AccountsService/users/{A}"):
            self.assertTrue(self.existe(dossier + chemin), chemin)
        self.assertFalse(self.existe(dossier + "/etc/sssd"))  # absent du poste : ignoré
        self.assertEqual(self.lire(f"{dossier}/crontab-{A}"), "0 2 * * * sauvegarde\n")
        self.assertEqual(oct(self.m.chemin(dossier + f"/crontab-{A}").stat().st_mode & 0o777), "0o600")
        self.assertEqual(etat.derniere_sauvegarde(self.m)["chemin"], dossier)

    def test_deux_sauvegardes_dans_la_meme_seconde(self):
        self.m.horodatage = lambda: "20261111-120000"
        un, deux = sauvegarde.faire(self.m, A), sauvegarde.faire(self.m, A)
        self.assertNotEqual(un, deux)
        self.assertEqual(len(etat.lire(self.m)["sauvegardes"]), 2)

    def test_action(self):
        self.config()
        self.assertIn("sauvegardée", actions.faire_sauvegarde(self.m))
        self.assertIsNotNone(etat.derniere_sauvegarde(self.m))


class TestSecours(Base):
    def setUp(self):
        super().setUp()
        self.peupler(secours=False)

    def test_creation(self):
        actions.creer_secours(self.m, "secours", "motdepasse1")
        useradd = next(a for a in self.m.appels if a[0] == "useradd")
        self.assertEqual(useradd, ["useradd", "-m", "-s", "/bin/bash", "-c", "Compte de secours (Sésame)", "-G", "sudo",
                                   "secours"])
        self.assertEqual(self.m.mots_de_passe["secours"], "motdepasse1")
        self.assertIn("secours", self.m.groupes_locaux()["sudo"].membres)

    def test_le_mot_de_passe_ne_figure_jamais_dans_les_commandes_ni_les_evenements(self):
        self.m.recepteur = self.m.ecrit
        actions.creer_secours(self.m, "secours", "motdepasse1")
        self.assertNotIn("motdepasse1", repr(self.m.appels))
        self.assertNotIn("motdepasse1", repr(self.m.evenements))

    def test_mot_de_passe_obligatoire_pour_creer(self):
        with self.assertRaises(ErreurSesame):
            actions.creer_secours(self.m, "secours", None)
        self.assertEqual(self.m.appels, [])

    def test_mot_de_passe_trop_court(self):
        with self.assertRaises(ErreurSesame):
            actions.creer_secours(self.m, "secours", "court")

    def test_compte_existant_sans_mot_de_passe(self):
        self.ecrire("/etc/passwd", self.lire("/etc/passwd") + "secours:x:1001:1001::/home/secours:/bin/sh\n")
        actions.creer_secours(self.m, "secours", None)
        self.assertEqual([a[0] for a in self.m.appels], ["usermod"])
        self.assertEqual(self.m.mots_de_passe, {})

    def test_compte_existant_avec_mot_de_passe(self):
        self.ecrire("/etc/passwd", self.lire("/etc/passwd") + "secours:x:1001:1001::/home/secours:/bin/sh\n")
        actions.creer_secours(self.m, "secours", "nouveau-mdp")
        self.assertEqual([a[0] for a in self.m.appels], ["usermod", "chpasswd"])

    def test_nom_invalide(self):
        with self.assertRaises(ErreurSesame):
            actions.creer_secours(self.m, "Pas Valide", "motdepasse1")


class TestQuitterAd(Base):
    def setUp(self):
        super().setUp()
        self.peupler()
        self.config()
        self.m.domaines_joints = ["cofinacorp.com"]
        del self.m.entra[N]  # le compte AD disparaît avec le domaine
        self.ecrire(chemins.NSSWITCH, "passwd: files systemd sss\ngroup: files sss\nshadow: files\nsudoers: files sss\n")
        self.ecrire("/var/lib/sss/db/cache.ldb", "x")
        self.ecrire("/var/lib/sss/db/config.ldb.bak", "garde")
        self.ecrire("/var/lib/sss/mc/passwd", "x")
        self.ecrire(f"/home/{N}/.bashrc", "ancien dossier AD")

    def test_sequence(self):
        sauvegarde.faire(self.m, A)
        self.m.appels.clear()
        self.assertIn("quitté", actions.quitter_ad(self.m))
        self.assertEqual(self.m.modifiantes(), [["realm", "leave", "-v", "cofinacorp.com"],
                                                ["systemctl", "disable", "--now", "sssd"],
                                                ["pam-auth-update", "--disable", "sss"]])
        self.assertEqual(self.m.domaines_joints, [])
        self.assertEqual(self.lire(chemins.NSSWITCH), "passwd: files systemd\ngroup: files\nshadow: files\nsudoers: files\n")
        self.assertFalse(self.existe("/var/lib/sss/db/cache.ldb"))
        self.assertTrue(self.existe("/var/lib/sss/db/config.ldb.bak"))
        self.assertFalse(self.existe("/var/lib/sss/mc/passwd"))
        self.assertTrue(etat.lire(self.m)["quitter_ad"])

    def test_archive_puis_suppression_du_dossier_ad(self):
        sauv = sauvegarde.faire(self.m, A)
        actions.quitter_ad(self.m)
        self.assertFalse(self.existe(f"/home/{N}"))
        with tarfile.open(self.m.chemin(f"{sauv}/home-ad-{N}.tar.gz")) as t:
            self.assertIn(f"{N}/.bashrc", t.getnames())

    def test_sans_sauvegarde_une_est_creee(self):
        actions.quitter_ad(self.m)
        self.assertIsNotNone(etat.derniere_sauvegarde(self.m))
        self.assertTrue(any(n.startswith("home-ad-") for n in self.m.lister(etat.derniere_sauvegarde(self.m)["chemin"])))

    def test_pam_en_echec_donne_un_avertissement(self):
        self.m.recepteur = self.m.ecrit
        self.m.forces[("pam-auth-update", "--disable", "sss")] = Resultat(1)
        actions.quitter_ad(self.m)
        self.assertTrue(any(t == "avertissement" for t, _ in self.m.evenements))

    def test_realm_leave_en_echec(self):
        self.m.panne_a = 0
        with self.assertRaises(ErreurSesame):
            actions.quitter_ad(self.m)

    def test_compte_ad_encore_visible(self):
        self.m.entra[N] = {"uid": 1, "gid": 1, "home": "/x"}
        with self.assertRaises(ErreurSesame):
            actions.quitter_ad(self.m)


class TestInstaller(Base):
    def setUp(self):
        super().setUp()
        self.peupler()
        self.m.paquets.clear()
        self.m.snaps.clear()

    def test_ubuntu_2404(self):
        actions.installer(self.m)
        self.assertEqual(self.m.modifiantes(), [
            ["add-apt-repository", "-y", "ppa:ubuntu-enterprise-desktop/authd"],
            ["apt-get", "update"],
            ["apt-get", "install", "-y", "authd", "gnome-shell", "yaru-theme-gnome-shell"],
            ["snap", "install", "authd-msentraid"]])
        self.assertTrue(etat.lire(self.m)["installer"])

    def test_ubuntu_plus_recent_sans_ppa(self):
        self.ecrire("/etc/os-release", 'VERSION_ID="25.10"\n')
        actions.installer(self.m)
        self.assertNotIn("add-apt-repository", [a[0] for a in self.m.appels])

    def test_snap_deja_la(self):
        self.m.snaps.add("authd-msentraid")
        actions.installer(self.m)
        self.assertNotIn(["snap", "install", "authd-msentraid"], self.m.appels)

    def test_refus_avant_24_04(self):
        for version in ("22.04", "20.04", None):
            self.ecrire("/etc/os-release", f'VERSION_ID="{version}"\n' if version else "")
            with self.assertRaises(ErreurSesame):
                actions.installer(self.m)
        self.assertEqual(self.m.appels, [])

    def test_echec_d_apt(self):
        self.m.panne_a = 1
        with self.assertRaises(ErreurSesame):
            actions.installer(self.m)
        self.assertNotIn("installer", etat.lire(self.m))


class TestConfigurer(Base):
    def setUp(self):
        super().setUp()
        self.peupler()
        self.ecrire(chemins.BROKER_MODELE, "[authd]\nname = Microsoft Entra ID\n")
        self.ecrire(chemins.BROKER_CONF, "# modèle d'origine\n")
        self.ecrire(chemins.LOGIN_DEFS, "LOGIN_TIMEOUT\t\t60\n")
        self.ecrire(chemins.NSSWITCH, "passwd: files systemd\ngroup: files systemd\nshadow: files\n")

    def construire(self, **extra):
        args = dict(locataire=LOCATAIRE, client=CLIENT, compte=N.upper(), groupes=["sudo", "docker"])
        args.update(extra)
        return actions.construire_config(self.m, **args)

    def test_construction_depuis_le_compte_local(self):
        c = self.construire(compte_local=A)
        self.assertEqual((c.compte_local, c.uid, c.gid, c.dossier), (A, U, U, H))
        self.assertEqual(c.compte, N)
        self.assertEqual(c.secours, "secours")

    def test_config_complete(self):
        actions.configurer(self.m, self.construire(compte_local=A))
        self.assertEqual(cfg.charger(self.m).compte, N)
        self.assertEqual(self.lire(chemins.BROKER_AUTHD), "[authd]\nname = Microsoft Entra ID\n")
        self.assertEqual(self.lire(chemins.BROKER_CONF + ".origine"), "# modèle d'origine\n")
        self.assertIn(f"owner = {N}", self.lire(chemins.BROKER_CONF))
        self.assertEqual(self.lire(chemins.LOGIN_DEFS), "LOGIN_TIMEOUT\t\t300\n")
        self.assertEqual(self.lire(chemins.NSSWITCH),
                         "passwd: files systemd authd\ngroup: files systemd authd\nshadow: files authd\n")
        self.assertEqual(self.m.modifiantes(), [["systemctl", "restart", "authd"],
                                                ["systemctl", "restart", chemins.SERVICE_BROKER]])

    def test_origine_jamais_ecrasee(self):
        actions.configurer(self.m, self.construire(compte_local=A))
        actions.configurer(self.m, self.construire(compte_local=A))
        self.assertEqual(self.lire(chemins.BROKER_CONF + ".origine"), "# modèle d'origine\n")

    def test_idempotent(self):
        actions.configurer(self.m, self.construire(compte_local=A))
        un = (self.lire(chemins.NSSWITCH), self.lire(chemins.BROKER_CONF), self.lire(chemins.SESAME_CONF))
        actions.configurer(self.m, self.construire(compte_local=A))
        self.assertEqual(un, (self.lire(chemins.NSSWITCH), self.lire(chemins.BROKER_CONF), self.lire(chemins.SESAME_CONF)))

    def test_login_timeout_plus_haut_garde(self):
        self.ecrire(chemins.LOGIN_DEFS, "LOGIN_TIMEOUT 600\n")
        actions.configurer(self.m, self.construire(compte_local=A))
        self.assertEqual(self.lire(chemins.LOGIN_DEFS), "LOGIN_TIMEOUT 600\n")

    def test_reconfiguration_apres_la_reprise_garde_uid_et_dossier(self):
        actions.configurer(self.m, self.construire(compte_local=A))
        self.ecrire("/etc/passwd", "root:x:0:0::/root:/bin/bash\n")  # le compte local a disparu
        c = self.construire(compte_local=A)
        self.assertEqual((c.uid, c.dossier), (U, H))

    def test_valeurs_invalides(self):
        for extra in ({"locataire": "x"}, {"client": ""}, {"compte": "pas-un-upn"}, {"compte_local": "n-existe-pas"},
                      {"groupes": ["Mauvais Nom"]}):
            with self.subTest(extra=extra), self.assertRaises(ErreurSesame):
                self.construire(**dict({"compte_local": A}, **extra))

    def test_module_non_installe(self):
        self.m.supprimer(chemins.BROKER_MODELE)
        with self.assertRaises(ErreurSesame):
            actions.configurer(self.m, self.construire(compte_local=A))
        self.assertFalse(self.existe(chemins.SESAME_CONF))

    def test_desactiver(self):
        actions.configurer(self.m, self.construire(compte_local=A))
        self.m.appels.clear()
        actions.desactiver(self.m)
        self.assertFalse(self.existe(chemins.BROKER_AUTHD))
        self.assertEqual(self.m.appels, [["systemctl", "restart", "authd"]])

    def test_noter_verification(self):
        actions.noter_verification(self.m)
        self.assertIn("date", etat.lire(self.m)["verification"])
        self.assertEqual(self.m.appels, [])
