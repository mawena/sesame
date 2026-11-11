# Sésame 1.2.0 — rejoindre Entra comme un PC Windows

Suite de [conception-1.1.0.md](conception-1.1.0.md). Demande : « quand je lance Sésame, qu'il me demande juste l'email,
le mot de passe et le nom de la machine ».

## Ce que voit l'utilisateur

1. `sesame-assistant` s'ouvre sur la page **« Rejoindre Microsoft Entra ID »** : deux champs, **Adresse pro** et **Nom
   de la machine** (prérempli avec le nom actuel, sans domaine), et un bouton **Rejoindre**. L'ancien écran à 8 étapes
   devient **« Mode avancé »** (menu), inchangé.
2. **Rejoindre** vérifie d'abord le réseau : si authd n'est pas installé et que Launchpad ou le Snap Store ne répondent
   pas, Sésame le dit tout de suite (« branchez-vous sur un autre réseau, par exemple le partage de connexion du
   téléphone ») et ne fait rien.
3. Une fenêtre de **connexion Microsoft** s'ouvre dans Sésame (WebKitGTK), l'adresse déjà remplie : mot de passe, puis
   validation sur le téléphone, comme sur Windows. Sésame ne voit jamais le mot de passe. La première fois, Microsoft
   demande à l'administrateur d'accepter les autorisations de « Microsoft Graph Command Line Tools ».
4. Sésame crée (ou reprend) l'application **« Ubuntu authd »** dans Entra et en lit l'ID client ; l'ID du locataire
   vient du jeton.
5. **Une** fenêtre polkit (mot de passe Ubuntu), puis tout s'enchaîne, avec la progression affichée : sauvegarde, compte
   de secours, nom de la machine, sortie du domaine AD, installation d'authd, configuration (mode mot de passe), reprise
   du compte **en attente de la première connexion**.
6. Page finale : « Déconnectez-vous ; à l'écran d'accueil, « Non listé ? », votre adresse pro, votre mot de passe Entra
   et la validation sur le téléphone. Redémarrez ensuite une fois : votre compte Entra reprend vos fichiers. » Bouton
   **Se déconnecter**.
7. Dans la première session Entra (dossier encore vide), une petite fenêtre lancée au démarrage de session
   (`sesame-assistant --suite`) dit « Redémarrez pour retrouver vos fichiers » avec un bouton **Redémarrer**.

En ligne de commande : `sesame rejoindre [--compte ADRESSE] [--nom-machine NOM]` fait la même chose ; la connexion
Microsoft passe par un code à usage unique (flux « device code »).

## Décisions

- **Client Microsoft pour créer l'application** : « Microsoft Graph Command Line Tools »
  (`14d82eec-204b-4c2f-b7e8-296a70dab67e`, client public de Microsoft, celui de PowerShell), point de terminaison
  `organizations`. Portées : `https://graph.microsoft.com/Application.ReadWrite.All`,
  `https://graph.microsoft.com/DelegatedPermissionGrant.ReadWrite.All`, `openid`, `profile`. Le flux « device code »
  avec ce client a été vérifié depuis le poste (11/11/2026).
- **Connexion dans l'assistant** : code d'autorisation + PKCE (S256), `redirect_uri=http://localhost`, interceptée par
  la WebView (`decide-policy`) sans serveur local ; session WebKit éphémère. Si la WebView est absente ou si Microsoft
  refuse la redirection (AADSTS50011), repli sur le code à usage unique dans la même fenêtre.
