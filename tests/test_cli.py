"""Ligne de commande : version, état, portail, appel de l'assistant root (jamais sudo)."""
import io
import json
import os
import subprocess
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace

from sesame import chemins, cli, guide, sauvegarde
from tests.commun import A, CLIENT, LOCATAIRE, N, Base

DEPOT = Path(__file__).resolve().parent.parent


class Lanceur:
    """Enregistre les appels de subprocess.run."""

    def __init__(self, code=0):
        self.appels, self.code = [], code

    def __call__(self, cmd, input=None, text=None):
        self.appels.append((cmd, input))
        return SimpleNamespace(returncode=self.code)


class BaseCli(Base):
    def setUp(self):
        super().setUp()
        self.peupler()
        self.config()
        self.lanceur = Lanceur()

    def main(self, *argv, **kw):
        sortie, erreur = io.StringIO(), io.StringIO()
        kw.setdefault("lanceur", self.lanceur)
        with redirect_stdout(sortie), redirect_stderr(erreur):
            code = cli.main(list(argv), self.m, **kw)
        return code, sortie.getvalue(), erreur.getvalue()


class TestAffichage(BaseCli):
    def test_version(self):
        code, sortie, _ = self.main("version")
        self.assertEqual((code, sortie), (0, "Sésame 1.0.0\n"))

    def test_version_via_le_lanceur(self):
        r = subprocess.run([sys.executable, str(DEPOT / "bin" / "sesame"), "version"], capture_output=True, text=True)
        self.assertEqual(r.stdout, "Sésame 1.0.0\n")
        self.assertEqual(r.stdout.split()[-1], "1.0.0")

    def test_portail(self):
        _, sortie, _ = self.main("portail")
        self.assertIn(guide.URL_PORTAIL, sortie)
        for titre, detail in guide.PORTAIL:
            self.assertIn(titre, sortie)
            self.assertIn(detail, sortie)

    def test_etat_par_defaut(self):
        code, sortie, _ = self.main()
        self.assertEqual(code, 0)
        self.assertEqual(sortie, self.main("etat")[1])
        self.assertEqual(len([l for l in sortie.splitlines() if l[:1] in "✓·–⏲✗?" and l[1:2] == " "]), 8)
        self.assertIn("Étape suivante : Sauvegarder la configuration", sortie)

    def test_symboles(self):
        sauvegarde.faire(self.m, A)
        _, sortie, _ = self.main("etat")
        self.assertIn("✓ 1. Sauvegarder", sortie)
        self.assertIn("– 3. Quitter", sortie)

    def test_etat_json(self):
        for argv in (("etat", "--json"), ("--json",)):
            donnees = json.loads(self.main(*argv)[1])
            self.assertEqual(len(donnees["etapes"]), 8)
            self.assertEqual(donnees["suivante"], "sauvegarde")

    def test_aucune_action_root_pour_la_lecture(self):
        self.main("etat")
        self.main("portail")
        self.assertEqual(self.lanceur.appels, [])


