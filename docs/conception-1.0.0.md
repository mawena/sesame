# Sésame 1.0.0 — conception

Suite : [Sésame 1.1.0 — connexion par mot de passe](conception-1.1.0.md).

Sésame branche un poste **Ubuntu Desktop 24.04 ou plus récent** sur **Microsoft Entra ID**, en s'appuyant sur
**authd** (Canonical) et son module `authd-msentraid` (snap). Ensuite, le compte Entra **reprend le compte local
existant** : même UID, même dossier personnel, mêmes groupes, même crontab. L'utilisateur retrouve son bureau, mais
s'y connecte avec son compte de l'entreprise.

Il remplace les scripts manuels `~/Desktop/entra-id/*.sh` (11/11/2026), dont il reprend la logique éprouvée.

Deux interfaces partagent le même cœur :

- `sesame-assistant` : assistant graphique GTK 4 + libadwaita, qui détecte l'état de chaque étape et propose la
  suivante ;
- `sesame` : la même chose en ligne de commande.

Les actions qui touchent au système passent par un **assistant root unique**, `/usr/libexec/sesame/sesame-racine`,
lancé par `pkexec` (polkit). L'utilisateur saisit son mot de passe dans la fenêtre d'authentification d'Ubuntu.

Doc d'authd : <https://ubuntu.com/docs/authd/stable-docs/> (installation, configuration, `authctl`).

## Objectifs, limites

- Le paquet est **idempotent** : chaque étape détecte si elle est déjà faite, et on peut la relancer sans risque.
- Le paquet n'est **jamais destructeur sans retour** : avant chaque étape qui modifie quelque chose, une sauvegarde est
  faite. La reprise du compte s'annule automatiquement si elle échoue, et aussi à la main (`sesame annuler-reprise`).
- La reprise du compte se fait de préférence **au prochain démarrage**, par un service systemd qui tourne avant
  l'écran de connexion et avant toute session : à ce moment, aucun programme ne tourne sous l'un des deux comptes.
- Le paquet est **générique** : rien n'est propre à un poste ou à une entreprise. Les valeurs (domaine AD, compte local, groupes,
  UPN suggéré) sont détectées sur le poste et modifiables.
- Le paquet ne fait pas : la création de l'application dans le portail Entra (il l'explique pas à pas, avec un lien
  vers le portail) ; l'inscription de l'appareil dans Entra (`register_device = false`) ; plusieurs comptes Entra
  (seul le propriétaire, `allowed_users = OWNER`).
- Aucun secret n'est stocké : l'ID du locataire et l'ID client ne sont pas des secrets. Le mot de passe du compte de
  secours passe par l'entrée standard de l'assistant root et n'est jamais écrit.

## Fichiers et chemins

| Chemin | Rôle |
|---|---|
| `/usr/bin/sesame` | ligne de commande |
| `/usr/bin/sesame-assistant` | assistant graphique |
| `/usr/libexec/sesame/sesame-racine` | assistant root (seul programme lancé par pkexec) |
| `/usr/share/sesame/sesame/` | paquet Python (les lanceurs ajoutent `/usr/share/sesame` à `sys.path`, comme Gagarine) |
| `/etc/sesame/sesame.conf` | réglages (INI, 0644), écrit par l'étape `configurer` |
| `/var/lib/sesame/etat.json` | ce que Sésame a fait et quand (0644, lisible sans root, sans secret) |
| `/var/lib/sesame/sauvegardes/AAAAMMJJ-HHMMSS[-motif]/` | sauvegardes (dossier 0700) |
| `/var/lib/sesame/reprise-programmee` | présent = reprise au prochain démarrage (JSON des paramètres, 0600) |
| `/var/lib/sesame/reprise-etat.json` | état d'une reprise en cours, pour l'annuler (0600) |
| `/var/lib/sesame/derniere-reprise.json` | résultat de la dernière reprise : `{"ok", "message", "date", "mode"}` (0644) |
| `/usr/lib/systemd/system/sesame-reprise.service` | reprise au démarrage |
| `/usr/share/polkit-1/actions/io.github.mawena.sesame.policy` | action `io.github.mawena.sesame.racine` |
| `/usr/share/applications/io.github.mawena.Sesame.desktop`, metainfo, icônes `io.github.mawena.Sesame` | bureau |
| `/etc/apt/sources.list.d/sesame.sources`, `/usr/share/keyrings/sesame.gpg` | dépôt APT du projet |

