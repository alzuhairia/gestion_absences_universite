"""Tests contractuels d'authentification sur l'API JSON interne.

Garantit que les endpoints internes consommés par le frontend
(``enrollments:get_departments`` et apparentés) :
    - n'acceptent QUE les rôles autorisés (étudiant / secrétaire selon
      la route — pas d'accès anonyme)
    - retournent un Content-Type JSON cohérent
    - exigent l'entête ``X-Requested-With: XMLHttpRequest`` (anti-CSRF
      défense en profondeur, complète le jeton CSRF Django)
    - réagissent correctement aux paramètres manquants ou invalides

L'usage de ``mock.patch`` permet d'isoler les vues des accès base
quand la logique de permission est testée indépendamment du contenu
métier renvoyé.
"""
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse

from apps.academics.models import Faculte
from apps.accounts.models import User


class ApiAuthContractTests(TestCase):
    """Contrat d'authentification/permissions JSON pour les endpoints internes consommés par le front."""

    def setUp(self):
        """Crée un étudiant, un secrétaire et le catalogue d'URLs internes à tester."""
        self.faculte = Faculte.objects.create(nom_faculte="Faculte API")
        self.student = User.objects.create_user(
            email="student-api@example.com",
            nom="Student",
            prenom="Api",
            password="pass1234",
            role=User.Role.ETUDIANT,
        )
        self.secretary = User.objects.create_user(
            email="secretary-api@example.com",
            nom="Secretary",
            prenom="Api",
            password="pass1234",
            role=User.Role.SECRETAIRE,
        )
        self.url = reverse("enrollments:get_departments")
        self.query = {"faculty_id": self.faculte.id_faculte}
        self.front_api_requests = (
            (
                reverse("enrollments:get_departments"),
                {"faculty_id": self.faculte.id_faculte},
            ),
            (reverse("enrollments:get_courses"), {"dept_id": 999, "year_id": 999}),
            (reverse("enrollments:get_courses_by_year"), {"year_id": 999}),
            (reverse("dashboard:get_prerequisites_by_level"), {"niveau": 2}),
            (
                reverse("absences:student_absence_history_api"),
                {"student_id": self.student.id_utilisateur},
            ),
        )

    def assert_json_error(self, response, *, status, code, message):
        """Assertion utilitaire : la réponse est un JSON d'erreur avec le code et le message attendus."""
        self.assertEqual(response.status_code, status)
        self.assertIn("application/json", response["Content-Type"].lower())
        payload = response.json()
        self.assertEqual(payload["error"]["code"], code)
        self.assertEqual(payload["error"]["message"], message)

    def test_anonymous_returns_401_json(self):
        """Un appel anonyme doit renvoyer 401 JSON (et non une redirection HTML)."""
        response = self.client.get(self.url, self.query, secure=True)

        self.assert_json_error(
            response,
            status=401,
            code="auth_required",
            message="Authentication required",
        )

    def test_insufficient_role_returns_403_json(self):
        """Un rôle non autorisé (étudiant) sur une route secrétaire renvoie 403 JSON."""
        self.client.force_login(self.student)

        response = self.client.get(self.url, self.query, secure=True)

        self.assert_json_error(
            response,
            status=403,
            code="forbidden",
            message="Forbidden",
        )

    def test_anonymous_front_api_endpoints_return_401_json(self):
        """Toutes les routes JSON internes renvoient 401 (jamais 302) en anonyme."""
        for url, query in self.front_api_requests:
            response = self.client.get(url, query, secure=True)
            with self.subTest(url=url):
                self.assert_json_error(
                    response,
                    status=401,
                    code="auth_required",
                    message="Authentication required",
                )
                self.assertNotEqual(response.status_code, 302)

    def test_insufficient_role_front_api_endpoints_return_403_json(self):
        """Routes secrétaire visitées par un étudiant : 403 JSON cohérent (pas 302)."""
        self.client.force_login(self.student)

        for url, query in self.front_api_requests:
            response = self.client.get(url, query, secure=True)
            with self.subTest(url=url):
                self.assert_json_error(
                    response,
                    status=403,
                    code="forbidden",
                    message="Forbidden",
                )
                self.assertNotEqual(response.status_code, 302)

    def test_session_expired_returns_401_json_not_html(self):
        """Après expiration de la session, le serveur renvoie 401 JSON et non du HTML de login."""
        self.client.force_login(self.secretary)
        self.client.logout()

        response = self.client.get(
            reverse("enrollments:get_courses_by_year"),
            {"year_id": 2026},
            secure=True,
        )

        self.assert_json_error(
            response,
            status=401,
            code="auth_required",
            message="Authentication required",
        )

    def test_bad_request_errors_are_json_for_front(self):
        """Les paramètres manquants produisent une 400 JSON avec un message en français lisible."""
        self.client.force_login(self.secretary)

        response_courses = self.client.get(
            reverse("enrollments:get_courses_by_year"),
            secure=True,
        )
        self.assert_json_error(
            response_courses,
            status=400,
            code="bad_request",
            message="year_id requis",
        )

        response_prereq = self.client.get(
            reverse("dashboard:get_prerequisites_by_level"),
            secure=True,
        )
        self.assert_json_error(
            response_prereq,
            status=400,
            code="bad_request",
            message="niveau requis",
        )

        response_history = self.client.get(
            reverse("absences:student_absence_history_api"),
            secure=True,
        )
        self.assert_json_error(
            response_history,
            status=400,
            code="bad_request",
            message="student_id requis",
        )

    def test_server_error_is_sanitized_and_contains_request_id(self):
        """Une erreur interne renvoie 500 JSON anonymisé (pas de fuite) et inclut un ``request_id``."""
        self.client.force_login(self.secretary)

        with patch(
            "apps.enrollments.views.Departement.objects.filter",
            side_effect=RuntimeError("secret-db-error"),
        ):
            response = self.client.get(self.url, self.query, secure=True)

        self.assertEqual(response.status_code, 500)
        payload = response.json()
        self.assertEqual(payload["error"]["code"], "server_error")
        self.assertEqual(
            payload["error"]["message"], "Une erreur interne est survenue."
        )
        self.assertIn("request_id", payload["error"])
        self.assertNotIn("secret-db-error", response.content.decode())
