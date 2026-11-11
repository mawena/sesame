# Sésame

**Site : [mawena.github.io/sesame](https://mawena.github.io/sesame/)** — dépôt APT signé, mises à jour par
`sudo apt upgrade`.

Sésame connecte un poste **Ubuntu Desktop 24.04 ou plus récent** à **Microsoft Entra ID** avec
[authd](https://ubuntu.com/identity/authd) (Canonical) et son module `authd-msentraid` (snap), puis fait **reprendre au
compte Entra le compte local existant** : même UID, même dossier personnel, mêmes groupes, même crontab. On retrouve son
bureau, mais on s'y connecte avec son compte de l'entreprise.

![Aperçu de l'assistant Sésame](docs/captures/apercu.png)

## Installation

Sésame s'installe depuis son **dépôt APT signé**, publié sur [mawena.github.io/sesame](https://mawena.github.io/sesame/) ;
ensuite, `sudo apt upgrade` apporte les nouvelles versions.

### En une ligne

```bash
curl -fsSL https://mawena.github.io/sesame/installer.sh | sudo sh
```

Le script ([à lire sur le site](https://mawena.github.io/sesame/installer.sh)) ajoute la clé et le dépôt, puis installe
Sésame : exactement les trois étapes ci-dessous.

### Pas à pas

```bash
# 1. La clé qui signe le dépôt
sudo curl -fsSLo /usr/share/keyrings/sesame.gpg https://mawena.github.io/sesame/apt/sesame.gpg
# 2. Le dépôt
sudo curl -fsSLo /etc/apt/sources.list.d/sesame.sources https://mawena.github.io/sesame/apt/sesame.sources
# 3. L'installation
sudo apt update && sudo apt install sesame
```

Clé de signature : « Sésame APT (mawena) », empreinte `EC3E F563 FE1B 133E 5575 3127 1089 B937 B4BD A7F1`.
Le paquet installe lui-même la source (`/etc/apt/sources.list.d/sesame.sources`) et la clé
(`/usr/share/keyrings/sesame.gpg`).

### Mise à jour

```bash
sudo apt update && sudo apt upgrade
```

### Sans le dépôt

En dernier recours, téléchargez `sesame_<version>_all.deb` et `SHA256SUMS` sur la page des
[releases](https://github.com/mawena/sesame/releases/latest), vérifiez la somme (`sha256sum -c SHA256SUMS`), puis :

```bash
sudo apt install ./sesame_<version>_all.deb
```

## À quoi ça sert

Avec authd, on ouvre une session Ubuntu avec son compte Microsoft Entra. Mais ce compte arrive avec un autre
identifiant, un autre dossier personnel et aucun groupe : le poste de tous les jours disparaît. Sésame remplace une suite
de scripts manuels : il installe et configure authd, puis le compte Entra prend la place du compte local.

- **idempotent** : chaque étape détecte si elle est déjà faite, et on peut la relancer sans risque ;
- **jamais destructeur sans retour** : une sauvegarde est faite avant chaque étape qui modifie quelque chose, la
  reprise s'annule automatiquement si elle échoue, et à la main ;
- **générique** : rien n'est propre à une entreprise ; domaine AD, compte local, groupes et UPN suggéré sont détectés
  sur le poste et modifiables ;
- **sans secret stocké** : l'ID du locataire et l'ID client ne sont pas des secrets ; le mot de passe du compte de
  secours passe par l'entrée standard de l'assistant root et n'est jamais écrit.

Sésame ne fait pas : la création de l'application dans le portail Entra (il l'explique pas à pas), l'inscription de
l'appareil dans Entra (`register_device = false`), ni plusieurs comptes Entra (seul le propriétaire, `allowed_users =
OWNER`).

## Prérequis

- Ubuntu Desktop 24.04 ou plus récent, avec GNOME et GDM ;
- un compte local avec les droits d'administration sur le poste ;
- les droits d'administration sur le locataire Microsoft Entra pour créer l'application et donner le consentement (ou
  quelqu'un qui peut le faire pour vous) ;
- un accès à Internet (PPA d'authd, snap `authd-msentraid`, connexion Microsoft).

## Créer l'application dans le portail Entra

À faire une seule fois par locataire, dans le [portail Entra](https://entra.microsoft.com). L'assistant et
`sesame portail` affichent les mêmes étapes.

1. **Inscriptions d'applications** (Identité, Applications) puis **Nouvelle inscription**.
2. Nom : « Ubuntu authd ». Types de comptes pris en charge : **Comptes dans cet annuaire d'organisation uniquement**
   (locataire unique). Laissez l'URI de redirection vide, puis **Inscrire**.
3. Notez, sur la page de vue d'ensemble, l'**ID d'application (client)** et l'**ID de l'annuaire (locataire)**.
4. **Autorisations de l'API** puis **Ajouter une autorisation**, **Microsoft Graph**, **Autorisations déléguées** :
   `openid`, `profile`, `offline_access`, `User.Read` et `GroupMember.Read.All`.
5. **Accorder le consentement administrateur** pour le locataire (bouton sur la même page).
6. **Authentification**, section Paramètres avancés : **Autoriser les flux de clients publics** sur **Oui**, puis
   **Enregistrer**.
7. Si une stratégie d'**accès conditionnel** bloque le flux par code d'appareil ou les clients publics pour cette
   application, ajoutez une exception : la connexion en dépend.

## Utilisation

Lancez **Sésame** depuis les applications, ou `sesame-assistant`. L'assistant montre chaque étape avec son état et propose
la suivante ; la commande `sesame` donne la même chose dans un terminal (`sesame` seul affiche l'état et l'étape
suivante). Les actions qui touchent au système demandent votre mot de passe dans la fenêtre d'authentification d'Ubuntu
(pkexec).

| Étape | Commande | Ce qu'elle fait |
|---|---|---|
| Sauvegarder | `sesame sauvegarde` | copie `/etc/passwd`, `shadow`, `group`, `nsswitch.conf`, `pam.d`, `sssd`, `gdm3`, etc. et la crontab du compte local |
| Compte de secours | `sesame secours` | crée un compte administrateur local de dépannage (mot de passe demandé deux fois) |
| Quitter l'AD | `sesame quitter-ad` | quitte le domaine Active Directory et retire sssd de la configuration (sans objet sans domaine) |
| Installer | `sesame installer` | ajoute le PPA d'authd, installe `authd` et le snap `authd-msentraid` |
| Configurer | `sesame configurer` | écrit `/etc/sesame/sesame.conf` et la configuration du module Entra à partir du locataire, du client et du compte Entra |
| Première connexion | | à l'écran d'accueil : « Non listé ? », votre UPN, « Microsoft Entra ID », code à saisir sur le téléphone, choix du mot de passe local |
| Reprise | `sesame reprise --au-demarrage` | le compte Entra reprend le compte local (voir ci-dessous) |
| Vérifier | `sesame verifier` | contrôles sans root : compte, dossier, groupes, crontab, services, compte de secours |

## Ce que fait la reprise, et comment l'annuler

La reprise se fait de préférence **au prochain démarrage** : un service systemd (`sesame-reprise.service`) tourne avant
l'écran de connexion et avant toute session, donc aucun programme ne tourne sous l'un des deux comptes. Le service est
activé par `sesame reprise --au-demarrage`, supprime d'abord le fichier de programmation (jamais de boucle), lance la
reprise, l'annule si elle échoue, puis se désactive.

La reprise :

1. fait une sauvegarde `avant-reprise` et garde la crontab du compte local ;
2. supprime le compte local (`userdel` sans `-r`) ;
3. donne au compte Entra l'UID et le GID du compte local (`authctl user set-uid`, `authctl group set-gid`) ;
4. lui donne le dossier personnel de l'ancien compte, sans jamais laisser authctl déplacer son contenu ;
5. met à jour ce qui citait l'ancien compte : `subuid`, `subgid`, unités systemd (`User=`, `Group=`), VMware, connexion
   automatique de GDM ; réinstalle la crontab pour le compte Entra et copie la photo et les réglages d'AccountsService.

**Annuler** : `sesame annuler-reprise` (ou le menu de l'assistant) remet le dossier, l'UID, le GID, les fichiers de
`/etc` et la crontab d'avant, depuis la sauvegarde. Pour seulement retirer une reprise programmée :
`sesame reprise --annuler-programmation`. Pour couper la connexion Entra sans rien désinstaller : `sesame desactiver`
(`sesame configurer` la rétablit).

## Configuration

`/etc/sesame/sesame.conf` (INI, écrit par l'étape « configurer ») :

```ini
[entra]
locataire = 00000000-0000-0000-0000-000000000000   ; ID de l'annuaire
client = 00000000-0000-0000-0000-000000000000      ; ID d'application
compte = prenom.nom@entreprise.com                 ; UPN, en minuscules

[local]
compte = charles-gamligo        ; compte local que le compte Entra reprendra
uid = 1000
gid = 1000
dossier = /home/charles-gamligo
secours = secours               ; compte local administrateur de dépannage

[groupes]
supplementaires = sudo,lpadmin,adm,docker   ; groupes redonnés au compte Entra
```

Fichiers de `/var/lib/sesame` :

| Fichier | Rôle |
|---|---|
| `etat.json` | ce que Sésame a fait et quand (lisible sans root, sans secret) |
| `sauvegardes/AAAAMMJJ-HHMMSS[-motif]/` | sauvegardes (dossier 0700) ; conservées à la purge du paquet |
| `reprise-programmee` | présent : reprise au prochain démarrage |
| `reprise-etat.json` | état d'une reprise en cours, pour l'annuler |
| `derniere-reprise.json` | résultat de la dernière reprise |

## Dépannage

- **Garder un accès** : ne fermez pas l'étape « compte de secours » ; si la session graphique ne s'ouvre plus, passez en
  console avec `Ctrl+Alt+F3` et connectez-vous avec le compte de secours.
- **Journaux** : `sudo journalctl -u authd -u snap.authd-msentraid.authd-msentraid.service -u sesame-reprise`.
- **Résultat de la reprise** : `cat /var/lib/sesame/derniere-reprise.json`.
- **Couper la connexion Entra** : `sesame desactiver`.
- **Revenir en arrière** : `sesame annuler-reprise`, ou restaurez les fichiers de la sauvegarde la plus récente de
  `/var/lib/sesame/sauvegardes` avec le compte de secours.

## Structure du dépôt

```
bin/                  sesame (ligne de commande), sesame-assistant (assistant graphique)
libexec/sesame-racine assistant root lancé par pkexec
sesame/               cœur Python : config, étapes, vérification, guide, racine, cli
sesame/interface/     assistant graphique GTK 4 + libadwaita
data/                 polkit, systemd, bureau, metainfo, icônes, source et clé APT
debian/               paquet Debian
man/                  sesame(8), sesame-assistant(1)
scripts/              build-deb.sh, publier-apt.sh, capture-interface.py
site/                 page d'accueil (GitHub Pages) et installer.sh
tests/                tests unitaires
docs/                 conception, captures
```

## Développement

```bash
make test    # tests unitaires (bibliothèque standard seulement)
make deb     # construit dist/sesame_<version>_all.deb, SHA256SUMS, lintian
make apt     # publie dist/*.deb dans le dépôt APT signé (branche gh-pages) et met le site à jour
```

Sur un poste partagé avec Gagarine, les travaux lourds passent par sa file :
`gagarine file "sesame-tests" 2 2 -- make test`. Le cœur est testé sur une racine temporaire, avec des commandes
simulées ; rien ne touche au poste. Conception : [`docs/conception-1.0.0.md`](docs/conception-1.0.0.md).

## Licence

[MIT](LICENSE) — © 2026 mawena.
