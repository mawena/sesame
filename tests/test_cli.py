"""Ligne de commande : version, état, rejoindre, étapes, appel de l'assistant root (jamais sudo).

Le cœur (config, étapes, validation) est remplacé par des doublures : ces tests ne vérifient que la ligne de commande.
"""
import io
import json
import os
import re
import subprocess
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from sesame import cli
from sesame.version import VERSION

DEPOT = Path(__file__).resolve().parent.parent
ADRESSE = "charles.gamligo@entreprise.com"
IDS = ("sauvegarde", "secours", "nom_machine", "quitter_ad", "outils", "compiler", "installer", "configurer",
       "premiere_connexion")


def etat():
    etapes = [{"id": i, "titre": i.replace("_", " ").capitalize(), "explication": "", "detail": "d",
               "statut": "a_faire"} for i in IDS]
    etapes[0]["statut"] = "fait"
    return {"version": VERSION, "etapes": etapes, "suivante": "secours"}


class Lanceur:
    """Enregistre les appels de subprocess.run ; `sorties` : stdout (JSON) à renvoyer, un élément par appel."""

    def __init__(self, code=0, sorties=()):
        self.appels, self.code, self.sorties = [], code, list(sorties)

    def __call__(self, cmd, input=None, text=None, stdout=None):
        self.appels.append((cmd, input))
        sortie = self.sorties.pop(0) if self.sorties and stdout is not None else None
        return SimpleNamespace(returncode=self.code, stdout=sortie)


def json_lignes(*evenements):
    return "".join(json.dumps(e) + "\n" for e in evenements)


COMPILATION_REQUISE = json_lignes({"type": "etape", "texte": "Sauvegarde"},
                                  {"type": "compilation_requise", "texte": "à compiler"},
                                  {"type": "fin", "ok": True, "message": "Préparation terminée"})
FIN = json_lignes({"type": "fin", "ok": True, "message": "Terminé"})


class FauxeCompilation:
    """Doublure de sesame.compilation."""

    def __init__(self, file=None, a_jour=False):
        self.file, self._a_jour, self.appels, self.compile = file, a_jour, [], False

    def etat(self, dossier):
        return {"compile": self.compile, "commit": None, "date": None, "paquets": {}}

    def dossier_par_defaut(self):
        return "/home/u/.local/share/sesame/himmelblau"

    def commande_file(self, dossier):
        return self.file

    def commande_directe(self, dossier):
        return ["python3", "-m", "sesame.compilation", "--directe", dossier]

    def a_jour(self, dossier, lancer=None):
        self.appels.append(dossier)
        return self._a_jour


DOSSIER = "/home/u/.local/share/sesame/himmelblau"
PAQUETS = DOSSIER + "/packaging"


def valider_compte(v):
    return re.fullmatch(r"[^@\s]+@[^@\s]+\.[A-Za-z]+", v) is not None


def valider_nom(v):
    return re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,13}[A-Za-z0-9]|[A-Za-z0-9]", v) is not None and not v.isdigit()


class BaseCli(unittest.TestCase):
    def setUp(self):
        self.lanceur = Lanceur()
        self.compilation = FauxeCompilation()
        self.defauts = SimpleNamespace(compte="", compte_local="charles-gamligo", nom_machine="")
        for nom, valeur in (("etat_complet", lambda s: etat()),
                            ("defauts", lambda s: self.defauts),
                            ("valider_compte", valider_compte),
                            ("valider_nom_machine", valider_nom)):
            patcher = mock.patch.object(cli, nom, valeur)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = mock.patch.object(cli, "compilation", self.compilation)
        patcher.start()
        self.addCleanup(patcher.stop)

    def main(self, *argv, **kw):
        sortie, erreur = io.StringIO(), io.StringIO()
        kw.setdefault("lanceur", self.lanceur)
        kw.setdefault("utilisateur", lambda: "charles-gamligo")
        kw.setdefault("hote", lambda: "pc-bureau")
        kw.setdefault("systeme", object())
        systeme = kw.pop("systeme")
        with redirect_stdout(sortie), redirect_stderr(erreur):
            code = cli.main(list(argv), systeme, **kw)
        return code, sortie.getvalue(), erreur.getvalue()

    @staticmethod
    def pas_de_question(*_):
        raise AssertionError("question inattendue")


