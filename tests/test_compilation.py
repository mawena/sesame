"""Compilation de Himmelblau : commandes simulées, dossiers temporaires, ni réseau ni podman réels."""
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from sesame import compilation as c
from sesame.systeme import ErreurSesame

HASH = "a" * 40
HASH2 = "b" * 40
DEBS = ["himmelblau_4.0.1_amd64.deb", "pam-himmelblau_4.0.1_amd64.deb", "nss-himmelblau_4.0.1_amd64.deb",
        "himmelblau-sso_4.0.1_amd64.deb"]


class Faux:
    """`lancer` simulé : enregistre les commandes, crée de faux .deb au `podman run`."""

    def __init__(self, commit=HASH, distant=HASH, debs=DEBS, echecs=None, absents=()):
        self.appels = []
        self.commit = commit
        self.distant = distant
        self.debs = debs
        self.echecs = echecs or {}   # préfixe d'argv (tuple) -> (code, sortie)
        self.absents = set(absents)

    def __call__(self, argv, cwd=None, rappel=None):
        self.appels.append((list(argv), cwd))
        if argv[0] in self.absents:
            raise FileNotFoundError(argv[0])
        for prefixe, rep in self.echecs.items():
            if tuple(argv[:len(prefixe)]) == prefixe:
                return rep
        sortie = ""
        if argv[:2] == ["git", "ls-remote"]:
            sortie = f"{self.distant}\trefs/heads/{c.BRANCHE}\n" if self.distant else ""
        elif argv[:2] == ["git", "clone"]:
            Path(argv[-1], ".git").mkdir(parents=True)
        elif argv[:2] == ["git", "rev-parse"]:
            sortie = self.commit + "\n"
        elif argv[:2] == ["podman", "run"]:
            cible = Path(cwd, "target", c.CIBLE, "debian")
            cible.mkdir(parents=True, exist_ok=True)
            for d in self.debs:
                (cible / d).write_bytes(b"deb")
            sortie = "Finished release\n"
        if rappel:
            for l in sortie.splitlines():
                rappel(l)
        return 0, sortie

    def verbes(self):
        return [" ".join(a[:2]) for a, _ in self.appels]


