"""Reprise du compte local par le compte Entra, annulation, démarrage."""
import json

from sesame import chemins, reprise
from sesame.systeme import ErreurSesame, Resultat
from tests.commun import A, DOC, G, H, N, NG, NH, NU, U, Base


class BaseReprise(Base):
    def setUp(self):
        super().setUp()
        self.peupler()
        self.config()

    def reprendre(self, mode="maintenant"):
        return reprise.reprendre(self.m, self.parametres(), mode)

    def derniere(self):
        return json.loads(self.lire(chemins.DERNIERE_REPRISE))

    def dossier_intact(self):
        self.assertEqual(self.lire(f"{H}/doc.txt"), DOC)
        self.assertEqual(self.lire(f"{H}/.config/réglage"), "x")
        self.assertFalse(self.existe(H + reprise.SUFFIXE))
        self.assertFalse(self.existe(f"{H}/{H.split('/')[-1]}"))

    def verifier_authctl(self):
        """Le vrai dossier H n'est jamais la cible d'authctl : `set-uid` et `set-gid` quand le compte Entra n'y
        pointe pas ; `set-home` seulement quand H est écarté (le chemin n'existe pas sur le disque)."""
        for appel in self.m.authctl:
            if appel["commande"][1] == "set-home":
                if appel["dossier_courant"] == H:
                    self.assertFalse(appel["courant_existe"], appel)
            else:
                self.assertNotEqual(appel["dossier_courant"], H, appel)

    def etat_interrompu(self):
        """Reprise faite, puis reprise-etat.json réécrit : l'état d'une reprise interrompue juste avant la fin."""
        self.assertTrue(self.reprendre()[0])
        sauv = self.m.lire_json(chemins.ETAT_JSON)["sauvegardes"][-1]["chemin"]
        self.m.ecrire_json(chemins.REPRISE_ETAT, {
            "compte_local": A, "compte_entra": N, "uid": U, "gid": G, "dossier": H, "entra_uid": NU,
            "entra_gid": NG, "entra_dossier": NH, "horodatage": "x", "sauvegarde": sauv})


class TestSequence(BaseReprise):
    def test_ordre_exact_des_commandes(self):
        ok, message = self.reprendre()
        self.assertTrue(ok, message)
        sauv = self.m.chemin(self.m.lire_json(chemins.ETAT_JSON)["sauvegardes"][-1]["chemin"])
        self.assertEqual(self.m.appels, [
            ["getent", "passwd", N],
            ["crontab", "-u", A, "-l"],
            ["userdel", A],
            ["authctl", "user", "set-uid", N, str(U)],
            ["authctl", "group", "set-gid", N, str(G)],
            ["authctl", "user", "set-home", N, H],
            ["crontab", "-u", N, str(sauv / f"crontab-{A}")],
            ["systemctl", "daemon-reload"],
        ])

    def test_resultat_final(self):
        ok, _ = self.reprendre()
        self.assertTrue(ok)
        self.dossier_intact()
        self.verifier_authctl()
        self.assertEqual(self.m.entra[N], {"uid": U, "gid": G, "home": H})
        self.assertNotIn(A, self.m.comptes_locaux())
        self.assertNotIn(A, self.m.groupes_locaux())
        self.assertFalse(self.existe(f"/var/spool/cron/crontabs/{A}"))
        self.assertTrue(self.derniere()["ok"])
        self.assertFalse(self.existe(chemins.REPRISE_ETAT))
        self.assertTrue(any(n.startswith("reprise-etat.termine-") for n in self.m.lister(chemins.VAR_SESAME)))

    def test_dossier_vierge_ecarte(self):
        self.reprendre()
        sauv = self.m.lire_json(chemins.ETAT_JSON)["sauvegardes"][-1]["chemin"]
        self.assertEqual(self.lire(f"{sauv}/dossier-entra-vierge/.profile"), "vierge\n")
        self.assertFalse(self.existe(NH))

    def test_groupe_restant_supprime(self):
        self.m.groupe_reste = True
        self.reprendre()
        self.assertIn(["groupdel", A], self.m.appels)

    def test_authctl_qui_cree_le_dossier(self):
        self.m.authctl_cree_dossier = True
        ok, message = self.reprendre()
        self.assertTrue(ok, message)
        self.dossier_intact()

    def test_reglages(self):
        self.reprendre()
        self.assertEqual(self.lire("/etc/subuid"), f"{U}:100000:65536\nautre:200000:65536\n")
        self.assertEqual(self.lire("/etc/subgid"), f"{U}:100000:65536\n")
        unite = self.lire("/etc/systemd/system/app.service")
        self.assertIn(f"User={U}\n", unite)
        self.assertIn(f"Group={G}\n", unite)
        self.assertIn("After=authd.socket authd.service", self.lire("/etc/systemd/system/app.service.d/sesame-authd.conf"))
        self.assertEqual(self.lire("/etc/systemd/system/autre.service"), "[Service]\nUser=root\n")
        self.assertFalse(self.existe("/etc/systemd/system/autre.service.d"))
        self.assertIn(f"<ACEDataUser>{N}</ACEDataUser>", self.lire("/etc/vmware/hostd/authorization.xml"))
        self.assertIn(f"#AutomaticLogin={A}", self.lire("/etc/gdm3/custom.conf"))
        self.assertEqual(self.m.crontabs[N], "0 2 * * * sauvegarde\n")
        users = self.lire(f"/var/lib/AccountsService/users/{N}")
        self.assertIn(f"icons/{N}", users)
        self.assertNotIn(f"icons/{A}", users)
        self.assertEqual(self.lire(f"/var/lib/AccountsService/icons/{N}"), "png")
        notes = self.m.lire_json(chemins.ETAT_JSON)["reprise"]
        self.assertEqual(notes["unites"], ["app.service"])
        self.assertTrue(notes["crontab"])

    def test_sans_crontab(self):
        del self.m.crontabs[A]
        self.reprendre()
        self.assertNotIn("crontab", [a[0] for a in self.m.appels if a[1:2] == ["-u"] and a[2] == N])

    def test_sauvegarde_avant_reprise(self):
        self.reprendre()
        sauv = self.m.lire_json(chemins.ETAT_JSON)["sauvegardes"][-1]
        self.assertEqual(sauv["motif"], "avant-reprise")
        self.assertIn("avant-reprise", sauv["chemin"])
        self.assertIn(A, self.lire(sauv["chemin"] + "/etc/passwd"))
        self.assertEqual(self.lire(f"{sauv['chemin']}/crontab-{A}"), "0 2 * * * sauvegarde\n")