class TestAffichage(BaseCli):
    def test_version(self):
        code, sortie, _ = self.main("version")
        self.assertEqual((code, sortie), (0, f"Sésame {VERSION}\n"))

    def test_version_via_le_lanceur(self):
        r = subprocess.run([sys.executable, str(DEPOT / "bin" / "sesame"), "version"], capture_output=True, text=True)
        self.assertEqual(r.stdout, f"Sésame {VERSION}\n")

    def test_etat_par_defaut(self):
        code, sortie, _ = self.main()
        self.assertEqual(code, 0)
        self.assertEqual(sortie, self.main("etat")[1])
        self.assertEqual(len([l for l in sortie.splitlines() if l[:1] in "✓·–⏲✗?" and l[1:2] == " "]), len(IDS))
        self.assertIn("✓ 1. Sauvegarde", sortie)
        self.assertIn("Étape suivante : Secours", sortie)

    def test_etat_json(self):
        for argv in (("etat", "--json"), ("--json",)):
            donnees = json.loads(self.main(*argv)[1])
            self.assertEqual([e["id"] for e in donnees["etapes"]], list(IDS))
            self.assertNotIn("derniere_reprise", donnees)

    def test_aucune_action_root_pour_la_lecture(self):
        self.main("etat")
        self.main("version")
        self.assertEqual(self.lanceur.appels, [])

    def test_commandes_authd_retirees(self):
        for argv in (["portail"], ["reprise"], ["annuler-reprise"], ["configurer", "--locataire", "x"],
                     ["configurer", "--client", "x"], ["configurer", "--connexion", "code"],
                     ["configurer", "--groupes", "sudo"]):
            with self.assertRaises(SystemExit) as e, redirect_stderr(io.StringIO()):
                cli.main(argv, object())
            self.assertEqual(e.exception.code, 2, argv)

    def test_aide_en_francais(self):
        sortie = io.StringIO()
        with self.assertRaises(SystemExit), redirect_stdout(sortie):
            cli.main(["--help"], object())
        for mot in ("Himmelblau", "rejoindre", "COMMANDE"):
            self.assertIn(mot, sortie.getvalue())
        sortie = io.StringIO()
        with self.assertRaises(SystemExit), redirect_stdout(sortie):
            cli.main(["rejoindre", "--help"], object())
        self.assertIn("--nom-machine", sortie.getvalue())


class TestRacine(BaseCli):
    def test_pkexec_jamais_sudo(self):
        self.assertEqual(cli.commande_racine(["etat"], deja_root=False)[:1], ["pkexec"])
        self.assertEqual(cli.commande_racine(["etat"], deja_root=True)[0], cli.chemin_racine())
        for racine in (True, False):
            self.assertNotIn("sudo", cli.commande_racine(["x"], deja_root=racine))

    def test_chemin_depuis_le_depot(self):
        self.assertEqual(cli.chemin_racine(), str(DEPOT / "libexec" / "sesame-racine"))

    def test_actions_simples(self):
        for commande in ("sauvegarde", "quitter-ad", "outils", "desactiver"):
            self.lanceur.appels.clear()
            self.main(commande)
            cmd, entree = self.lanceur.appels[0]
            self.assertEqual(cmd[-1], commande)
            self.assertIsNone(entree)
            self.assertEqual(cmd[0], "pkexec" if os.geteuid() else cmd[0])

    def test_code_de_sortie_transmis(self):
        self.lanceur.code = 1
        self.assertEqual(self.main("outils")[0], 1)

    def test_authentification_annulee(self):
        for code in (126, 127):
            self.lanceur.code = code
            c, _, erreur = self.main("outils")
            self.assertEqual(c, code)
            self.assertIn("Authentification annulée", erreur)


