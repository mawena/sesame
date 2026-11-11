# Journal des modifications

Toutes les modifications notables de ce projet sont consignées ici.

Le format suit [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/), et le projet respecte le
[versionnage sémantique](https://semver.org/lang/fr/).

## [Non publié]

## [2.0.2] - 2026-11-11

### Corrigé

- **Installation sans question de dpkg** : `apt-get install` passe `--force-confdef --force-confold`. Avant,
  `himmelblau-apparmor` restait à moitié installé (« iU ») parce que dpkg demandait quoi faire de
  `/etc/apparmor.d/local/usr.sbin.cupsd`, que cups crée vide, et que personne ne pouvait répondre sous pkexec ; chaque
  `apt` suivant échouait. Un fichier de configuration vide (ou fait de commentaires) prend maintenant la version du
  paquet ; un fichier modifié est gardé et la version du paquet est posée en `.dpkg-dist`, avec un avertissement.
- Un paquet Himmelblau resté à moitié installé est réparé (`dpkg --configure -a`) avant l'installation ; si
  `himmelblau-apparmor` ne peut toujours pas être configuré, il est retiré pour ne pas bloquer apt.
- **Quitter l'AD arrête aussi les sockets de SSSD** (`sssd-nss`, `sssd-pam`, `sssd-pam-priv`, `sssd-autofs`,
  `sssd-pac`, `sssd-ssh`, `sssd-sudo`) et efface leur état d'échec : ils échouaient à chaque démarrage.
- **Un seul dossier personnel** : se connecter en tapant l'adresse pro ouvrait la session dans un nouveau dossier vide
  (`/home/<adresse>` → `/home/<UUID>`, créé depuis `/etc/skel`). `himmelblau.conf` reçoit `home_attr = SPN` et
  `home_alias = UUID`, et `/home/<adresse>` devient un lien vers le dossier du compte local ; un dossier déjà créé par
  Himmelblau est renommé `<dossier>.avant-sesame-<date>`, jamais supprimé. « Désactiver » retire ce lien, et l'étape
  « Configurer » n'est faite que si le lien est en place (relancer « Rejoindre » le corrige).
- Le texte de première connexion signale que le trousseau GNOME (« Connexion ») reste chiffré avec l'ancien mot de passe
  local : il se change dans « Mots de passe et clés ».

## [2.0.1] - 2026-11-11

### Corrigé

- La compilation de Himmelblau lancée par la file Gagarine échouait (« No module named 'sesame' ») : la commande transmet
  désormais toujours `PYTHONPATH`, car le processus lancé n'hérite pas du `sys.path` de l'assistant.
- « Rejoindre » reprend les paquets de Himmelblau déjà compilés au lieu de tout recompiler.

## [2.0.0] - 2026-11-11

### Modifié

- **Passage à Himmelblau** : Sésame relie le poste à Microsoft Entra ID comme un PC Windows, sans application ni ID à
  créer dans Entra. Le compte local est gardé tel quel (UID, dossier, groupes) et relié au compte Entra par le
  `user_map_file` de Himmelblau ; le poste est inscrit dans Entra à la première connexion, puis un code PIN (Windows
  Hello) est choisi. Version majeure : changement incompatible.
- **Assistant simplifié** : une seule page « Rejoindre Microsoft Entra ID » (adresse pro et nom de la machine), la
  progression affichée, puis la marche à suivre pour la première connexion.
- `sesame etat --json` : la clé `derniere_reprise` disparaît ; les étapes deviennent `sauvegarde`, `secours`,
  `nom_machine`, `quitter_ad`, `outils`, `compiler`, `installer`, `configurer`, `premiere_connexion`.
