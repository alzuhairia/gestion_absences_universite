from datetime import date, time
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse

from apps.absences.models import Absence
from apps.academic_sessions.models import AnneeAcademique, Seance
from apps.academics.models import Cours, Departement, Faculte
from apps.accounts.models import User
from apps.enrollments.models import Inscription


class ApiAuthContractTests(TestCase):
    def setUp(self):
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
        self.assertEqual(response.status_code, status)
        self.assertIn("application/json", response["Content-Type"].lower())
        payload = response.json()
        self.assertEqual(payload["error"]["code"], code)
        self.assertEqual(payload["error"]["message"], message)

    def test_anonymous_returns_401_json(self):
        response = self.client.get(self.url, self.query, secure=True)

        self.assert_json_error(
            response,
            status=401,
            code="auth_required",
            message="Authentication required",
        )

    def test_insufficient_role_returns_403_json(self):
        self.client.force_login(self.student)

        response = self.client.get(self.url, self.query, secure=True)

        self.assert_json_error(
            response,
            status=403,
            code="forbidden",
            message="Forbidden",
        )

    def test_anonymous_front_api_endpoints_return_401_json(self):
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


class AbsenceApiIsolationTests(TestCase):
    """Tests that the Absence API enforces per-role data isolation."""

    def setUp(self):
        self.faculte = Faculte.objects.create(nom_faculte="Fac ISO")
        self.dept = Departement.objects.create(
            nom_departement="Dept ISO", id_faculte=self.faculte
        )
        self.annee = AnneeAcademique.objects.create(libelle="2025-2026", active=True)

        self.prof1 = User.objects.create_user(
            email="prof1-iso@example.com", nom="Prof", prenom="One",
            password="pass1234", role=User.Role.PROFESSEUR,
        )
        self.prof2 = User.objects.create_user(
            email="prof2-iso@example.com", nom="Prof", prenom="Two",
            password="pass1234", role=User.Role.PROFESSEUR,
        )
        self.student1 = User.objects.create_user(
            email="stu1-iso@example.com", nom="Stu", prenom="One",
            password="pass1234", role=User.Role.ETUDIANT,
        )
        self.student2 = User.objects.create_user(
            email="stu2-iso@example.com", nom="Stu", prenom="Two",
            password="pass1234", role=User.Role.ETUDIANT,
        )

        # Course 1 → prof1
        self.course1 = Cours.objects.create(
            code_cours="ISO1", nom_cours="Course One",
            nombre_total_periodes=20, id_departement=self.dept,
            professeur=self.prof1, id_annee=self.annee, niveau=1,
        )
        # Course 2 → prof2
        self.course2 = Cours.objects.create(
            code_cours="ISO2", nom_cours="Course Two",
            nombre_total_periodes=20, id_departement=self.dept,
            professeur=self.prof2, id_annee=self.annee, niveau=1,
        )

        self.ins1 = Inscription.objects.create(
            id_etudiant=self.student1, id_cours=self.course1, id_annee=self.annee,
        )
        self.ins2 = Inscription.objects.create(
            id_etudiant=self.student2, id_cours=self.course2, id_annee=self.annee,
        )

        seance1 = Seance.objects.create(
            date_seance=date(2026, 1, 5), heure_debut=time(8, 0),
            heure_fin=time(10, 0), id_cours=self.course1, id_annee=self.annee,
        )
        seance2 = Seance.objects.create(
            date_seance=date(2026, 1, 5), heure_debut=time(8, 0),
            heure_fin=time(10, 0), id_cours=self.course2, id_annee=self.annee,
        )

        self.absence1 = Absence.objects.create(
            id_inscription=self.ins1, id_seance=seance1,
            type_absence="ABSENT", duree_absence=Decimal("2.0"),
            statut="NON_JUSTIFIEE", encodee_par=self.prof1,
        )
        self.absence2 = Absence.objects.create(
            id_inscription=self.ins2, id_seance=seance2,
            type_absence="ABSENT", duree_absence=Decimal("2.0"),
            statut="NON_JUSTIFIEE", encodee_par=self.prof2,
        )

        self.url = reverse("api:absence-list")

    def test_professor_cannot_see_other_courses_absences(self):
        """Prof1 sees only absences from their own courses, not prof2's."""
        self.client.force_login(self.prof1)
        response = self.client.get(self.url, secure=True)
        self.assertEqual(response.status_code, 200)

        ids = [a["id_absence"] for a in response.json()["results"]]
        self.assertIn(self.absence1.pk, ids)
        self.assertNotIn(self.absence2.pk, ids)

    def test_student_cannot_see_other_students_absences(self):
        """Student1 sees only their own absences, not student2's."""
        self.client.force_login(self.student1)
        response = self.client.get(self.url, secure=True)
        self.assertEqual(response.status_code, 200)

        ids = [a["id_absence"] for a in response.json()["results"]]
        self.assertIn(self.absence1.pk, ids)
        self.assertNotIn(self.absence2.pk, ids)
