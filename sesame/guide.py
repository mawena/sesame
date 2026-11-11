"""Guide de la création de l'application dans le portail Microsoft Entra."""

URL_PORTAIL = "https://entra.microsoft.com"
URI_REDIRECTION = "https://login.microsoftonline.com/common/oauth2/nativeclient"

PORTAIL = [
    ("Inscrire l'application",
     "Entra ID › Inscriptions d'applications › Nouvelle inscription. Nom : « Ubuntu authd ». Type de comptes : "
     "« Comptes dans cet annuaire d'organisation uniquement » (locataire unique). URI de redirection : plateforme "
     f"« Client public/natif (mobile et bureau) », adresse {URI_REDIRECTION}. Cliquez sur Inscrire."),
    ("Noter les deux identifiants",
     "Sur la page « Vue d'ensemble » de l'application, copiez l'ID d'application (client) et l'ID de l'annuaire "
     "(locataire). Ce ne sont pas des secrets : Sésame vous les demande."),
    ("Ajouter les autorisations",
     "Autorisations des API › Ajouter une autorisation › Microsoft Graph › Autorisations déléguées : openid, "
     "profile, offline_access, User.Read et GroupMember.Read.All."),
    ("Accorder le consentement administrateur",
     "Cliquez sur « Accorder un consentement d'administrateur » pour le locataire. Il est obligatoire pour "
     "GroupMember.Read.All."),
    ("Autoriser les flux de clients publics",
     "Authentification › Paramètres avancés › « Autoriser les flux de clients publics » : Oui, puis Enregistrer. "
     "C'est nécessaire à la connexion par code sur le téléphone, proposée en secours."),
    ("Autoriser l'inscription des appareils",
     "Entra ID › Appareils › Paramètres de l'appareil : « Les utilisateurs peuvent inscrire leurs appareils auprès "
     "de Microsoft Entra ID » doit être sur Tous (le réglage par défaut) ou vous inclure. Comme un PC Windows, "
     "le poste sera inscrit dans Entra à la première connexion et apparaîtra dans Entra › Appareils."),
    ("Vérifier votre compte",
     "La connexion par mot de passe demande une méthode de double authentification enregistrée (Microsoft "
     "Authenticator, par exemple : https://mysignins.microsoft.com/security-info) et un domaine qui n'est pas "
     "fédéré par AD FS (Entra ID › Noms de domaine personnalisés, colonne « Fédéré »). Sinon, choisissez la "
     "connexion « Code sur le téléphone » dans Sésame."),
    ("Vérifier l'accès conditionnel",
     "Si une stratégie d'accès conditionnel exige un appareil conforme (Intune) ou bloque le « flux de code "
     "d'appareil » (device code flow), elle peut bloquer la connexion : excluez votre compte de cette stratégie."),
]


def texte_portail():
    """Le guide en texte lisible, pour la ligne de commande."""
    lignes = [f"Créer l'application dans le portail Entra : {URL_PORTAIL}", ""]
    for i, (titre, detail) in enumerate(PORTAIL, 1):
        lignes += [f"{i}. {titre}", f"   {detail}", ""]
    return "\n".join(lignes).rstrip() + "\n"