- Himmelblau (branche **stable-4.x**) est **compilé sur le poste**, sous l'utilisateur, par podman : gratuit, sans
  abonnement (voie « self-built » de l'installateur officiel), puis installé par root. Environ 30 à 60 minutes, ~6 Go de
  RAM, ~10 Go de disque, par la file Gagarine si elle est présente.

### Ajouté

- `sesame rejoindre [--compte ADRESSE] [--nom-machine NOM]` : prépare le poste (root), compile Himmelblau sous
  l'utilisateur, puis l'installe et le configure (root).
- `sesame compiler` et `sesame mettre-a-jour [--forcer]` (recompile si la branche stable a avancé, puis réinstalle) ;
  « Mettre à jour Himmelblau » dans le menu de l'assistant.
- Étapes `nom-machine`, `outils`, `compiler` et `premiere-connexion` ; option `--copier` de `sesame secours` (reprend le mot de
  passe Ubuntu actuel).
- Vérification, après l'installation, que PAM, NSS et GDM sont bien configurés par les paquets Himmelblau.

### Retiré

- authd et son module Entra (snap `authd-msentraid`).
- L'ID du locataire et l'ID client, et le guide de création de l'application dans le portail Entra
  (`sesame portail`).
- Le mode de connexion (`--connexion`, `mot-de-passe` ou `code`) et les groupes redonnés (`--groupes`).
- La reprise du compte local par le compte Entra (`sesame reprise`, `sesame annuler-reprise`) et l'unité
  `sesame-reprise.service`.

## [1.1.0] - 2026-11-11

### Ajouté

- Connexion **comme sur Windows** : adresse pro, mot de passe Entra, puis double authentification (Microsoft
  Authenticator, code) ou méthode sans mot de passe, grâce au flux « Entra authentication » d'authd 0.7.0 et du module
  Entra 0.5.0. C'est le mode par défaut ; le poste est inscrit dans Entra à la première connexion
  (`register_device = true`).
- Réglage `connexion` (`mot-de-passe` ou `code`) dans `sesame.conf`, option `--connexion` de `sesame configurer`, et
  choix « Connexion » dans l'assistant. Le code sur le téléphone reste proposé en secours.
- Le guide du portail Entra décrit l'URI de redirection, l'inscription des appareils, la double authentification, AD FS
  et l'accès conditionnel.

### Modifié

- L'étape « Installer » met à jour le module Entra déjà installé (`snap refresh`) et affiche les versions d'authd et du
  module ; elle prévient s'ils sont trop anciens pour la connexion par mot de passe.
- L'étape « Configurer » refuse la connexion par mot de passe avec des versions trop anciennes, et repasse à faire
  quand le mode de connexion change (une installation faite en 1.0.0 passe ainsi au mode mot de passe en la relançant).
- La fenêtre de première connexion explique le mode choisi.

## [1.0.0] - 2026-11-11

Première version : Sésame branche un poste Ubuntu 24.04+ sur Microsoft Entra ID avec authd, puis le compte Entra reprend
le compte local existant.

### Ajouté

- **Étapes idempotentes**, dans un ordre fixe, chacune avec une détection sans root et une action root : sauvegarde,
  compte de secours, sortie du domaine Active Directory, installation d'authd (PPA `ubuntu-enterprise-desktop/authd`) et
  du snap `authd-msentraid`, configuration de la connexion Entra, première connexion, reprise du compte local,
  vérification.
- **Reprise du compte local par le compte Entra** : UID, GID, dossier personnel, groupes supplémentaires, crontab,
  `subuid`/`subgid`, unités systemd et réglages qui citaient l'ancien compte ; au prochain démarrage (recommandé, par
  `sesame-reprise.service`, avant toute session et avant les services qui tournent sous le compte local) ou
  tout de suite.
- **Annulation** automatique en cas d'échec, et à la main (`sesame annuler-reprise`) ; `sesame desactiver` coupe la
  connexion Entra sans rien désinstaller.
- **Sauvegardes** dans `/var/lib/sesame/sauvegardes` avant chaque étape qui modifie quelque chose, conservées à la purge
  du paquet.
- **Assistant graphique** `sesame-assistant` (GTK 4 + libadwaita) : état de chaque étape, champs préremplis par
  détection, guide de création de l'application dans le portail Entra, journal en direct.
- **Commande** `sesame` (`etat`, `sauvegarde`, `secours`, `quitter-ad`, `installer`, `configurer`, `reprise`,
  `annuler-reprise`, `desactiver`, `verifier`, `portail`, `version`) et **assistant root** `sesame-racine`, seul
  programme lancé par pkexec (action polkit `io.github.mawena.sesame.racine`).
- **Paquet Debian** `sesame_1.0.0_all.deb`, pages de manuel `sesame(8)` et `sesame-assistant(1)`, **dépôt APT signé**
  (`https://mawena.github.io/sesame/apt`, clé dédiée) : le paquet ajoute sa source et sa clé, `apt upgrade` suffit
  ensuite ; site `https://mawena.github.io/sesame/` et `installer.sh`.
- `sesame-reprise.service` n'est jamais activé ni démarré par l'installation du paquet.