class TestPreconditions(BaseReprise):
    def refuse(self, fragment, mode="maintenant", intact=True):
        avant = list(self.m.appels)
        ok, message = self.reprendre(mode)
        self.assertFalse(ok)
        self.assertIn(fragment, message)
        if intact:
            self.dossier_intact()
        self.assertEqual([a for a in self.m.appels[len(avant):] if a[0] not in ("getent",)], [])
        self.assertFalse(self.derniere()["ok"])

    def test_compte_local_absent(self):
        self.ecrire("/etc/passwd", "root:x:0:0::/root:/bin/bash\n")
        self.refuse("n'existe pas")

    def test_uid_different(self):
        self.ecrire("/etc/passwd", f"{A}:x:1234:1234::{H}:/bin/bash\n")
        self.refuse("n'existe pas")

    def test_dossier_absent(self):
        self.m.supprimer(H)
        ok, message = self.reprendre()
        self.assertFalse(ok)
        self.assertIn("introuvable", message)

    def test_compte_entra_inconnu(self):
        del self.m.entra[N]
        self.refuse("inconnu")

    def test_compte_entra_dans_passwd(self):
        self.ecrire("/etc/passwd", self.lire("/etc/passwd") + f"{N}:x:5000:5000::/home/x:/bin/bash\n")
        self.refuse("n'est pas un compte authd")

    def test_meme_uid(self):
        self.m.entra[N]["uid"] = U
        self.refuse("déjà l'UID")

    def test_meme_dossier(self):
        self.m.entra[N]["home"] = H
        self.refuse("pointe déjà")

    def test_authctl_absent(self):
        self.m.authctl_present = False
        self.refuse("authctl")

    def test_processus_ancien_compte(self):
        self.ecrire("/proc/321/status", f"Name:\tfirefox\nUid:\t{U}\t{U}\t{U}\t{U}\n")
        self.refuse("firefox")

    def test_processus_compte_entra(self):
        self.ecrire("/proc/322/status", f"Name:\tgnome-shell\nUid:\t{NU}\t{NU}\t{NU}\t{NU}\n")
        self.refuse("gnome-shell")

    def test_processus_d_un_autre_compte_ne_gene_pas(self):
        self.ecrire("/proc/323/status", "Name:\tsshd\nUid:\t0\t0\t0\t0\n")
        self.assertTrue(self.reprendre()[0])

    def test_appelant_est_le_compte_local(self):
        self.m.env["PKEXEC_UID"] = str(U)
        self.refuse("autre compte")

    def test_appelant_autre_compte(self):
        self.m.env["PKEXEC_UID"] = "1001"
        self.assertTrue(self.reprendre()[0])

    def test_reserve_existante(self):
        self.ecrire(H + reprise.SUFFIXE + "/x", "x")
        self.refuse("existe", intact=False)

    def test_reprise_deja_en_cours(self):
        self.ecrire(chemins.REPRISE_ETAT, "{}")
        self.refuse("déjà en cours")

    def test_processus_ignores_au_demarrage_de_la_programmation(self):
        self.ecrire("/proc/321/status", f"Name:\tfirefox\nUid:\t{U}\t{U}\t{U}\t{U}\n")
        self.assertIn("prochain démarrage", reprise.programmer(self.m, self.parametres()))