class TestRejoindre(BaseCli):
    def racine(self, *args):
        return cli.commande_racine(list(args))

    def base(self, nom="PC-Charles"):
        return ["rejoindre", "--compte", ADRESSE, "--nom-machine", nom, "--compte-local", "charles-gamligo"]

    def test_sans_compilation_requise_une_seule_commande_exacte(self):
        self.lanceur.sorties = [FIN]
        code, sortie, erreur = self.main("rejoindre", "--compte", ADRESSE, "--nom-machine", "PC-Charles",
                                         saisie=self.pas_de_question, mot_de_passe=self.pas_de_question)
        self.assertEqual(code, 0)
        self.assertEqual(len(self.lanceur.appels), 1)
        cmd, entree = self.lanceur.appels[0]
        self.assertEqual(cmd, self.racine("--json", *self.base()))
        self.assertIsNone(entree)
        self.assertIn("Terminé", sortie)

    def test_compilation_puis_seconde_commande_avec_paquets(self):
        self.lanceur.sorties = [COMPILATION_REQUISE, FIN]
        code, sortie, _ = self.main("rejoindre", "--compte", ADRESSE, "--nom-machine", "PC-Charles")
        self.assertEqual(code, 0)
        appels = [a[0] for a in self.lanceur.appels]
        self.assertEqual(appels, [self.racine("--json", *self.base()),
                                  ["python3", "-m", "sesame.compilation", "--directe", DOSSIER],
                                  self.racine("--json", *self.base(), "--paquets", PAQUETS)])
        self.assertIn("== Sauvegarde", sortie)
        self.assertNotIn("pkexec", appels[1])  # la compilation n'est jamais root

    def test_deja_compile_reprend_les_paquets_sans_recompiler(self):
        self.compilation.compile = True
        self.lanceur.sorties = [FIN]
        code, _, _ = self.main("rejoindre", "--compte", ADRESSE, "--nom-machine", "PC-Charles")
        self.assertEqual(code, 0)
        self.assertEqual([a[0] for a in self.lanceur.appels], [self.racine("--json", *self.base(), "--paquets", PAQUETS)])

    def test_compilation_par_la_file_gagarine(self):
        self.compilation.file = ["gagarine", "file", "himmelblau compilation", "6", "4", "--", "python3"]
        self.lanceur.sorties = [COMPILATION_REQUISE, FIN]
        self.main("rejoindre", "--compte", ADRESSE, "--nom-machine", "pc")
        self.assertEqual(self.lanceur.appels[1][0], self.compilation.file)

    def test_compilation_en_echec(self):
        class Echoue(Lanceur):
            def __call__(self, cmd, input=None, text=None, stdout=None):
                res = super().__call__(cmd, input, text, stdout)
                res.returncode = 1 if cmd[0] == "python3" else 0
                return res
        self.lanceur = Echoue(sorties=[COMPILATION_REQUISE])
        code, _, erreur = self.main("rejoindre", "--compte", ADRESSE, "--nom-machine", "pc")
        self.assertEqual(code, 1)
        self.assertEqual(len(self.lanceur.appels), 2)  # pas de seconde commande root
        self.assertIn("compilation", erreur)

    def test_echec_de_la_preparation_pas_de_compilation(self):
        self.lanceur.code = 1
        self.lanceur.sorties = [COMPILATION_REQUISE]
        self.assertEqual(self.main("rejoindre", "--compte", ADRESSE, "--nom-machine", "pc")[0], 1)
        self.assertEqual(len(self.lanceur.appels), 1)

    def test_adresse_en_minuscules(self):
        self.lanceur.sorties = [FIN]
        self.main("rejoindre", "--compte", ADRESSE.upper(), "--nom-machine", "pc")
        self.assertIn(ADRESSE, self.lanceur.appels[0][0])

    def test_questions_posees_et_defauts(self):
        self.lanceur.sorties = [FIN]
        reponses = iter([ADRESSE, ""])
        invites = []
        self.main("rejoindre", saisie=lambda p: invites.append(p) or next(reponses))
        self.assertEqual(len(invites), 2)
        self.assertIn("Adresse pro", invites[0])
        self.assertIn("[pc-bureau]", invites[1])  # nom d'hôte sans domaine proposé
        self.assertEqual(self.lanceur.appels[0][0], self.racine("--json", *self.base("pc-bureau")))

    def test_adresse_proposee_depuis_la_configuration(self):
        self.lanceur.sorties = [FIN]
        self.defauts.compte = ADRESSE
        invites = []
        self.main("rejoindre", "--nom-machine", "pc", saisie=lambda p: invites.append(p) or "")
        self.assertIn(f"[{ADRESSE}]", invites[0])
        self.assertIn(ADRESSE, self.lanceur.appels[0][0])

    def test_une_seule_question_si_un_seul_manque(self):
        self.lanceur.sorties = [FIN]
        invites = []
        self.main("rejoindre", "--compte", ADRESSE, saisie=lambda p: invites.append(p) or "mon-pc")
        self.assertEqual(len(invites), 1)
        self.assertIn("Nom de la machine", invites[0])
        self.assertIn("mon-pc", self.lanceur.appels[0][0])

    def test_plus_de_jeton(self):
        self.lanceur.sorties = [FIN]
        self.main("rejoindre", "--compte", ADRESSE, "--nom-machine", "pc", mot_de_passe=self.pas_de_question)
        for argv in (["depot"], ["rejoindre", "--jeton", "x"]):
            with self.assertRaises(SystemExit), redirect_stderr(io.StringIO()):
                cli.main(argv, object())

    def test_valeurs_invalides_en_option(self):
        for argv in (["--compte", "pas-une-adresse", "--nom-machine", "pc"],
                     ["--compte", ADRESSE, "--nom-machine", "nom invalide!"],
                     ["--compte", ADRESSE, "--nom-machine", "12345"]):
            code, _, erreur = self.main("rejoindre", *argv)
            self.assertEqual(code, 2, argv)
            self.assertIn("invalide", erreur)
        self.assertEqual(self.lanceur.appels, [])

    def test_valeur_invalide_redemandee(self):
        self.lanceur.sorties = [FIN]
        reponses = iter(["pas-une-adresse", ADRESSE])
        _, _, erreur = self.main("rejoindre", "--nom-machine", "pc", saisie=lambda p: next(reponses))
        self.assertIn("invalide", erreur)
        self.assertIn(ADRESSE, self.lanceur.appels[0][0])

    def test_compte_local_est_l_utilisateur_courant(self):
        self.lanceur.sorties = [FIN]
        self.main("rejoindre", "--compte", ADRESSE, "--nom-machine", "pc", utilisateur=lambda: "marie")
        self.assertEqual(self.lanceur.appels[0][0][-2:], ["--compte-local", "marie"])

    def test_authentification_annulee(self):
        self.lanceur.code = 126
        code, _, erreur = self.main("rejoindre", "--compte", ADRESSE, "--nom-machine", "pc")
        self.assertEqual(code, 126)
        self.assertIn("Authentification annulée", erreur)

    def test_jamais_sudo(self):
        self.lanceur.sorties = [FIN]
        self.main("rejoindre", "--compte", ADRESSE, "--nom-machine", "pc")
        self.assertNotIn("sudo", self.lanceur.appels[0][0])


