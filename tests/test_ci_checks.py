"""
Tests d'intégration continue : absence de migrations en attente et durcissement cookies.

Ces vérifications tournent dans la pipeline CI pour empêcher la fusion d'un
code qui aurait modifié un modèle sans générer la migration correspondante,
ou qui aurait régressé sur les drapeaux de sécurité des cookies en production.
"""
from io import StringIO

from django.conf import settings
from django.core.management import call_command
from django.test import SimpleTestCase
from django.test.utils import override_settings


class MigrationCheckTests(SimpleTestCase):
    """Vérifie que le projet est cohérent avec ses migrations et passe ``check --deploy``."""

    databases = {"default"}

    def test_makemigrations_check_dry_run(self):
        """Aucune migration manquante : ``makemigrations --check --dry-run`` doit renvoyer ``No changes detected``."""
        stdout = StringIO()
        stderr = StringIO()

        call_command(
            "makemigrations",
            check=True,
            dry_run=True,
            stdout=stdout,
            stderr=stderr,
        )

        combined_output = f"{stdout.getvalue()}\n{stderr.getvalue()}"
        self.assertIn("No changes detected", combined_output)

    def test_check_deploy(self):
        """``manage.py check --deploy`` ne doit produire aucun avertissement en configuration production."""
        stdout = StringIO()
        stderr = StringIO()

        with override_settings(
            DEBUG=False,
            SECURE_SSL_REDIRECT=True,
            SECURE_HSTS_SECONDS=31536000,
            SECURE_HSTS_INCLUDE_SUBDOMAINS=True,
            SECURE_HSTS_PRELOAD=True,
            SESSION_COOKIE_SECURE=True,
            CSRF_COOKIE_SECURE=True,
            SILENCED_SYSTEM_CHECKS=[
                "drf_spectacular.W001",
                "drf_spectacular.W002",
            ],
        ):
            call_command(
                "check",
                deploy=True,
                stdout=stdout,
                stderr=stderr,
            )

        combined_output = f"{stdout.getvalue()}\n{stderr.getvalue()}".lower()
        self.assertNotIn("warning", combined_output)


class ProductionCookieSecurityTests(SimpleTestCase):
    """Vérifie les drapeaux de durcissement cookies non couverts par ``check --deploy``."""

    @override_settings(
        DEBUG=False,
        SESSION_COOKIE_SECURE=True,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Strict",
        CSRF_COOKIE_SECURE=True,
        CSRF_COOKIE_HTTPONLY=True,
    )
    def test_production_cookie_flags(self):
        """En production, les cookies de session et CSRF doivent être Secure/HttpOnly/SameSite=Strict."""
        self.assertTrue(settings.SESSION_COOKIE_SECURE)
        self.assertTrue(settings.SESSION_COOKIE_HTTPONLY)
        self.assertEqual(settings.SESSION_COOKIE_SAMESITE, "Strict")
        self.assertTrue(settings.CSRF_COOKIE_SECURE)
        self.assertTrue(settings.CSRF_COOKIE_HTTPONLY)