class TestPannes(BaseReprise):
    """Une panne simulée à chaque commande de la reprise, suivie de l'annulation."""

    def noms_des_commandes(self):
        self.reprendre()
        return [" ".join(a[:4]) for a in self.m.modifiantes()]

    def test_panne_a_chaque_commande(self):
        noms = self.noms_des_commandes()
        self.assertEqual(len(noms), 6)
        for i, nom in enumerate(noms):
            with self.subTest(commande=nom):
                self.setUp()
                self.m.panne_a = i
                ok, message = self.reprendre()
                self.assertFalse(ok, message)
                self.assertEqual(len(self.m.pannes), 1)
                self.assertIn("Échec de la reprise", message)
                self.assertIn("restauré", message)
                self.dossier_intact()
                self.verifier_authctl()
                self.assertEqual(self.m.entra[N], {"uid": NU, "gid": NG, "home": NH})
                self.assertEqual(self.lire(f"{NH}/.profile"), "vierge\n")
                self.assertEqual(self.m.comptes_locaux()[A].uid, U)
                self.assertIn(A, self.m.groupes_locaux())
                self.assertEqual(self.m.crontabs.get(A), "0 2 * * * sauvegarde\n")
                self.assertNotIn(N, self.m.crontabs)
                self.assertIn(f"User={A}", self.lire("/etc/systemd/system/app.service"))
                self.assertFalse(self.existe("/etc/systemd/system/app.service.d/sesame-authd.conf"))
                self.assertIn(f"AutomaticLogin={A}", self.lire("/etc/gdm3/custom.conf"))
                self.assertIn(f"<ACEDataUser>{A}", self.lire("/etc/vmware/hostd/authorization.xml"))
                self.assertTrue(self.lire("/etc/subuid").startswith(f"{A}:"))
                self.assertFalse(self.existe(f"/var/lib/AccountsService/users/{N}"))
                self.assertFalse(self.derniere()["ok"])
                self.assertFalse(self.existe(chemins.REPRISE_ETAT))
                self.assertTrue(any(n.startswith("reprise-etat.annule-") for n in self.m.lister(chemins.VAR_SESAME)))

    def test_panne_de_la_sauvegarde_ne_change_rien(self):
        self.m.forces[("crontab", "-u", A, "-l")] = Resultat(1)
        ok, _ = self.reprendre()
        self.assertTrue(ok)  # pas de crontab : ce n'est pas une panne

    def test_annulation_echoue_sur_set_home_et_remet_h(self):
        self.m.panne_a = 5  # daemon-reload échoue : N pointe sur H
        # L'annulation automatique doit faire `set-home` ; on le fait échouer (7e commande modifiante).
        self.m.forces = {}
        original = self.m.lancer

        def lancer(argv, entree=None, direct=None):
            if argv[:4] == ["authctl", "user", "set-home", N] and argv[4] == NH:
                self.m.appels.append(list(argv))
                return Resultat(1, "", "panne")
            return original(argv, entree, direct)

        self.m.lancer = lancer
        ok, message = self.reprendre()
        self.assertFalse(ok)
        self.assertIn("L'annulation a échoué", message)
        self.dossier_intact()
        self.assertTrue(self.existe(chemins.REPRISE_ETAT))  # reste là pour réessayer
        self.m.lancer = original
        ok, message = reprise.annuler(self.m)
        self.assertTrue(ok, message)
        self.dossier_intact()
        self.assertEqual(self.m.entra[N]["home"], NH)


