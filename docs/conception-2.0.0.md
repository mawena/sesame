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

Paquets : dépôt **stable** sur abonnement (choix de l'utilisateur, 11/11/2026). Le jeton d'abonnement (Open
Collective, envoyé par e-mail, un par branche ; on prend la 4.x) donne
`https://repo.himmelblau-idm.org/<JETON>/himmelblau/v_4/deb/ubuntu noble main`, clé
`https://packages.himmelblau-idm.org/himmelblau.asc`. Les deux hôtes répondent depuis le réseau du poste (Launchpad et
le Snap Store, eux, sont bloqués).

## Ce que voit l'utilisateur

1. `sesame-assistant` : une page **« Rejoindre Microsoft Entra ID »** avec **Adresse pro**, **Nom de la machine**
   (prérempli, nom actuel sans domaine) et, tant que le dépôt Himmelblau n'est pas configuré, **Jeton d'abonnement
   Himmelblau** (champ masqué, lien « Obtenir un jeton » vers https://himmelblau-idm.org/stable-repositories/).
   Bouton **Rejoindre**.
2. **Une** fenêtre polkit (mot de passe Ubuntu actuel), puis tout s'enchaîne avec la progression affichée.
3. Page finale : « Le poste NOM est prêt. Déconnectez-vous, choisissez votre compte à l'écran d'accueil, tapez le mot
   de passe Entra de ADRESSE et validez sur le téléphone. Le poste sera inscrit dans Entra à cette première connexion,
   puis vous choisirez un code PIN (Windows Hello) pour les connexions suivantes. » Bouton **Se déconnecter**.
4. Menu : **Détails** (liste des étapes et leur état, chacune relançable), **Vérifier**, **Désactiver la connexion
   Entra** (retour à la connexion locale seule), **À propos**.

Ligne de commande : `sesame rejoindre [--compte ADRESSE] [--nom-machine NOM]` (jeton demandé sans écho s'il le faut),
`sesame etat`, `sesame verifier`, `sesame desactiver`, et les étapes une par une.

## Décisions

- **Version 2.0.0** : changement incompatible (authd remplacé, options `--locataire`, `--client`, `--connexion`,
  reprise de compte et guide du portail retirés).
- **Paquets installés** : `himmelblau pam-himmelblau nss-himmelblau` ; `himmelblau-apparmor` en plus si AppArmor est
  présent (échec toléré). Pas `himmelblau-sso`, `o365`, `himmelblau-qr-greeter`. Les paquets configurent eux-mêmes PAM
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
- **Dépôt** : clé téléchargée, désarmurée par `gpg --dearmor` dans `/etc/apt/keyrings/himmelblau.gpg` ; source deb822
  `/etc/apt/sources.list.d/himmelblau.sources` (`Signed-By:`), mode 0640 (le jeton est un secret ; apt lit les sources
  en root). Avant d'écrire, Sésame vérifie le jeton en lisant
  `…/v_4/deb/ubuntu/dists/noble/main/binary-amd64/Packages.gz` : 401/403 → « jeton refusé », 404 → « pas de paquets
  pour Ubuntu 24.04 », réseau → « le dépôt Himmelblau ne répond pas ». Le jeton passe à `sesame-racine` par l'entrée
  standard, jamais en argument, et n'est jamais écrit dans un journal.
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

`sesame etat --json` → `{"version", "etapes": [{"id", "titre", "explication", "statut", "detail"}…], "suivante"}`
(la clé `derniere_reprise` disparaît). Statuts inchangés (`a_faire`, `fait`, `sans_objet`, `programmee`, `bloquee`,
`inconnu`). Identifiants, dans l'ordre :

| id | titre | fait quand |
|----|-------|-----------|
| `sauvegarde` | Sauvegarder la configuration | une sauvegarde existe |
| `secours` | Créer le compte de secours | le compte de secours existe et est dans `sudo` |
| `nom_machine` | Nommer la machine | `sesame.conf` a `nom_machine` et `/etc/hostname` vaut ce nom (sinon `a_faire`) |
| `quitter_ad` | Quitter le domaine Active Directory | plus aucun domaine (`sans_objet` s'il n'y en a jamais eu) |
| `depot` | Ajouter le dépôt Himmelblau | `/etc/apt/sources.list.d/himmelblau.sources` existe |
| `installer` | Installer Himmelblau | paquets `himmelblau`, `pam-himmelblau`, `nss-himmelblau` installés |
| `configurer` | Relier votre compte à Entra | `himmelblau.conf` a `domain` et `user_map_file`, `user-map` relie le compte local, `himmelblaud` actif |
| `premiere_connexion` | Première connexion | notée dans `etat.json` (`noter-premiere-connexion`), sinon `a_faire` avec la marche à suivre |

### `sesame-racine` (root, par pkexec ; `--json` = un événement par ligne, comme en 1.x)

```
sesame-racine [--json] etat
sesame-racine [--json] rejoindre --compte ADRESSE --nom-machine NOM [--compte-local NOM]   # jeton éventuel sur stdin
sesame-racine [--json] sauvegarde [--motif M]
sesame-racine [--json] secours [--nom secours]            # mot de passe sur stdin ; vide = copie du mot de passe actuel
sesame-racine [--json] nom-machine --nom NOM
sesame-racine [--json] quitter-ad
sesame-racine [--json] depot                               # jeton sur stdin
sesame-racine [--json] installer
sesame-racine [--json] configurer --compte ADRESSE [--compte-local NOM]
sesame-racine [--json] noter-premiere-connexion
sesame-racine [--json] desactiver
```

`rejoindre` valide tout avant de modifier quoi que ce soit, puis enchaîne sauvegarde, secours, nom de la machine,
sortie du domaine, dépôt (si absent ; jeton obligatoire alors), installation (si un paquet manque), configuration ;
chaque étape annoncée par `systeme.etape(...)` et sautée si déjà faite ; relancer reprend où on s'était arrêté.

### Modules

- `sesame/himmelblau.py` (nouveau, fonctions pures et constantes) : `CLE_URL`, `DEPOT_RACINE =
  "https://repo.himmelblau-idm.org/{jeton}/himmelblau/v_4"`, `SOURCE`, `TROUSSEAU`, `CONFIG`, `USER_MAP`, `PAQUETS`,
  `valider_jeton(jeton)` (`[A-Za-z0-9_-]{8,}`, ni « public » ni « basic »), `texte_source(jeton)`,
  `url_controle(jeton)`, `texte_config(existant, domaine, user_map)`, `texte_user_map(existant, local, adresse)`,
  `retirer_user_map(existant, local)`, `domaine(adresse)`, `masquer(texte, jeton)`.
- Retirés : `reprise.py`, `guide.py` (et leurs tests), `data/systemd/sesame-reprise.service`, la configuration authd de
  `config.py`/`actions.py`/`verification.py`.
- `sesame/config.py` : `Config(compte, compte_local, uid, gid, dossier, secours, nom_machine)` ; `valider_upn`,
  `valider_nom`, `valider_nom_machine`, `normaliser_upn`, `defauts`, `charger`, `ecrire`.
- `sesame/verification.py` : contrôles (himmelblaud actif, NSS `himmelblau` dans passwd et group, `pam_himmelblau`
  dans `/etc/pam.d/common-auth`, `user-map` relie le compte, `aad-tool status` si disponible, nom d'hôte).

### Interface et ligne de commande

- L'interface lance `pkexec sesame-racine --json rejoindre …` par le lanceur existant, jeton éventuel sur stdin, et lit
  `etat --json` pour savoir si le champ jeton doit apparaître (étape `depot` à faire).
- `sesame rejoindre` : même enchaînement, jeton demandé par `getpass` si l'étape `depot` est à faire.

## Tests

Machine simulée de `tests/commun.py` (apt-get, dpkg-query, hostnamectl, `/etc/shadow`, `chpasswd -e`, `gpg --dearmor`,
`pam-auth-update`, `systemctl`, téléchargements par une fonction injectable) ; aucun accès réseau. Tous les tests
passent par la file Gagarine.
