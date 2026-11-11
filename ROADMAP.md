# Sésame — feuille de route

Connexion à Ubuntu par Microsoft Entra ID (authd), avec reprise du compte local. Conception : [docs/conception-1.0.0.md](docs/conception-1.0.0.md).

## Phase 1 — Conception

- [x] Étude d'authd et du module `authd-msentraid` (doc Canonical), relevé du poste (Ubuntu 24.04, GDM X11, domaine AD, compte local UID 1000)
- [x] Scripts manuels éprouvés (`~/Desktop/entra-id/`), base de la logique
- [x] Dépôt git flow (`main`, `develop`, `feature/sesame-1.0.0`)
- [x] Conception 1.0.0 : étapes, reprise et annulation, assistant root, polkit, interface, paquet

## Phase 2 — Cœur et assistant root

- [x] `sesame/systeme.py` : accès au système sous une racine, commandes, processus, NSS
- [x] `sesame/config.py` : `sesame.conf`, valeurs détectées, validation, `broker.conf`
- [x] `sesame/etapes.py` : détection sans root des 8 étapes, étape suivante
- [x] Actions root : sauvegarde, secours, quitter l'AD, installer, configurer, désactiver
- [x] Reprise du compte (maintenant et au démarrage) et annulation automatique ou manuelle
- [x] `sesame/verification.py`, `sesame/guide.py`
- [x] `sesame-racine` (JSON ligne par ligne) et la commande `sesame`
- [x] Tests unitaires du cœur (racine temporaire, commandes simulées, pannes à chaque étape de la reprise)

## Phase 3 — Assistant graphique

- [x] Fenêtre GTK 4 + libadwaita : compte Entra, étapes, journal, bandeau
- [x] Dialogues : secours, première connexion, reprise, guide du portail, vérification, à propos
- [x] Lancement asynchrone de `pkexec sesame-racine --json`
- [x] Fichier `.desktop`, metainfo, icônes, page de manuel, capture d'écran
- [x] Test de l'interface

## Phase 4 — Paquet, dépôt APT, site, documentation

- [x] `debian/`, `Makefile`, `scripts/build-deb.sh` (tests, lintian, SHA256SUMS)
- [x] Politique polkit, service `sesame-reprise.service`, page de manuel `sesame.8`
- [x] Clé de signature « Sésame APT (mawena) », `data/apt/`, `scripts/publier-apt.sh`
- [x] Site (page d'accueil, `installer.sh`)
- [x] `README.md`, `CHANGELOG.md`, `LICENSE`

## Phase 5 — Intégration

- [x] Tests complets par la file Gagarine
- [x] Construction du `.deb`, lintian sans erreur ni avertissement
- [ ] Installation sur le poste (`pkexec`), `sesame etat` et l'assistant sur le vrai système

## Phase 6 — Release 1.0.0

- [x] Lien SSH du dépôt, `origin`, dépôt GitHub (« About » : site + dépôt APT)
- [x] Release git flow 1.0.0, CHANGELOG, tag `v1.0.0`, push de `main`, `develop` et des tags
- [x] Release GitHub avec le `.deb` et `SHA256SUMS`
- [x] Publication dans le dépôt APT, vérification par `apt-get update` sans root

## Phase 7 — Mise en place sur le poste de Charles

- [ ] Application « Ubuntu authd » créée dans le portail Entra (Charles)
- [ ] Étapes 1 à 5 avec l'assistant
- [ ] Première connexion Entra
- [ ] Reprise du compte au démarrage, puis vérification