- **Application « Ubuntu authd »** : recherchée par étiquette `sesame`, sinon par nom ; sinon créée :
  `signInAudience=AzureADMyOrg`, `isFallbackPublicClient=true` (flux de clients publics, pour le code en secours),
  `publicClient.redirectUris=[https://login.microsoftonline.com/common/oauth2/nativeclient]`, autorisations Microsoft
  Graph déléguées `openid profile offline_access User.Read GroupMember.Read.All` (identifiants lus dans
  `oauth2PermissionScopes` du principal de service Microsoft Graph, pas codés en dur), principal de service, puis
  consentement administrateur (`oauth2PermissionGrants`, `consentType=AllPrincipals`). Une application existante est
  complétée (redirection, client public, autorisations, consentement) sans rien retirer. Délais de réplication :
  nouvelles tentatives (404/400) avec attente croissante, 6 essais.
- **Contrôle du locataire** : le locataire du domaine de l'adresse pro (`/.well-known/openid-configuration`) doit être
  celui du jeton ; sinon erreur claire (« connectez-vous avec un compte administrateur de <domaine> »).
- **Compte de secours** : créé s'il manque, avec **le mot de passe Ubuntu actuel** du compte local (empreinte de
  `/etc/shadow` copiée par `chpasswd -e`). Empreinte inutilisable (`!`, `*`, vide) → erreur qui renvoie au mode avancé.
- **Nom de la machine** : 1 à 15 caractères, lettres, chiffres et tirets, ni tiret au début ou à la fin, pas
  uniquement des chiffres (règle Windows). `hostnamectl hostname NOM`, ligne `127.0.1.1` de `/etc/hosts` remplacée (ou
  ajoutée). La casse est gardée. authd inscrit l'appareil sous `os.Hostname()`.