Pour les tests, le cœur prend une **racine** de système de fichiers (`Systeme(racine=…)`) : tous les chemins
ci-dessus et ceux de `/etc`, `/home`, `/proc`, `/var/spool/cron` sont lus et écrits sous cette racine. Les commandes
externes passent par une seule méthode, que les tests remplacent pour enregistrer les appels sans les exécuter.

### `/etc/sesame/sesame.conf`

```ini
[entra]
locataire = 00000000-0000-0000-0000-000000000000   ; ID de l'annuaire (tenant)
client = 00000000-0000-0000-0000-000000000000      ; ID d'application (client)
compte = prenom.nom@entreprise.com                 ; UPN, toujours en minuscules

[local]
compte = charles-gamligo        ; compte local que le compte Entra reprendra
uid = 1000                      ; noté à la configuration (le compte local disparaît à la reprise)
gid = 1000
dossier = /home/charles-gamligo
secours = secours               ; compte local administrateur de dépannage

[groupes]
supplementaires = sudo,lpadmin,adm,docker   ; groupes locaux redonnés au compte Entra (owner_extra_groups)
```

Valeurs par défaut proposées (détection, `config.defauts(systeme)`) :

- compte local : l'utilisateur qui lance l'assistant (`PKEXEC_UID`, `SUDO_USER` ou l'utilisateur courant), sinon le
  premier compte de `/etc/passwd` dont l'UID est entre 1000 et 59999 ;
- groupes : les groupes supplémentaires de ce compte qui existent dans `/etc/group` ;
- UPN suggéré : `<compte local avec « - » remplacé par « . »>@<domaine AD>` si le poste est dans un domaine
  (`realm list --name-only`), sinon vide.

Validation : `valider_guid(texte)` (8-4-4-4-12 hexadécimal) ; `valider_upn(texte)` (`partie@domaine.tld`, sans espace,
mis en minuscules).

## Les étapes

L'ordre est fixe. Chaque étape a un identifiant stable, un titre, une détection **sans root** et une action **root**.
La détection renvoie un statut parmi `a_faire`, `fait`, `sans_objet`, `programmee`, `bloquee` (une étape précédente
manque ; le détail dit laquelle) et `inconnu`.

| # | id | Titre | Détection (sans root) | Action (root) |
|---|---|---|---|---|
| 1 | `sauvegarde` | Sauvegarder la configuration | `etat.json` mentionne une sauvegarde | copie `--parents` de `/etc/passwd`, `shadow`, `group`, `gshadow`, `subuid`, `subgid`, `nsswitch.conf`, `login.defs`, `krb5.conf`, `sssd/`, `pam.d/`, `gdm3/`, `systemd/system/*.service`, `vmware/hostd/authorization.xml`, `/var/lib/AccountsService`, plus la crontab du compte local |
| 2 | `secours` | Créer le compte de secours | le compte existe dans `/etc/passwd` et est dans `sudo` | `useradd -m -s /bin/bash -c "Compte de secours (Sésame)" -G sudo <secours>`, puis `chpasswd` avec le mot de passe lu sur l'entrée standard (une ligne) ; si le compte existe, seulement l'ajout à `sudo` et, si un mot de passe est fourni, son changement |
| 3 | `quitter_ad` | Quitter le domaine Active Directory | `sans_objet` si aucun domaine (`realm list --name-only` vide) et pas de `sss` dans `nsswitch.conf` ; `fait` si plus de domaine mais trace dans `etat.json` | pour chaque domaine : `realm leave -v <domaine>` (local, sans `--remove`) ; `systemctl disable --now sssd` ; vider `/var/lib/sss/db/*.ldb` et `/var/lib/sss/mc/*` ; `pam-auth-update --disable sss` ; retirer `sss` des lignes `passwd`, `group`, `shadow`, `netgroup`, `services`, `sudoers`, `automount` de `nsswitch.conf` ; archiver en `.tar.gz` (dans la sauvegarde) puis supprimer `/home/<UPN>` s'il existe (ancien dossier AD du même nom) |
| 4 | `installer` | Installer authd et le module Entra | paquet `authd` installé (`dpkg-query`) et snap `authd-msentraid` présent (`snap list`) | refuse si la version d'Ubuntu est inférieure à 24.04 ; en 24.04 : `add-apt-repository -y ppa:ubuntu-enterprise-desktop/authd` ; puis `apt-get update`, `apt-get install -y authd gnome-shell yaru-theme-gnome-shell`, `snap install authd-msentraid` |
| 5 | `configurer` | Configurer la connexion Entra | `/etc/authd/brokers.d/msentraid.conf` existe, `sesame.conf` contient locataire et client, et le service du module est actif | écrit `sesame.conf` ; copie `/snap/authd-msentraid/current/conf/authd/msentraid.conf` dans `/etc/authd/brokers.d/` ; garde `broker.conf.origine` puis écrit `/var/snap/authd-msentraid/current/broker.conf` (modèle ci-dessous) ; `LOGIN_TIMEOUT` porté à 300 s s'il est plus bas ; ajoute `authd` aux lignes `passwd`, `group`, `shadow` de `nsswitch.conf` s'il manque ; redémarre `authd` et `snap.authd-msentraid.authd-msentraid.service` |
| 6 | `premiere_connexion` | Première connexion par Entra | `fait` si `getent passwd <UPN>` répond et que l'UPN n'est pas dans `/etc/passwd` | aucune : l'assistant explique la connexion à l'écran d'accueil et propose de fermer la session |
| 7 | `reprise` | Reprendre le compte local | `fait` si le compte Entra a l'UID et le dossier du compte local et que celui-ci n'est plus dans `/etc/passwd` ; `programmee` si `reprise-programmee` existe | voir « Reprise » ; modes `--au-demarrage` (recommandé) et `--maintenant` |
| 8 | `verification` | Vérifier | toujours `a_faire` jusqu'à un passage réussi noté dans `etat.json` | aucune action root : liste de contrôles (voir « Vérification ») |

Actions en plus : `annuler-reprise` ; `desactiver` (supprime `/etc/authd/brokers.d/msentraid.conf` et redémarre
`authd`, ce qui coupe la connexion Entra sans rien désinstaller ; `configurer` la rétablit) ; `etat` (JSON).

### `broker.conf` écrit

```ini
# Module Microsoft Entra ID pour authd — écrit par Sésame. Original : broker.conf.origine
[oidc]
issuer = https://login.microsoftonline.com/<locataire>/v2.0
client_id = <client>

[users]
allowed_users = OWNER
owner = <UPN>
home_base_dir = /home
owner_extra_groups = <groupes>

[msentraid]
register_device = false

[flows]
entra_auth = false
```

### Reprise du compte local par le compte Entra

Paramètres : compte local `A` (UID `U`, GID `G`, dossier `H`), compte Entra `N` (UPN), compte de secours.

**Préconditions** (aucune modification si l'une manque, message clair) : `A` est dans `/etc/passwd` avec l'UID `U` ;
`H` existe ; `N` est résolu par NSS (`getent`), n'est pas dans `/etc/passwd`, et son UID `NU` est différent de `U` ;
son dossier `NH` est différent de `H` ; `authctl` est présent ; aucun processus ne tourne sous `U` ni sous `NU`
(lecture de `/proc/*/status`) ; en mode `--maintenant`, l'appelant (`PKEXEC_UID` ou `SUDO_UID`) n'est pas `U`.

**Séquence** :

1. sauvegarde `avant-reprise` (comme l'étape 1) et crontab de `A` dans la sauvegarde ;
2. écriture de `reprise-etat.json` : `A`, `N`, `U`, `G`, `H`, `NU`, `NG` (GID du groupe privé de `N`), `NH`, horodatage,
   chemin de la sauvegarde ;
3. `userdel A` (sans `-r`) ; `groupdel A` s'il reste ; suppression de `/var/spool/cron/crontabs/A` ;
4. `authctl user set-uid N U` puis `authctl group set-gid N G` (authctl met à jour le propriétaire du dossier neuf `NH`) ;
5. `authctl user set-home` déplace le contenu de l'ancien dossier quand il existe. On écarte donc les deux dossiers
   pour qu'il ne change que l'enregistrement : `mv H H.sesame-reprise` ; `mv NH <sauvegarde>/dossier-entra-vierge` s'il
   existe ; `authctl user set-home N H` ; `mv H.sesame-reprise H` ;
6. réglages qui citaient `A` : `/etc/subuid` et `/etc/subgid` (`A:` devient `U:`) ; tout `/etc/systemd/system/*.service`
   avec `User=A` ou `Group=A` (devient `U` / `G`, et une surcharge `<unité>.d/sesame-authd.conf` avec
   `After=authd.socket authd.service`) ; `/etc/vmware/hostd/authorization.xml` (`<ACEDataUser>A</ACEDataUser>` devient
   `N`) ; `/etc/gdm3/custom.conf` (`AutomaticLogin=A` est mis en commentaire) ; la crontab sauvegardée est installée
   pour `N` (`crontab -u N fichier`) ; `/var/lib/AccountsService/users/A` et `icons/A` sont copiés sous le nom `N`
   (chemin de l'icône corrigé) ;
7. `systemctl daemon-reload` ; `derniere-reprise.json` avec `ok: true` ; `reprise-etat.json` est renommé
   `reprise-etat.termine-<horodatage>.json`.

**Échec** : à partir de l'étape 3, toute erreur déclenche l'**annulation** automatique, et l'échec est noté dans
`derniere-reprise.json` avec le message.

**Annulation** (`annuler-reprise`, lit `reprise-etat.json`) : on ne laisse **jamais** authctl déplacer le contenu de
`H`.

1. Si `H` est absent et `H.sesame-reprise` présent, on remet `H.sesame-reprise` à sa place.
2. Si le dossier de `N` est `H` : `mv H H.sesame-reprise`, puis `authctl user set-home N NH` (`NH` ne doit pas exister),
   puis `mv H.sesame-reprise H`.
3. On remet le dossier vierge sauvegardé en `NH`.
4. On vérifie que le dossier de `N` n'est plus `H`. Puis, si `N` a l'UID `U`, `authctl user set-uid N NU` ; si son
   groupe a le GID `G`, `authctl group set-gid N NG`.
5. On restaure, depuis la sauvegarde `avant-reprise`, les fichiers de `/etc` copiés.
6. On supprime les surcharges `sesame-authd.conf` et on réinstalle la crontab de `A`. On supprime celle de `N`.
7. `systemctl daemon-reload`. Enfin, `reprise-etat.json` est renommé `reprise-etat.annule-<horodatage>.json`.

**Au démarrage** : `sesame reprise --au-demarrage` vérifie les préconditions qui ne dépendent pas des processus, écrit
`reprise-programmee` (JSON des paramètres) et active `sesame-reprise.service`. Au démarrage suivant, le service tourne
une fois et fait trois choses : il supprime d'abord `reprise-programmee` (jamais de boucle), puis il lance la reprise
et l'annule si elle échoue. Enfin, il se désactive (`systemctl disable sesame-reprise.service`) et laisse le démarrage
continuer, réussite ou échec. `sesame reprise --annuler-programmation` retire le fichier et désactive le service.

Les services système qui tournent sous le compte local (`User=A` ou `User=U`, par exemple `cofidash.service`)
démarreraient en même temps que la reprise : celle-ci verrait alors des processus sous `U` et refuserait de se faire.
Pour l'éviter, la programmation écrit une surcharge `sesame-reprise.service.d/sesame-ordre.conf` avec
`Before=<ces services>`. La surcharge est retirée après l'exécution ou à l'annulation de la programmation.

```ini
[Unit]
Description=Sésame : reprise du compte local par le compte Entra
ConditionPathExists=/var/lib/sesame/reprise-programmee
After=local-fs.target authd.socket authd.service
Wants=authd.service
Before=systemd-user-sessions.service display-manager.service

[Service]
Type=oneshot
ExecStart=/usr/libexec/sesame/sesame-racine reprise --execution-demarrage
TimeoutStartSec=15min

[Install]
WantedBy=multi-user.target
```

### Vérification (sans root)

`sesame verifier` renvoie une liste de contrôles `(ok: bool, texte)` :

- l'utilisateur courant est `N` et son UID vaut `U` ;
- `$HOME` vaut `H` et lui appartient ;
- `N` fait partie de chaque groupe supplémentaire configuré ;
- une crontab existe si l'ancien compte en avait une ;
- `authd` et le service du module sont actifs ;
- `A` n'existe plus ;
- le compte de secours existe et est dans `sudo` ;
- chaque unité modifiée par la reprise est active si elle était activée.

Tant qu'on n'est pas connecté en tant que `N`, la vérification ne contrôle que la configuration et le dit. Un
passage réussi est noté dans `etat.json` par l'assistant root (`sesame-racine noter-verification`, sans autre effet).

## Assistant root : `/usr/libexec/sesame/sesame-racine`

```
sesame-racine [--json] ACTION [options]
  sauvegarde [--motif TEXTE]
  secours [--nom NOM]                       mot de passe (facultatif si le compte existe) : une ligne sur stdin
  quitter-ad
  installer
  configurer --locataire GUID --client GUID --compte UPN [--compte-local NOM] [--secours NOM] [--groupes a,b,c]
  reprise (--maintenant | --au-demarrage | --annuler-programmation | --execution-demarrage)
  annuler-reprise
  desactiver
  noter-verification
  etat
```

- Il refuse de tourner sans root (code 1, message).
- Sans `--json`, il écrit du texte lisible. Avec `--json`, il écrit **une ligne JSON par événement** sur stdout :
  - `{"type": "etape", "texte": "Sauvegarde de /etc"}` : début d'une sous-étape ;
  - `{"type": "commande", "texte": "apt-get install -y authd …"}` : commande lancée ;
  - `{"type": "sortie", "texte": "…"}` : sortie d'une commande, ligne par ligne ;
  - `{"type": "avertissement", "texte": "…"}` ;
  - `{"type": "fin", "ok": true, "message": "…"}` : toujours la dernière ligne.
- Code de sortie : 0 si tout va bien, 1 si l'action échoue, 2 en cas d'erreur d'usage.
- `etat` renvoie le même JSON que `sesame etat --json`, vu par root.

Polkit : action `io.github.mawena.sesame.racine`, `auth_admin` pour `allow_any` et `allow_inactive`,
`auth_admin_keep` pour `allow_active`, annotation `org.freedesktop.policykit.exec.path` =
`/usr/libexec/sesame/sesame-racine`.

## Ligne de commande : `sesame`

```
sesame [etat] [--json]            état des étapes (par défaut)
sesame sauvegarde | secours | quitter-ad | installer | configurer [...] | reprise [...] | annuler-reprise | desactiver
sesame verifier                    contrôles, sans root
sesame portail                     explique la création de l'application dans Entra (texte du guide)
sesame version
```

- Les actions root relancent `pkexec /usr/libexec/sesame/sesame-racine ACTION …`, ou l'appellent directement si l'on
  est déjà root. Depuis le dépôt, le chemin est `libexec/sesame-racine`.
- `sesame secours` demande le mot de passe deux fois (`getpass`) et le passe par stdin.
- `sesame configurer` demande les valeurs manquantes, en proposant les valeurs par défaut détectées.
- `sesame etat` affiche, pour chaque étape, une ligne avec un symbole (✓ fait, · à faire, – sans objet, ⏲ programmée,
  ✗ bloquée), son titre et le détail, puis « Étape suivante : … ».

## API du cœur, utilisée par l'assistant graphique et la ligne de commande

Les modules sont dans `sesame/`.

- `sesame.version.VERSION` : `"1.0.0"`.
- `sesame.systeme.Systeme(racine="/")` : accès au système (fichiers sous la racine, commandes, `/proc`, NSS).
- `sesame.config` :
  - `Config` (dataclass : `locataire`, `client`, `compte`, `compte_local`, `uid`, `gid`, `dossier`, `secours`,
    `groupes: list[str]`) ;
  - `charger(systeme) -> Config | None` ;
  - `defauts(systeme) -> Config` ;
  - `valider_guid` et `valider_upn` ;
  - `texte_broker(config) -> str`.
- `sesame.etapes` :
  - `ETAPES` : liste ordonnée d'objets avec `id`, `titre`, `explication` (2 ou 3 phrases pour l'utilisateur) et
    `action_racine` (nom de l'action de `sesame-racine`, ou `None`) ;
  - `lire_etat(systeme) -> list[dict]` : chaque élément vaut
    `{"id", "titre", "statut", "detail", "explication", "action"}` ;
  - `etape_suivante(etats) -> str | None` ;
  - `derniere_reprise(systeme) -> dict | None`.
- `sesame.verification.controler(systeme, config) -> list[tuple[bool, str]]`.
- `sesame.guide.PORTAIL` : les étapes du portail Entra, en texte structuré (liste de `(titre, détail)`). Le contenu
  vient de la feuille de route des scripts : inscription « Ubuntu authd », locataire unique, permissions Graph
  déléguées `openid`, `profile`, `offline_access`, `User.Read`, `GroupMember.Read.All`, consentement administrateur,
  « Autoriser les flux de clients publics », accès conditionnel qui bloquerait le code d'appareil.
  `sesame.guide.URL_PORTAIL = "https://entra.microsoft.com"`.
- `sesame.racine.main(argv) -> int` : assistant root (le lanceur `libexec/sesame-racine` l'appelle).
- `sesame.cli.main(argv) -> int`.

## Assistant graphique : `sesame-assistant`

`Adw.Application`, id `io.github.mawena.Sesame`, libadwaita ≥ 1.5. Une seule fenêtre (environ 720 × 820), qui
reste utilisable à 360 px de large.

- **En-tête** : titre « Sésame », bouton « Actualiser », menu principal avec « Guide du portail Entra », « Désactiver la
  connexion Entra », « Annuler la reprise » et « À propos » (`Adw.AboutDialog`, licence MIT, site
  `https://mawena.github.io/sesame/`).
- **Bandeau** (`Adw.Banner`) : l'étape suivante, ou « Tout est en place ». Après un démarrage avec reprise, il indique le
  résultat de `derniere-reprise.json`.
- **Groupe « Compte Microsoft Entra »** : `Adw.EntryRow` pour l'ID du locataire, l'ID client, le compte Entra (UPN) et
  le compte local, préremplis par `charger()` ou `defauts()`. La validation se fait en direct (classe `error`). Une
  rangée « Créer l'application dans le portail Entra » ouvre le guide (`Adw.Dialog` avec les étapes de
  `guide.PORTAIL` et un bouton qui ouvre `URL_PORTAIL`).
- **Groupe « Étapes »** : une `Adw.ActionRow` par étape, avec une icône de statut en préfixe, le titre, le détail en
  sous-titre et, en suffixe, un bouton « Lancer » ou « Refaire », ou un indicateur d'activité pendant l'action. Une
  étape `bloquee` a son bouton désactivé, avec une infobulle qui dit pourquoi.
  - `secours` : `Adw.AlertDialog` avec deux `Adw.PasswordEntryRow` qui doivent être identiques, 8 caractères minimum.
  - `configurer` : utilise les champs du groupe Entra ; il refuse si un champ est invalide.
  - `premiere_connexion` : dialogue qui explique la connexion (« Non listé ? », UPN, « Microsoft Entra ID », QR code
    ou code sur le téléphone, choix du mot de passe local), avec un bouton « Fermer la session »
    (`gnome-session-quit --logout`).
  - `reprise` : `Adw.AlertDialog` destructif qui dit ce qui va se passer. Il propose « Au prochain démarrage »
    (recommandé), puis « Redémarrer maintenant » (`systemctl reboot` via logind). Si l'assistant tourne sous un autre
    compte que le compte local, il propose aussi « Maintenant ».
  - `verification` : affiche la liste des contrôles dans un dialogue.
- **Groupe « Journal »** : `Adw.ExpanderRow` contenant un `Gtk.TextView` en police à chasse fixe, non éditable, qui
  reçoit les événements JSON de `sesame-racine`.
- Les actions lancent `pkexec /usr/libexec/sesame/sesame-racine --json …` avec `Gio.Subprocess` (stdin en tube pour le
  mot de passe). La lecture est asynchrone, ligne par ligne, et l'interface ne se bloque jamais. À la fin : un toast
  (`Adw.ToastOverlay`) et une actualisation de l'état. Un seul lancement à la fois.
- Si pkexec est annulé (code 126 ou 127), un toast « Authentification annulée » s'affiche.

## Paquet

- `sesame_<version>_all.deb`, construit avec debhelper (`3.0 (native)`), comme Gagarine.
- Dépendances : `python3 (>= 3.10)`, `pkexec`, `policykit-1 | polkitd`, `realmd`, `snapd`,
  `software-properties-common` (`add-apt-repository`), `passwd`, `cron | cron-daemon`.
- Recommandés : `python3-gi`, `gir1.2-gtk-4.0`, `gir1.2-adw-1 (>= 1.5)`.
- authd n'est **pas** une dépendance : en 24.04, il vient d'un PPA et il est installé par l'étape `installer`.
- Le paquet installe sa source APT (deb822 `sesame.sources`, `Signed-By: /usr/share/keyrings/sesame.gpg`) et sa clé.
- Le dépôt APT signé est sur GitHub Pages (`https://mawena.github.io/sesame/apt`, branche `gh-pages`), avec une clé dédiée
  « Sésame APT (mawena) » (ed25519, sans phrase de passe), sur le modèle de Gagarine (`scripts/publier-apt.sh`, `site/`,
  `make apt`).
- Lintian ne doit signaler ni erreur ni avertissement. Les fichiers de bureau et la metainfo doivent être valides.

## Tests

- `make test` lance `python3 -m unittest discover -s tests -t . -v`, avec la bibliothèque standard seulement.
- Le cœur est testé sur une racine temporaire, avec des commandes simulées : détection de chaque statut, écriture de
  `broker.conf`, de `sesame.conf` et de `nsswitch.conf`, ordre exact des commandes de la reprise, annulation après une
  panne simulée à chaque étape (le contenu de `H` n'est jamais déplacé ailleurs que vers `H.sesame-reprise` et
  retour), au démarrage (le fichier programmé est supprimé avant tout).
- L'assistant graphique : test d'import et de construction de la fenêtre si un affichage est disponible, sinon le test
  est ignoré (`skipTest`).
- Les suites de tests et la construction du paquet passent par la file Gagarine (`gagarine file …`).