class TestAnnulationManuelle(BaseReprise):
    def test_apres_reprise_reussie(self):
        self.m.panne_a = 5
        self.reprendre()
        self.assertFalse(self.existe(chemins.REPRISE_ETAT))
        ok, message = reprise.annuler(self.m)
        self.assertFalse(ok)
        self.assertIn("Aucune reprise", message)

    def test_reprise_interrompue(self):
        self.etat_interrompu()
        ok, message = reprise.annuler(self.m)
        self.assertTrue(ok, message)
        self.dossier_intact()
        self.verifier_authctl()
        self.assertEqual(self.m.entra[N], {"uid": NU, "gid": NG, "home": NH})
        self.assertEqual(self.m.comptes_locaux()[A].uid, U)
        self.assertFalse(self.derniere()["ok"])
        self.assertIn("annulée", self.derniere()["message"])

    def test_refuse_si_processus(self):
        self.etat_interrompu()
        self.ecrire("/proc/400/status", f"Name:\tfirefox\nUid:\t{U}\t{U}\t{U}\t{U}\n")
        ok, message = reprise.annuler(self.m)
        self.assertFalse(ok)
        self.assertIn("fermez", message)
        self.assertEqual(self.m.entra[N]["home"], H)

    def test_dossier_ecarte_est_remis(self):
        """Coupure juste après `mv H H.sesame-reprise` : l'annulation remet H."""
        self.etat_interrompu()
        self.m.deplacer(H, H + reprise.SUFFIXE)
        ok, message = reprise.annuler(self.m)
        self.assertTrue(ok, message)
        self.dossier_intact()


class TestDemarrage(BaseReprise):
    def programmer(self):
        reprise.programmer(self.m, self.parametres())

    def test_programmation(self):
        self.programmer()
        donnees = self.m.lire_json(chemins.REPRISE_PROGRAMMEE)
        self.assertEqual(donnees["compte_entra"], N)
        self.assertEqual(donnees["uid"], U)
        self.assertEqual(oct(self.m.chemin(chemins.REPRISE_PROGRAMMEE).stat().st_mode & 0o777), "0o600")
        self.assertIn(["systemctl", "enable", "sesame-reprise.service"], self.m.appels)

    def test_programmation_passe_avant_les_services_du_compte(self):
        """Un service `User=A` tournerait déjà au démarrage et bloquerait la reprise : elle passe avant lui."""
        self.programmer()
        ordre = self.m.lire(reprise.ORDRE_REPRISE)
        self.assertIn("Before=app.service", ordre)
        self.assertNotIn("autre.service", ordre)
        reprise.annuler_programmation(self.m)
        self.assertFalse(self.existe(reprise.ORDRE_REPRISE))
        self.assertFalse(self.existe(reprise.ORDRE_REPRISE.rsplit("/", 1)[0]))

    def test_ordre_retire_apres_le_demarrage(self):
        self.programmer()
        reprise.executer_demarrage(self.m)
        self.assertFalse(self.existe(reprise.ORDRE_REPRISE))

    def test_programmation_qui_echoue_retire_le_fichier(self):
        self.m.panne_a = 0
        with self.assertRaises(ErreurSesame):
            self.programmer()
        self.assertFalse(self.existe(chemins.REPRISE_PROGRAMMEE))

    def test_annuler_programmation(self):
        self.programmer()
        reprise.annuler_programmation(self.m)
        self.assertFalse(self.existe(chemins.REPRISE_PROGRAMMEE))
        self.assertIn(["systemctl", "disable", "sesame-reprise.service"], self.m.appels)

    def test_fichier_programme_supprime_avant_tout(self):
        self.programmer()
        vus = []
        original = self.m.lancer

        def lancer(argv, entree=None, direct=None):
            vus.append((argv[0], self.existe(chemins.REPRISE_PROGRAMMEE)))
            return original(argv, entree, direct)

        self.m.lancer = lancer
        ok, message = reprise.executer_demarrage(self.m)
        self.assertTrue(ok, message)
        self.assertTrue(vus)
        self.assertEqual({present for _, present in vus}, {False})
        self.assertEqual(self.m.appels[-1], ["systemctl", "disable", "sesame-reprise.service"])
        self.assertEqual(self.derniere()["mode"], "execution-demarrage")

    def test_echec_au_demarrage_annule_et_ne_bloque_pas(self):
        self.programmer()
        self.m.nb_modif = 0
        self.m.panne_a = 3  # set-home
        ok, message = reprise.executer_demarrage(self.m)
        self.assertFalse(ok)
        self.assertFalse(self.existe(chemins.REPRISE_PROGRAMMEE))
        self.dossier_intact()
        self.assertEqual(self.m.appels[-1], ["systemctl", "disable", "sesame-reprise.service"])

    def test_fichier_illisible(self):
        self.ecrire(chemins.REPRISE_PROGRAMMEE, "{pas du json")
        ok, _ = reprise.executer_demarrage(self.m)
        self.assertFalse(ok)
        self.assertFalse(self.existe(chemins.REPRISE_PROGRAMMEE))

    def test_aucun_fichier(self):
        ok, message = reprise.executer_demarrage(self.m)
        self.assertFalse(ok)
        self.assertIn("Aucune", message)

    def test_exception_inattendue(self):
        self.programmer()
        self.m.lancer = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boum"))
        ok, message = reprise.executer_demarrage(self.m)
        self.assertFalse(ok)
