"""Guide du portail Entra."""
import unittest

from sesame import guide


class TestGuide(unittest.TestCase):
    def test_contenu(self):
        self.assertEqual(guide.URL_PORTAIL, "https://entra.microsoft.com")
        tout = " ".join(t + " " + d for t, d in guide.PORTAIL)
        for mot in ("openid", "profile", "offline_access", "User.Read", "GroupMember.Read.All", "consentement",
                    "flux de clients publics", "accès conditionnel", "Ubuntu authd", "locataire unique"):
            self.assertIn(mot.lower(), tout.lower(), mot)

    def test_forme(self):
        for titre, detail in guide.PORTAIL:
            self.assertTrue(titre and detail)
        self.assertGreaterEqual(len(guide.PORTAIL), 5)