- **Reprise en attente** : `reprise.programmer(..., attendre=True)` accepte un compte Entra encore inconnu ; le fichier
  `reprise-programmee` porte `"attendre": true`. Au démarrage, tant que le compte Entra est inconnu, le service garde le
  fichier et reste activé (fin « en attente », jamais d'échec) ; dès qu'il existe, la reprise habituelle a lieu.
- **Version** : 1.2.0 (nouvelle fonction compatible ; tout le reste de la 1.1.0 est gardé dans le mode avancé).

## Contrats entre modules

### `sesame/entra.py` (côté utilisateur, sans root, bibliothèque standard seulement)

```python
CLIENT_OUTILS_GRAPH = "14d82eec-204b-4c2f-b7e8-296a70dab67e"
ID_GRAPH = "00000003-0000-0000-c000-000000000000"
AUTORITE = "https://login.microsoftonline.com/organizations"
REDIRECTION = "http://localhost"
PORTEES = ("https://graph.microsoft.com/Application.ReadWrite.All",
           "https://graph.microsoft.com/DelegatedPermissionGrant.ReadWrite.All", "openid", "profile")
PORTEES_AUTHD = ("openid", "profile", "offline_access", "User.Read", "GroupMember.Read.All")
NOM_APPLICATION = "Ubuntu authd"
ETIQUETTE = "sesame"
HOTES_AUTHD = ("ppa.launchpadcontent.net", "api.snapcraft.io")

class ErreurEntra(ErreurSesame): ...           # message en français, lisible tel quel

def http_urllib(methode, url, corps=None, entetes=None, delai=30) -> tuple[int, dict | None]
    # corps dict -> JSON ; corps str -> application/x-www-form-urlencoded ; réponse JSON décodée (None sinon) ;
    # erreurs réseau -> ErreurEntra("Microsoft ne répond pas : …")

@dataclass
class Demande: url: str; verificateur: str; etat: str; redirection: str = REDIRECTION
def nouvelle_demande(email) -> Demande          # login_hint=email, prompt=select_account
def est_redirection(url, demande) -> bool
def code_depuis_redirection(url, demande) -> str   # vérifie state ; error= -> ErreurEntra (AADSTS65001 : consentement
                                                   # refusé ; AADSTS50011 : redirection refusée -> repli code)
@dataclass
class Jeton: acces: str; locataire: str; compte: str   # tid et preferred_username lus dans le jeton d'accès/ID
def echanger_code(code, demande, http=http_urllib) -> Jeton
def demarrer_code_appareil(http=http_urllib) -> dict  # clés : code_utilisateur, adresse, message, code_appareil,
                                                      # intervalle, expire
def attendre_code_appareil(appareil, http=http_urllib, dormir=time.sleep, horloge=time.monotonic,
                           annule=lambda: False) -> Jeton
def locataire_du_domaine(email, http=http_urllib) -> str | None
def verifier_locataire(email, jeton, http=http_urllib) -> None     # ErreurEntra si différent ; rien si inconnu
def hotes_injoignables(delai=8, ouvrir=None) -> list[str]          # parmi HOTES_AUTHD (toute réponse HTTP = joignable)
def preparer_application(jeton, http=http_urllib, rappel=lambda texte: None, dormir=time.sleep) -> str  # ID client
```

### `sesame-racine rejoindre` (root, par pkexec)

```
sesame-racine [--json] rejoindre --compte ADRESSE --nom-machine NOM --locataire GUID --client GUID [--compte-local NOM]
```

`actions.rejoindre(systeme, compte, nom_machine, locataire, client, compte_local=None) -> str`. Valide tout avant de
modifier quoi que ce soit (`construire_config` + `valider_nom_machine`), puis, chaque étape annoncée par
`systeme.etape(...)` et sautée si déjà faite : sauvegarde (`rejoindre`), compte de secours (copie de l'empreinte),
nom de la machine, sortie du domaine AD, installation (si authd ou le module manquent ou sont trop anciens),
configuration (`connexion = mot-de-passe`), reprise en attente (sauf si elle est déjà faite ou programmée). Compte
local par défaut : celui de `uid_appelant()` s'il est local, sinon `cfg.defauts`. Message de fin : « Le poste NOM est
prêt à rejoindre Entra : déconnectez-vous, puis connectez-vous avec ADRESSE et votre mot de passe Entra. ». Échec
réseau à l'installation → message qui nomme le réseau (Launchpad, Snap Store) et propose un autre réseau ; relancer
`rejoindre` reprend où il s'était arrêté.

Nouvelles fonctions : `cfg.valider_nom_machine(nom)`, `actions.changer_nom_machine(systeme, nom)`,
`actions.creer_secours(systeme, nom, mot_de_passe=None, copier_de=None)`, `reprise.programmer(systeme, p,
attendre=False)`. `etapes` : l'étape « reprise » programmée en attente reste `programmee`, détail « au premier démarrage
après la première connexion Entra ».

### Assistant graphique

- `sesame/interface/microsoft.py` : `ConnexionMicrosoft(parent, email, sur_fin)` (fenêtre modale ; `sur_fin(jeton,
  erreur)`), WebView WebKit 6.0 éphémère ; repli code à usage unique (code en grand, copiable, bouton « Ouvrir la
  page »).
- `fenetre.py` : `Adw.ViewStack` (ou `Adw.NavigationView`) : page « Rejoindre » par défaut, « Mode avancé » = l'écran
  actuel. Le travail réseau tourne dans un fil, résultats rendus par `GLib.idle_add`. La page « Rejoindre » montre la
  progression (événements de `sesame-racine --json`), puis la page finale. Si Sésame est déjà configuré et la reprise
  programmée ou faite, la page « Rejoindre » montre l'état et la marche à suivre.
- `sesame-assistant --suite` + `/etc/xdg/autostart/sesame-suite.desktop` : ne s'affiche que si l'utilisateur de la
  session n'est pas dans `/etc/passwd` et que `/var/lib/sesame/reprise-programmee` existe.
- `debian/control` : `Depends: gir1.2-webkit-6.0`.

## Tests

Tout réseau simulé (`http` injecté), aucune requête réelle. Racine : machine simulée de `tests/commun.py`
(`hostnamectl`, `/etc/shadow`, `chpasswd -e`). Interface : fonctions d'`entra` et fenêtre Microsoft remplacées par des
doublures. Tous les tests passent par la file Gagarine.
