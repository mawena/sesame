# Sésame 1.1.0 — conception

Suite de [Sésame 1.0.0](conception-1.0.0.md). Tout ce que dit la conception 1.0.0 reste vrai, sauf ce qui est précisé
ici.

## But

Connecter « comme sur Windows » : **adresse pro + mot de passe Entra + double authentification** (validation dans
Microsoft Authenticator, code à usage unique, ou méthode sans mot de passe : clé FIDO2, Authenticator sans mot de passe,
Temporary Access Pass). Avant, il fallait le code d'appareil (QR code ou code à saisir sur le téléphone), puis choisir un
mot de passe local.

Cela repose sur authd 0.7.0 et le module `authd-msentraid` 0.5.0 (annonce de Canonical, septembre 2026). Sésame 1.1.0
active ce mode par défaut ; l'ancien reste disponible.

## Réglage `connexion`

Clé `connexion` de la section `[entra]` de `/etc/sesame/sesame.conf` :

- `mot-de-passe` (défaut) : comme sur Windows ;
- `code` : le code d'appareil sur le téléphone, comportement de la 1.0.0.

Sans la clé (fichier écrit par la 1.0.0), ou avec une valeur inconnue, la valeur lue est `mot-de-passe`. Dans
`etat.json`, une étape « configurer » notée sans `connexion` (faite par la 1.0.0) compte comme `code` : c'est ce qui
fait repasser l'étape à faire après la mise à jour (voir plus bas).

- `sesame configurer --connexion mot-de-passe|code` ; sans l'option : la valeur déjà enregistrée, sinon
  `mot-de-passe` ; en interactif, la question est posée. `sesame-racine configurer --connexion mot-de-passe|code` aussi.
- Assistant graphique : dans le groupe « Compte Microsoft Entra », une ligne de choix « Connexion » : « Adresse et mot de
  passe (comme sur Windows) » ou « Code sur le téléphone ».

## `broker.conf` par mode

| Réglage | `mot-de-passe` | `code` |
|---|---|---|
| `[msentraid] register_device` | `true` | `false` |
| `[flows] device_code` | `true` | `true` |
| `[flows] entra_auth` | `true` | `false` |

Le reste du fichier (`[oidc]`, `[users]`) ne change pas. En mode `mot-de-passe`, le PC est **inscrit dans Entra** à la
première connexion : il apparaît dans Entra › Appareils, comme un PC Windows. C'est ce qui permet à authd de lire les
groupes du compte sans secret client. Le code d'appareil reste proposé en secours à l'écran de connexion. Le mode `code`
ne change rien par rapport à la 1.0.0.

Hors connexion, authd garde une empreinte salée du mot de passe pour laisser entrer. Si la connexion s'est faite sans mot
de passe (clé FIDO2, Authenticator), authd demande de choisir un mot de passe local à la première connexion.

## Versions minimales

Le mode `mot-de-passe` demande **authd ≥ 0.7.0** et **`authd-msentraid` ≥ 0.5.0**. Trois endroits s'en occupent :

- **détection de l'étape « Installer »** : si une des deux versions est plus ancienne, l'étape le signale (version
  trouvée, version requise) ;
- **action « Installer »** : `apt-get install` (qui met aussi à jour authd s'il est déjà installé), puis
  `snap refresh authd-msentraid` si le snap est déjà installé (sinon `snap install`) ;
- **action « Configurer »** : refuse le mode `mot-de-passe` si les versions sont trop anciennes, dit pourquoi et propose
  le mode `code`.

Autres conditions, que Sésame n'est pas en mesure de vérifier lui-même et que le guide du portail décrit : une méthode de
double authentification enregistrée sur le compte, et un compte qui n'est pas fédéré par AD FS. Les comptes sans double
authentification, ou fédérés par AD FS, retombent sur le code d'appareil (ou utilisent le mode `code`).

## Détection du changement de mode

L'étape `configurer` note la valeur de `connexion` dans `etat.json`. Si la valeur voulue (`sesame.conf`) diffère de celle
notée, ou si elle est absente de `etat.json` (installation faite par la 1.0.0, donc en `code`), l'étape repasse à
`a_faire` avec le détail « le mode de connexion a changé ». La relancer suffit : changer `register_device` force une
nouvelle authentification, et authd demandera de se reconnecter par Entra. Changer de mode plus tard : changer le choix
« Connexion » et relancer « Configurer ».

## Guide du portail

`sesame portail` et le menu « Guide du portail Entra » décrivent les réglages, dans cet ordre :

1. à l'inscription de l'application « Ubuntu authd », plateforme « Client public/natif (mobile et bureau) » avec l'URI
   de redirection `https://login.microsoftonline.com/common/oauth2/nativeclient` ;
2. autorisations déléguées Microsoft Graph inchangées (`openid`, `profile`, `offline_access`, `User.Read`,
   `GroupMember.Read.All`) et consentement administrateur ;
3. « Autoriser les flux de clients publics » : toujours utile, pour la connexion de secours par code ;
4. Entra ID › Appareils › Paramètres de l'appareil : « Les utilisateurs peuvent inscrire leurs appareils auprès de
   Microsoft Entra ID » sur Tous (valeur par défaut) ou sur un groupe qui inclut le compte ;
5. vérifier le compte : méthode de double authentification enregistrée
   (<https://mysignins.microsoft.com/security-info>), domaine non fédéré (Entra ID › Noms de domaine personnalisés,
   colonne « Fédéré ») ;
6. accès conditionnel : une stratégie qui exige un appareil conforme (Intune), ou qui bloque le flux de code d'appareil,
   peut bloquer la connexion ; exclure le compte de la stratégie.

## Textes de première connexion

À l'écran de GDM, en mode `mot-de-passe` : « Non listé ? », l'adresse pro (par exemple `prenom.nom@entreprise.com`),
« Microsoft Entra ID », le mot de passe Entra, la double authentification (Authenticator, code), et c'est tout. En mode
`code` : QR code ou code à saisir sur le téléphone, puis choix d'un mot de passe local. L'assistant, `sesame portail`,
la page de manuel et le site disent la même chose.

## Compatibilité avec la 1.0.0

- une installation 1.0.0 continue de fonctionner telle quelle (mode `code`) tant que « Configurer » n'est pas relancé ;
- la mise à jour fait repasser « Configurer » à faire ; la relancer applique le mode choisi (`mot-de-passe` par défaut)
  et demande à authd une nouvelle authentification ;
- `sesame.conf` de la 1.0.0 reste lisible : la clé `connexion` est facultative.

## Ce qui ne change pas

Les étapes et leur ordre, la sauvegarde, le compte de secours, la sortie de
l'AD, la reprise du compte local (au démarrage, annulation automatique en cas d'échec, `annuler-reprise`), `desactiver`,
la vérification, l'assistant root unique lancé par pkexec, l'absence de secret stocké, `allowed_users = OWNER`, le dépôt
APT et le paquet.