class TestRacine(BaseCli):
    def test_pkexec_jamais_sudo(self):
        self.assertEqual(cli.commande_racine(["etat"], deja_root=False)[:1], ["pkexec"])
        self.assertEqual(cli.commande_racine(["etat"], deja_root=True)[0], cli.chemin_racine())
        for racine in (True, False):
            self.assertNotIn("sudo", cli.commande_racine(["x"], deja_root=racine))

    def test_chemin_depuis_le_depot(self):
        self.assertEqual(cli.chemin_racine(), str(DEPOT / "libexec" / "sesame-racine"))

    def test_actions_simples(self):
        for commande in ("sauvegarde", "quitter-ad", "installer", "annuler-reprise", "desactiver"):
            self.lanceur.appels.clear()
            self.main(commande)
            cmd, entree = self.lanceur.appels[0]
            self.assertEqual(cmd[-1], commande)
            self.assertIsNone(entree)
            self.assertEqual(cmd[0], "pkexec" if os.geteuid() else cmd[0])

    def test_code_de_sortie_transmis(self):
        self.lanceur.code = 1
        self.assertEqual(self.main("installer")[0], 1)

    def test_authentification_annulee(self):
        self.lanceur.code = 126
        code, _, erreur = self.main("installer")
        self.assertEqual(code, 126)
        self.assertIn("Authentification annulée", erreur)

    def test_secours_demande_deux_fois_le_mot_de_passe(self):
        reponses = iter(["motdepasse1", "motdepasse1"])
        invites = []
        code, _, _ = self.main("secours", mot_de_passe=lambda p: invites.append(p) or next(reponses))
        self.assertEqual(code, 0)
        self.assertEqual(len(invites), 2)
        cmd, entree = self.lanceur.appels[0]
        self.assertEqual(entree, "motdepasse1\n")
        self.assertNotIn("motdepasse1", " ".join(cmd))

    def test_secours_mots_de_passe_differents_ou_courts(self):
        for reponses in (["motdepasse1", "autre-chose"], ["court", "court"]):
            it = iter(reponses)
            code, _, _ = self.main("secours", mot_de_passe=lambda p: next(it))
            self.assertEqual(code, 1)
        self.assertEqual(self.lanceur.appels, [])

    def test_configurer_demande_les_valeurs_manquantes(self):
        reponses = iter([LOCATAIRE, CLIENT, N, "", ""])
        invites = []
        self.main("configurer", saisie=lambda p: invites.append(p) or next(reponses))
        cmd, _ = self.lanceur.appels[0]
        self.assertEqual(cmd[-11:], ["configurer", "--locataire", LOCATAIRE, "--client", CLIENT, "--compte", N,
                                     "--compte-local", A, "--groupes", "sudo,docker"])
        self.assertIn(f"[{A}]", invites[3])  # le compte local est proposé

    def test_configurer_redemande_une_valeur_invalide(self):
        reponses = iter(["pas-un-guid", LOCATAIRE])
        code, _, erreur = self.main("configurer", "--client", CLIENT, "--compte", N, "--compte-local", A,
                                    "--groupes", "sudo", saisie=lambda p: next(reponses))
        self.assertIn("invalide", erreur)
        self.assertIn(LOCATAIRE, self.lanceur.appels[0][0])

    def test_configurer_sans_question_si_tout_est_donne(self):
        self.main("configurer", "--locataire", LOCATAIRE, "--client", CLIENT, "--compte", N.upper(), "--compte-local", A,
                  "--groupes", "", saisie=lambda p: self.fail("question inattendue"))
        cmd, _ = self.lanceur.appels[0]
        self.assertIn(N, cmd)  # UPN en minuscules

    def test_reprise_demande_confirmation(self):
        code, sortie, _ = self.main("reprise", saisie=lambda p: "non")
        self.assertEqual(code, 1)
        self.assertEqual(self.lanceur.appels, [])
        self.main("reprise", saisie=lambda p: "OUI")
        self.assertEqual(self.lanceur.appels[0][0][-2:], ["reprise", "--au-demarrage"])

    def test_reprise_modes(self):
        for option, attendu in (("--maintenant", "--maintenant"), ("--au-demarrage", "--au-demarrage"),
                                ("--annuler-programmation", "--annuler-programmation")):
            self.lanceur.appels.clear()
            self.main("reprise", option, "--oui", saisie=lambda p: self.fail("confirmation inattendue"))
            self.assertEqual(self.lanceur.appels[0][0][-2:], ["reprise", attendu])

    def test_verifier_note_le_passage_reussi_seulement_connecte(self):
        self.m.entra[N] = {"uid": 1000, "gid": 1000, "home": "/home/" + A}
        self.m.ecrire("/etc/passwd", "root:x:0:0::/root:/bin/bash\nsecours:x:1001:1001::/h:/bin/sh\n")
        self.m.ecrire("/etc/group", "sudo:x:27:secours\ndocker:x:9:\n")
        self.m.actifs.update({"authd", chemins.SERVICE_BROKER})
        code, sortie, _ = self.main("verifier")
        self.assertIn("Vous n'êtes pas connecté", sortie)
        self.assertEqual([a[0][-1] for a in self.lanceur.appels], [])  # groupes manquants : échec, rien noté