class Base(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.dossier = str(Path(t.name) / "sesame" / "himmelblau")


class TestOutils(Base):
    def test_dossier_par_defaut(self):
        with mock.patch.dict(os.environ, {"XDG_DATA_HOME": "/x/donnees"}):
            self.assertEqual(c.dossier_par_defaut(), "/x/donnees/sesame/himmelblau")
        env = {k: v for k, v in os.environ.items() if k != "XDG_DATA_HOME"}
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertTrue(c.dossier_par_defaut().endswith("/.local/share/sesame/himmelblau"))

    def test_constantes(self):
        self.assertEqual(c.BRANCHE, "stable-4.x")
        self.assertEqual(c.PAQUETS, ("himmelblau", "pam-himmelblau", "nss-himmelblau"))
        self.assertEqual((c.RAM_GO, c.COEURS), (6, 4))

    def test_lancer_reel_relaie_les_lignes(self):
        vu = []
        code, sortie = c.lancer([sys.executable, "-c", "print('a'); print('b')"], rappel=vu.append)
        self.assertEqual((code, vu, sortie), (0, ["a", "b"], "a\nb"))

    def test_commit_distant(self):
        f = Faux()
        self.assertEqual(c.commit_distant(f), HASH)
        self.assertEqual(f.appels[0][0], ["git", "ls-remote", c.DEPOT_GIT, "refs/heads/stable-4.x"])
        self.assertIsNone(c.commit_distant(Faux(distant="")))
        self.assertIsNone(c.commit_distant(Faux(echecs={("git",): (128, "fatal")})))
        self.assertIsNone(c.commit_distant(Faux(absents=["git"])))


class TestCompiler(Base):
    def test_premier_clone(self):
        f = Faux()
        etapes, lignes = [], []
        e = c.compiler(self.dossier, f, rappel=lignes.append, etape=etapes.append, coeurs=3)
        self.assertEqual(f.verbes(), ["git clone", "git rev-parse", "python3 scripts/gen_dockerfiles.py",
                                      "podman build", "podman run"])
        clone = f.appels[0][0]
        self.assertEqual(clone, ["git", "clone", "--depth", "1", "--branch", "stable-4.x", c.DEPOT_GIT, self.dossier])
        build = f.appels[3][0]
        self.assertEqual(build, ["podman", "build", "-t", c.IMAGE, "-f", "images/Dockerfile.ubuntu24.04", "."])
        run = f.appels[4][0]
        self.assertNotIn("-it", run)
        self.assertIn("CARGO_BUILD_JOBS=3", run)
        self.assertIn("label=disable", run)
        self.assertIn(f"{self.dossier}:/himmelblau", run)
        self.assertIn(f"{self.dossier}/target/ubuntu24.04:/himmelblau/target", run)
        self.assertEqual(run[-1], c.IMAGE)
        self.assertEqual(etapes, ["Téléchargement du code de Himmelblau (stable-4.x)",
                                  "Préparation du conteneur de compilation",
                                  "Compilation (environ 30 à 60 min)", "Paquets prêts"])
        self.assertIn("Finished release", lignes)
        self.assertTrue(e["compile"])
        self.assertEqual(e["commit"], HASH)
        self.assertEqual(sorted(e["paquets"]), sorted(["himmelblau", "pam-himmelblau", "nss-himmelblau",
                                                       "himmelblau-sso"]))
        donnees = json.loads(Path(self.dossier, "packaging", c.FICHIER_ETAT).read_text())
        self.assertEqual(donnees["commit"], HASH)
        self.assertIn("T", donnees["date"])

    def test_mise_a_jour(self):
        Path(self.dossier, ".git").mkdir(parents=True)
        pack = Path(self.dossier, "packaging")
        pack.mkdir()
        (pack / "himmelblau_3.0.0_amd64.deb").write_bytes(b"vieux")
        f = Faux(commit=HASH2)
        e = c.compiler(self.dossier, f)
        self.assertEqual(f.verbes()[:3], ["git fetch", "git reset", "git rev-parse"])
        self.assertEqual(f.appels[0][0], ["git", "fetch", "--depth", "1", "origin", "stable-4.x"])
        self.assertEqual(f.appels[1][0], ["git", "reset", "--hard", "FETCH_HEAD"])
        self.assertFalse((pack / "himmelblau_3.0.0_amd64.deb").exists())
        self.assertEqual(e["commit"], HASH2)

    def test_paquets_manquants(self):
        f = Faux(debs=["himmelblau_4.0.1_amd64.deb"])
        with self.assertRaises(ErreurSesame) as cm:
            c.compiler(self.dossier, f)
        self.assertIsInstance(cm.exception, c.ErreurCompilation)
        self.assertIn("pam-himmelblau", str(cm.exception))
        self.assertIn("nss-himmelblau", str(cm.exception))
        self.assertFalse(c.etat(self.dossier)["compile"])

    def test_podman_absent(self):
        for absent in ("podman", "git"):
            with self.assertRaises(c.ErreurCompilation) as cm:
                c.compiler(self.dossier + absent, Faux(absents=[absent]))
            self.assertIn(absent, str(cm.exception))
            self.assertIn("Installer les outils de compilation", str(cm.exception))

    def test_podman_code_127(self):
        f = Faux(echecs={("podman", "build"): (127, "podman: not found")})
        with self.assertRaises(c.ErreurCompilation) as cm:
            c.compiler(self.dossier, f)
        self.assertIn("Installer les outils de compilation", str(cm.exception))

    def test_echec_reseau(self):
        cas = [(("git", "clone"), "fatal: unable to access 'https://github.com/': Could not resolve host: github.com"),
               (("podman", "build"), "Error: pinging container registry registry-1.docker.io: dial tcp: no such host"),
               (("podman", "run"), "error: failed to download from `https://index.crates.io/config.json`")]
        for prefixe, texte in cas:
            with self.subTest(prefixe=prefixe):
                f = Faux(echecs={prefixe: (1, texte)})
                with self.assertRaises(c.ErreurCompilation) as cm:
                    c.compiler(self.dossier + "-" + prefixe[1], f)
                self.assertIn("réseau", str(cm.exception))
                self.assertIn(texte.splitlines()[-1], str(cm.exception))

    def test_echec_compilation_garde_les_dernieres_lignes(self):
        sortie = "\n".join(f"ligne {i}" for i in range(100)) + "\nerror[E0432]: unresolved import"
        f = Faux(echecs={("podman", "run"): (1, sortie)})
        with self.assertRaises(c.ErreurCompilation) as cm:
            c.compiler(self.dossier, f)
        m = str(cm.exception)
        self.assertIn("unresolved import", m)
        self.assertIn("ligne 99", m)
        self.assertNotIn("ligne 10\n", m)
        self.assertNotIn("réseau", m)


class TestEtat(Base):
    def test_vide(self):
        self.assertEqual(c.etat(self.dossier), {"compile": False, "commit": "", "date": "", "paquets": {}})

    def test_apres_compilation_et_a_jour(self):
        c.compiler(self.dossier, Faux())
        e = c.etat(self.dossier)
        self.assertTrue(e["compile"])
        self.assertEqual(e["paquets"]["himmelblau"], "himmelblau_4.0.1_amd64.deb")
        self.assertTrue(c.a_jour(self.dossier, Faux(distant=HASH)))
        self.assertFalse(c.a_jour(self.dossier, Faux(distant=HASH2)))
        self.assertFalse(c.a_jour(self.dossier, Faux(distant="")))

    def test_deb_disparu_ou_fichier_invalide(self):
        c.compiler(self.dossier, Faux())
        Path(self.dossier, "packaging", "nss-himmelblau_4.0.1_amd64.deb").unlink()
        e = c.etat(self.dossier)
        self.assertFalse(e["compile"])
        self.assertNotIn("nss-himmelblau", e["paquets"])
        self.assertFalse(c.a_jour(self.dossier, Faux()))
        Path(self.dossier, "packaging", c.FICHIER_ETAT).write_text("pas du json")
        self.assertFalse(c.etat(self.dossier)["compile"])


class TestCommandes(Base):
    def test_commande_file_avec_gagarine(self):
        cmd = c.commande_file(self.dossier, quoi=lambda n: "/usr/bin/gagarine")
        self.assertEqual(cmd[:7], ["gagarine", "file", "himmelblau compilation", "6", "4", "--", cmd[6]])
        self.assertIn("sesame.compilation", cmd)
        self.assertIn("--directe", cmd)
        self.assertEqual(cmd[-2:], ["--dossier", self.dossier])

    def test_commande_file_sans_gagarine(self):
        self.assertIsNone(c.commande_file(self.dossier, quoi=lambda n: None))

    def test_commande_directe_pythonpath(self):
        parent = str(Path(c.__file__).resolve().parent.parent)
        with mock.patch.object(sys, "path", ["/autre"]), mock.patch.dict(os.environ, {"PYTHONPATH": ""}):
            cmd = c.commande_directe(self.dossier)
        self.assertEqual(cmd[:2], ["env", f"PYTHONPATH={parent}"])
        self.assertEqual(cmd[2:], [sys.executable, "-m", "sesame.compilation", "--directe", "--dossier", self.dossier])
        # Même quand sys.path ou PYTHONPATH le contiennent déjà : le processus lancé ne voit pas le sys.path.
        with mock.patch.object(sys, "path", [parent]), mock.patch.dict(os.environ, {"PYTHONPATH": parent}):
            self.assertEqual(c.commande_directe(self.dossier)[:2], ["env", f"PYTHONPATH={parent}"])
        with mock.patch.dict(os.environ, {"PYTHONPATH": "/x"}):
            self.assertEqual(c.commande_directe(self.dossier)[1], f"PYTHONPATH={parent}{os.pathsep}/x")


class TestMain(Base):
    def lancer_main(self, argv, f=None, quoi=lambda n: None):
        sortie = io.StringIO()
        code = c.main(argv, lancer_=f or Faux(), sortie=sortie, quoi=quoi)
        return code, sortie.getvalue()

    def test_json(self):
        code, texte = self.lancer_main(["--directe", "--json", "--dossier", self.dossier])
        self.assertEqual(code, 0)
        evts = [json.loads(l) for l in texte.splitlines()]
        types = [e["type"] for e in evts]
        self.assertEqual(types[0], "etape")
        self.assertIn("sortie", types)
        self.assertEqual(types[-1], "fin")
        self.assertTrue(evts[-1]["ok"])
        self.assertEqual(evts[-1]["commit"], HASH)
        self.assertEqual(evts[0]["texte"], "Téléchargement du code de Himmelblau (stable-4.x)")

    def test_json_echec(self):
        code, texte = self.lancer_main(["--directe", "--json", "--dossier", self.dossier], Faux(absents=["podman"]))
        self.assertEqual(code, 1)
        fin = json.loads(texte.splitlines()[-1])
        self.assertEqual((fin["type"], fin["ok"]), ("fin", False))
        self.assertIn("outils de compilation", fin["message"])

    def test_texte_simple(self):
        code, texte = self.lancer_main(["--directe", "--dossier", self.dossier])
        self.assertEqual(code, 0)
        self.assertIn("== Compilation (environ 30 à 60 min)", texte)

    def test_sans_directe_passe_par_la_file(self):
        f = Faux()
        code, _ = self.lancer_main(["--dossier", self.dossier], f, quoi=lambda n: "/usr/bin/gagarine")
        self.assertEqual(code, 0)
        self.assertEqual(f.appels[0][0][:2], ["gagarine", "file"])
        self.assertEqual(len(f.appels), 1)

    def test_sans_directe_sans_gagarine_compile(self):
        f = Faux()
        code, _ = self.lancer_main(["--dossier", self.dossier], f)
        self.assertEqual(code, 0)
        self.assertIn("podman run", f.verbes())

    def test_verifier_a_jour(self):
        c.compiler(self.dossier, Faux())
        code, texte = self.lancer_main(["--verifier-a-jour", "--json", "--dossier", self.dossier], Faux(distant=HASH))
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(texte)["a_jour"])
        code, texte = self.lancer_main(["--verifier-a-jour", "--dossier", self.dossier], Faux(distant=HASH2))
        self.assertEqual(code, 10)
        self.assertIn("nouvelle version", texte)
        code, _ = self.lancer_main(["--verifier-a-jour", "--dossier", self.dossier], Faux(distant=""))
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
