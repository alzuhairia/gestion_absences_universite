from pathlib import Path

from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from apps.accounts.models import User
from apps.academics.models import Faculte


class FrontendFetchGuardTemplateTests(SimpleTestCase):
    TEMPLATE_ASSERTIONS = {
        'templates/enrollments/manager.html': [
            "fetchJson",
            "'X-Requested-With': 'XMLHttpRequest'",
            "content-type",
            "if (!response.ok)",
            "response.json(",
            "application/json",
        ],
        'templates/enrollments/enrollment_form.html': [
            "fetchJson",
            "'X-Requested-With': 'XMLHttpRequest'",
            "content-type",
            "if (!response.ok)",
            "response.json(",
            "application/json",
        ],
        'templates/dashboard/secretary_courses.html': [
            "fetchJson",
            "'X-Requested-With': 'XMLHttpRequest'",
            "content-type",
            "if (!response.ok)",
            "response.json(",
            "application/json",
        ],
        'templates/dashboard/secretary_course_edit.html': [
            "fetchJson",
            "'X-Requested-With': 'XMLHttpRequest'",
            "content-type",
            "if (!response.ok)",
            "response.json(",
            "application/json",
        ],
    }

    XSS_SENSITIVE_TEMPLATES = (
        'templates/dashboard/admin_users.html',
        'templates/dashboard/secretary_courses.html',
        'templates/dashboard/secretary_course_edit.html',
    )

    def test_templates_keep_fetch_guard_rails(self):
        for template_path, expected_snippets in self.TEMPLATE_ASSERTIONS.items():
            with self.subTest(template=template_path):
                content = Path(template_path).read_text(encoding='utf-8').lower()
                for snippet in expected_snippets:
                    self.assertIn(snippet.lower(), content)

    def test_sensitive_templates_do_not_use_inner_html(self):
        for template_path in self.XSS_SENSITIVE_TEMPLATES:
            with self.subTest(template=template_path):
                content = Path(template_path).read_text(encoding='utf-8').lower()
                self.assertNotIn('innerhtml', content)
                self.assertNotIn('outerhtml', content)
                self.assertNotIn('insertadjacenthtml', content)


class FrontendSessionExpiryContractTests(TestCase):
    def setUp(self):
        self.faculte = Faculte.objects.create(nom_faculte='Faculte Front Contract')
        self.secretary = User.objects.create_user(
            email='front-secretary@example.com',
            nom='Front',
            prenom='Secretary',
            password='pass1234',
            role=User.Role.SECRETAIRE,
        )

        self.endpoints = (
            (reverse('enrollments:get_departments'), {'faculty_id': self.faculte.id_faculte}),
            (reverse('enrollments:get_courses'), {'dept_id': 999, 'year_id': 999}),
            (reverse('enrollments:get_courses_by_year'), {'year_id': 999}),
            (reverse('dashboard:get_prerequisites_by_level'), {'niveau': 2}),
            (reverse('absences:student_absence_history_api'), {'student_id': 1}),
        )

    def test_expired_session_returns_json_401_for_front_endpoints(self):
        self.client.force_login(self.secretary)
        self.client.logout()

        for url, query in self.endpoints:
            with self.subTest(url=url):
                response = self.client.get(url, query, secure=True)
                self.assertEqual(response.status_code, 401)
                self.assertIn('application/json', response['Content-Type'].lower())
                payload = response.json()
                self.assertEqual(payload['error']['code'], 'auth_required')
                self.assertEqual(payload['error']['message'], 'Authentication required')
