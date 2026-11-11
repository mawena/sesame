# Journal des modifications

Toutes les modifications notables de ce projet sont consignées ici.

Le format suit [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/), et le projet respecte le
[versionnage sémantique](https://semver.org/lang/fr/).

## [Non publié]

Première version : Sésame branche un poste Ubuntu 24.04+ sur Microsoft Entra ID avec authd, puis le compte Entra reprend
le compte local existant.

### Ajouté

- **Étapes idempotentes**, dans un ordre fixe, chacune avec une détection sans root et une action root : sauvegarde,
  compte de secours, sortie du domaine Active Directory, installation d'authd (PPA `ubuntu-enterprise-desktop/authd`) et
  du snap `authd-msentraid`, configuration de la connexion Entra, première connexion, reprise du compte local,
  vérification.
- **Reprise du compte local par le compte Entra** : UID, GID, dossier personnel, groupes supplémentaires, crontab,
  `subuid`/`subgid`, unités systemd et réglages qui citaient l'ancien compte ; au prochain démarrage (recommandé, par
  `sesame-reprise.service`, avant toute session) ou tout de suite.
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