class TestEtapes(BaseCli):
    def test_outils(self):
        self.main("outils")
        self.assertEqual(self.lanceur.appels[0][0], cli.commande_racine(["outils"]))

    def test_compiler_sous_l_utilisateur(self):
        code, sortie, _ = self.main("compiler")
        self.assertEqual(code, 0)
        cmd, entree = self.lanceur.appels[0]
        self.assertEqual(cmd, ["python3", "-m", "sesame.compilation", "--directe", DOSSIER])
        self.assertNotIn("pkexec", cmd)
        self.assertIn("30 à 60", sortie)

    def test_compiler_par_la_file(self):
        self.compilation.file = ["gagarine", "file", "x", "6", "4", "--", "y"]
        self.main("compiler")
        self.assertEqual(self.lanceur.appels[0][0], self.compilation.file)

    def test_installer_avec_les_paquets_compiles(self):
        self.main("installer")
        self.assertEqual(self.lanceur.appels[0][0], cli.commande_racine(["installer", "--paquets", PAQUETS]))

    def test_mettre_a_jour_deja_a_jour(self):
        self.compilation._a_jour = True
        code, sortie, _ = self.main("mettre-a-jour")
        self.assertEqual(code, 0)
        self.assertIn("Himmelblau est à jour", sortie)
        self.assertEqual(self.lanceur.appels, [])

    def test_mettre_a_jour_compile_puis_installe(self):
        self.main("mettre-a-jour")
        appels = [a[0] for a in self.lanceur.appels]
        self.assertEqual(appels, [["python3", "-m", "sesame.compilation", "--directe", DOSSIER],
                                  cli.commande_racine(["installer", "--paquets", PAQUETS])])

    def test_mettre_a_jour_force(self):
        self.compilation._a_jour = True
        self.main("mettre-a-jour", "--forcer")
        self.assertEqual(len(self.lanceur.appels), 2)

    def test_mettre_a_jour_compilation_en_echec(self):
        self.lanceur.code = 1
        self.assertEqual(self.main("mettre-a-jour")[0], 1)
        self.assertEqual(len(self.lanceur.appels), 1)

    def test_secours_demande_deux_fois_le_mot_de_passe(self):
        reponses = iter(["motdepasse1", "motdepasse1"])
        invites = []
        code, _, _ = self.main("secours", mot_de_passe=lambda p: invites.append(p) or next(reponses))
        self.assertEqual(code, 0)
        self.assertEqual(len(invites), 2)
        cmd, entree = self.lanceur.appels[0]
        self.assertEqual(cmd, cli.commande_racine(["secours", "--nom", "secours"]))
        self.assertEqual(entree, "motdepasse1\n")
        self.assertNotIn("motdepasse1", " ".join(cmd))

    def test_secours_nom_personnalise(self):
        self.main("secours", "--nom", "depannage", mot_de_passe=lambda p: "motdepasse1")
        self.assertEqual(self.lanceur.appels[0][0][-2:], ["--nom", "depannage"])

    def test_secours_mots_de_passe_differents_ou_courts(self):
        for reponses in (["motdepasse1", "autre-chose"], ["court", "court"]):
            it = iter(reponses)
            code, _, _ = self.main("secours", mot_de_passe=lambda p: next(it))
            self.assertEqual(code, 1)
        self.assertEqual(self.lanceur.appels, [])

    def test_secours_copier_le_mot_de_passe_actuel(self):
        code, _, _ = self.main("secours", "--copier", mot_de_passe=self.pas_de_question)
        self.assertEqual(code, 0)
        cmd, entree = self.lanceur.appels[0]
        self.assertEqual(cmd, cli.commande_racine(["secours", "--nom", "secours"]))
        self.assertEqual(entree, "\n")

    def test_nom_machine(self):
        self.main("nom-machine", "PC-Charles", saisie=self.pas_de_question)
        self.assertEqual(self.lanceur.appels[0][0], cli.commande_racine(["nom-machine", "--nom", "PC-Charles"]))

    def test_nom_machine_demande_si_absent(self):
        invites = []
        self.main("nom-machine", saisie=lambda p: invites.append(p) or "")
        self.assertIn("[pc-bureau]", invites[0])
        self.assertEqual(self.lanceur.appels[0][0][-2:], ["--nom", "pc-bureau"])

    def test_nom_machine_invalide(self):
        code, _, erreur = self.main("nom-machine", "mauvais-")
        self.assertEqual(code, 2)
        self.assertIn("invalide", erreur)
        self.assertEqual(self.lanceur.appels, [])

    def test_configurer(self):
        self.main("configurer", "--compte", ADRESSE, saisie=self.pas_de_question)
        self.assertEqual(self.lanceur.appels[0][0],
                         cli.commande_racine(["configurer", "--compte", ADRESSE, "--compte-local", "charles-gamligo"]))

    def test_configurer_compte_local_et_question(self):
        invites = []
        self.main("configurer", "--compte-local", "marie", saisie=lambda p: invites.append(p) or ADRESSE)
        self.assertEqual(len(invites), 1)
        self.assertEqual(self.lanceur.appels[0][0][-4:], ["--compte", ADRESSE, "--compte-local", "marie"])

    def test_premiere_connexion_note_et_explique(self):
        code, sortie, _ = self.main("premiere-connexion")
        self.assertEqual(code, 0)
        self.assertIn("PIN", sortie)
        self.assertEqual(self.lanceur.appels[0][0][-1], "noter-premiere-connexion")

    def test_verifier(self):
        controles = [(True, "himmelblaud actif"), (False, "user-map manquant")]
        with mock.patch.object(cli.verification, "controler", create=True, return_value=controles), \
                mock.patch.object(cli.cfg, "charger", create=True, return_value=None):
            code, sortie, _ = self.main("verifier")
        self.assertEqual(code, 1)
        self.assertIn("✓ himmelblaud actif", sortie)
        self.assertIn("✗ user-map manquant", sortie)
        self.assertEqual(self.lanceur.appels, [])
        with mock.patch.object(cli.verification, "controler", create=True, return_value=controles[:1]), \
                mock.patch.object(cli.cfg, "charger", create=True, return_value=None):
            self.assertEqual(self.main("verifier")[0], 0)


if __name__ == "__main__":
    unittest.main()
