# Sésame 2.0.0 — rejoindre Entra comme un PC Windows, avec Himmelblau

Suite de [conception-1.1.0.md](conception-1.1.0.md). La 1.2.0 envisagée (authd + création automatique d'une
application dans Entra) est abandonnée : authd exige un ID client (`client ID is required` dans
`brokers/internal/broker/broker.go`), donc une application à créer dans Entra, alors que Windows n'en demande aucune.

## Pourquoi Himmelblau

[Himmelblau](https://himmelblau-idm.org) (libre, soutenu par SUSE ; authd réutilise sa bibliothèque pour la
connexion par mot de passe) a un mode Entra natif **sans application ni ID** : il passe par les applications de
Microsoft, comme Windows, et retrouve le locataire à partir du domaine de l'adresse. Il inscrit le poste dans Entra à
la première connexion (sous le nom d'hôte), et **`user_map_file`** relie un compte local existant à un compte Entra :
`charles-gamligo` garde son UID, son dossier et ses réglages et se connecte avec l'adresse pro, le mot de passe Entra
et la validation sur le téléphone. Plus de reprise de compte, plus de redémarrage, plus de compte Entra séparé.

Paquets : **branche stable `stable-4.x` compilée sur le poste**, gratuite (choix de l'utilisateur, 11/11/2026 :
« je veux un truc gratuit » ; le dépôt stable est payant, la version de développement trop risquée). C'est la voie
gratuite prévue par l'installateur officiel (`curl -fsSL https://himmelblau-idm.org/install | sh`, « self-built ») :
`git clone --branch stable-4.x https://github.com/himmelblau-idm/himmelblau.git`, puis la recette `ubuntu24.04` du
`Makefile` (conteneur podman `ubuntu:24.04` + `cargo deb`), qui dépose les `.deb` dans `packaging/`. GitHub, Docker Hub,
crates.io et l'archive Ubuntu répondent depuis le réseau du poste (Launchpad et le Snap Store, eux, sont bloqués).

## Ce que voit l'utilisateur

1. `sesame-assistant` : une page **« Rejoindre Microsoft Entra ID »** avec **Adresse pro** et **Nom de la machine**
   (prérempli, nom actuel sans domaine). Bouton **Rejoindre**.
2. Fenêtre polkit (mot de passe Ubuntu actuel) : préparation (sauvegarde, secours, nom, sortie du domaine, outils de
   compilation). Puis **compilation de Himmelblau** sous l'utilisateur, sans root, par la file Gagarine si `gagarine`
   est présent (« environ 30 à 60 min », progression et journal affichés ; la fenêtre peut rester ouverte ou être
   fermée : la compilation continue et Sésame reprend où il en est). Puis seconde fenêtre polkit : installation et
   configuration.
3. Page finale : « Le poste NOM est prêt. Déconnectez-vous, choisissez votre compte à l'écran d'accueil, tapez le mot
   de passe Entra de ADRESSE et validez sur le téléphone. Le poste sera inscrit dans Entra à cette première connexion,
   puis vous choisirez un code PIN (Windows Hello) pour les connexions suivantes. » Bouton **Se déconnecter**.
4. Menu : **Détails** (liste des étapes et leur état, chacune relançable), **Vérifier**, **Désactiver la connexion
   Entra** (retour à la connexion locale seule), **À propos**.

Ligne de commande : `sesame rejoindre [--compte ADRESSE] [--nom-machine NOM]`, `sesame compiler`,
`sesame mettre-a-jour` (recompile si la branche stable a avancé, puis réinstalle), `sesame etat`, `sesame verifier`,
`sesame desactiver`, et les étapes une par une. Menu de l'assistant : **Mettre à jour Himmelblau** en plus.

## Décisions

- **Version 2.0.0** : changement incompatible (authd remplacé, options `--locataire`, `--client`, `--connexion`,
  reprise de compte et guide du portail retirés).
- **Paquets installés** : `himmelblau pam-himmelblau nss-himmelblau` pris dans `packaging/` (vérifiés par
  `dpkg-deb -f … Package`) ; `himmelblau-apparmor` en plus s'il a été construit et qu'AppArmor est présent (échec
  toléré). Pas `himmelblau-sso`, `o365`, `himmelblau-qr-greeter`. Les paquets configurent eux-mêmes PAM
  (`pam-auth-update`, profil prioritaire avec `ignore_unknown_user`), NSS (`update-nss add`) et GDM ; Sésame le
  **vérifie** après coup et le signale s'il manque quelque chose.
- **`/etc/himmelblau/himmelblau.conf`**, section `[global]`, en gardant le reste du fichier : `domain = <domaine de
  l'adresse>`, `user_map_file = /etc/himmelblau/user-map`. `enable_hello` reste à sa valeur par défaut (PIN après la
  première connexion, comme Windows ; sans lui, chaque connexion et chaque déverrouillage demanderaient le téléphone).
  Copie `.sesame-origine` du fichier d'origine.
- **`/etc/himmelblau/user-map`** : une ligne `<compte local>:<adresse>` (remplace une ligne existante pour ce compte
  local). Compte local : celui qui a lancé Sésame (`uid_appelant()`, UID ≥ 1000 dans `/etc/passwd`), sinon
  `cfg.defauts`.
- **Services** : `systemctl enable --now himmelblaud himmelblaud-tasks`, puis `systemctl restart` après la
  configuration.
- **Outils** (root) : `apt-get install -y podman uidmap git make` ; vérifie que le compte local a une plage dans
  `/etc/subuid` et `/etc/subgid` (sinon `usermod --add-subuids 100000-165535 --add-subgids 100000-165535`).
- **Compilation** (`sesame/compilation.py`, sous l'utilisateur, jamais root) : dossier
  `~/.local/share/sesame/himmelblau` (clone `--depth 1 --branch stable-4.x`, sinon `git fetch` + `reset --hard
  origin/stable-4.x`) ; `python3 scripts/gen_dockerfiles.py --out ./images/` ; `podman build -t
  sesame-himmelblau-ubuntu24.04 -f images/Dockerfile.ubuntu24.04 .` ; `podman run --rm --security-opt label=disable -e
  CARGO_BUILD_JOBS=<cœurs> -v SRC:/himmelblau -v SRC/target/ubuntu24.04:/himmelblau/target
  sesame-himmelblau-ubuntu24.04` (sans `-it` : pas de terminal) ; les `.deb` de `target/ubuntu24.04/debian/` vont dans
  `packaging/` (vidé avant). Fichier `packaging/sesame-compilation.json` : commit, date, paquets. Avec `gagarine` :
  `gagarine file "himmelblau compilation" 6 4 -- python3 -m sesame.compilation --directe …` (6 Go annoncés,
  `CARGO_BUILD_JOBS=4`) ; sans : directement avec `CARGO_BUILD_JOBS=4`. Progression : lignes de sortie relayées.
  « À jour » = commit distant (`git ls-remote … refs/heads/stable-4.x`) égal au commit compilé.
- **Compte de secours** : créé s'il manque, avec le mot de passe Ubuntu actuel (empreinte de `/etc/shadow` copiée par
  `chpasswd -e`) ; empreinte inutilisable (`!`, `*`, vide) → erreur claire. Le mot de passe local de `charles-gamligo`
  reste valable aussi (PAM essaie Himmelblau puis `pam_unix`).
- **Nom de la machine** : 1–15 caractères `[A-Za-z0-9-]`, ni tiret au début ou à la fin, pas uniquement des
  chiffres ; `hostnamectl hostname NOM` ; ligne `127.0.1.1` de `/etc/hosts` remplacée ou ajoutée ; casse gardée.
- **Désactiver** : retire la ligne du compte de `user-map`, `pam-auth-update --disable himmelblau` (nom du profil lu
  dans `/usr/share/pam-configs/`), arrête les services ; rien n'est désinstallé. « Rejoindre » rétablit tout.
- **Mise à jour depuis la 1.x** : `sesame.conf` 1.x lu sans erreur (clés inconnues ignorées) ; l'unité
  `sesame-reprise.service` disparaît du paquet (jamais activée par défaut) ; si `/var/lib/sesame/reprise-programmee`
  existe, il est retiré par `postinst`.

## Contrats

### Étapes (`sesame/etapes.py`, détection sans root, même structure JSON que la 1.x)

(Le tableau ci-dessous remplace l'étape `depot` par `outils` et `compiler` ; `sesame.conf` garde
`dossier_compilation`, le dossier de compilation de l'utilisateur.)

`sesame etat --json` → `{"version", "etapes": [{"id", "titre", "explication", "statut", "detail"}…], "suivante"}`
(la clé `derniere_reprise` disparaît). Statuts inchangés (`a_faire`, `fait`, `sans_objet`, `programmee`, `bloquee`,
`inconnu`). Identifiants, dans l'ordre :

| id | titre | fait quand |
|----|-------|-----------|
| `sauvegarde` | Sauvegarder la configuration | une sauvegarde existe |
| `secours` | Créer le compte de secours | le compte de secours existe et est dans `sudo` |
| `nom_machine` | Nommer la machine | `sesame.conf` a `nom_machine` et `/etc/hostname` vaut ce nom (sinon `a_faire`) |
| `quitter_ad` | Quitter le domaine Active Directory | plus aucun domaine (`sans_objet` s'il n'y en a jamais eu) |
| `outils` | Installer les outils de compilation | `podman`, `uidmap`, `git`, `make` installés |
| `compiler` | Compiler Himmelblau | `packaging/sesame-compilation.json` existe dans `dossier_compilation` avec les trois paquets (ou Himmelblau déjà installé : `fait`) |
| `installer` | Installer Himmelblau | paquets `himmelblau`, `pam-himmelblau`, `nss-himmelblau` installés |
| `configurer` | Relier votre compte à Entra | `himmelblau.conf` a `domain` et `user_map_file`, `user-map` relie le compte local, `himmelblaud` actif |
| `premiere_connexion` | Première connexion | notée dans `etat.json` (`noter-premiere-connexion`), sinon `a_faire` avec la marche à suivre |

### `sesame-racine` (root, par pkexec ; `--json` = un événement par ligne, comme en 1.x)

```
sesame-racine [--json] etat
sesame-racine [--json] rejoindre --compte ADRESSE --nom-machine NOM [--compte-local NOM] [--paquets DOSSIER]
sesame-racine [--json] sauvegarde [--motif M]
sesame-racine [--json] secours [--nom secours]            # mot de passe sur stdin ; vide = copie du mot de passe actuel
sesame-racine [--json] nom-machine --nom NOM
sesame-racine [--json] quitter-ad
sesame-racine [--json] outils
sesame-racine [--json] installer --paquets DOSSIER        # les .deb compilés
sesame-racine [--json] configurer --compte ADRESSE [--compte-local NOM]
sesame-racine [--json] noter-premiere-connexion
sesame-racine [--json] desactiver
```

`rejoindre` valide tout avant de modifier quoi que ce soit, puis enchaîne sauvegarde, secours, nom de la machine,
sortie du domaine, outils ; ensuite, si Himmelblau n'est pas installé et que `--paquets` ne contient pas les trois
paquets, il s'arrête en réussite avec l'événement `{"type": "compilation_requise"}` et le message « Préparation
terminée : Himmelblau doit maintenant être compilé. » ; sinon installation puis configuration. Chaque étape est
annoncée par `systeme.etape(...)` et sautée si déjà faite ; relancer reprend où on s'était arrêté. L'interface et
`sesame rejoindre` font : `rejoindre` → compilation (utilisateur) → `rejoindre --paquets DOSSIER`.

### Modules

- `sesame/himmelblau.py` (nouveau, fonctions pures et constantes) : `CONFIG`, `USER_MAP`, `PAQUETS`,
  `PAQUETS_OPTIONNELS = ("himmelblau-apparmor",)`, `OUTILS = ("podman", "uidmap", "git", "make")`,
  `texte_config(existant, domaine, user_map)`, `texte_user_map(existant, local, adresse)`,
  `retirer_user_map(existant, local)`, `domaine(adresse)`, `debs_dans(noms_de_fichiers)` (choisit, pour chaque paquet
  voulu, le `.deb` correspondant).
- `sesame/compilation.py` (nouveau, côté utilisateur) : `DEPOT_GIT`, `BRANCHE = "stable-4.x"`,
  `dossier_par_defaut()`, `commit_distant(lancer)`, `etat(dossier)` (compilé ? commit ? paquets ?), `a_jour(dossier,
  lancer)`, `compiler(dossier, lancer, rappel, coeurs=4)`, `commande_file(dossier)` (la commande `gagarine file …` ou
  `None`), `main(argv)` pour `python3 -m sesame.compilation`.
- Retirés : `reprise.py`, `guide.py` (et leurs tests), `data/systemd/sesame-reprise.service`, la configuration authd de
  `config.py`/`actions.py`/`verification.py`.
- `sesame/config.py` : `Config(compte, compte_local, uid, gid, dossier, secours, nom_machine)` ; `valider_upn`,
  `valider_nom`, `valider_nom_machine`, `normaliser_upn`, `defauts`, `charger`, `ecrire`.
- `sesame/verification.py` : contrôles (himmelblaud actif, NSS `himmelblau` dans passwd et group, `pam_himmelblau`
  dans `/etc/pam.d/common-auth`, `user-map` relie le compte, `aad-tool status` si disponible, nom d'hôte).

### Interface et ligne de commande

- L'interface lance `pkexec sesame-racine --json rejoindre …`, puis, sur `compilation_requise`, la compilation
  (`commande_file` ou `python3 -m sesame.compilation --directe`, sorties relayées au journal, étape « Compiler
  Himmelblau » en cours), puis `pkexec sesame-racine --json rejoindre … --paquets DOSSIER`.
- `sesame rejoindre` : même enchaînement dans le terminal.

## Tests

Machine simulée de `tests/commun.py` (apt-get, dpkg-query, dpkg-deb, hostnamectl, `/etc/shadow`, `chpasswd -e`,
`pam-auth-update`, `systemctl`, usermod) ; compilation avec un `lancer` simulé (git, podman) ; aucun accès réseau. Tous les tests
passent par la file Gagarine.
