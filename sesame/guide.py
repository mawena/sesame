"""Guide de la création de l'application dans le portail Microsoft Entra."""

URL_PORTAIL = "https://entra.microsoft.com"

PORTAIL = [
    ("Inscrire l'application",
     "Entra ID › Inscriptions d'applications › Nouvelle inscription. Nom : « Ubuntu authd ». Type de comptes : "
     "« Comptes dans cet annuaire d'organisation uniquement » (locataire unique). Pas d'URI de redirection. "
     "Cliquez sur Inscrire."),
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
     "C'est nécessaire à la connexion par code d'appareil."),
    ("Vérifier l'accès conditionnel",
     "Si une stratégie d'accès conditionnel bloque le « flux de code d'appareil » (device code flow), excluez "
     "l'application « Ubuntu authd » ou votre compte de cette stratégie."),
]


def texte_portail():
    """Le guide en texte lisible, pour la ligne de commande."""
    lignes = [f"Créer l'application dans le portail Entra : {URL_PORTAIL}", ""]
    for i, (titre, detail) in enumerate(PORTAIL, 1):
        lignes += [f"{i}. {titre}", f"   {detail}", ""]
    return "\n".join(lignes).rstrip() + "\n"
