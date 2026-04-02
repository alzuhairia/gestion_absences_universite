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
            email="prof1-iso@example.com",
            nom="Prof",
            prenom="One",
            password="pass1234",
            role=User.Role.PROFESSEUR,
        )
        self.prof2 = User.objects.create_user(
            email="prof2-iso@example.com",
            nom="Prof",
            prenom="Two",
            password="pass1234",
            role=User.Role.PROFESSEUR,
        )
        self.student1 = User.objects.create_user(
            email="stu1-iso@example.com",
            nom="Stu",
            prenom="One",
            password="pass1234",
            role=User.Role.ETUDIANT,
        )
        self.student2 = User.objects.create_user(
            email="stu2-iso@example.com",
            nom="Stu",
            prenom="Two",
            password="pass1234",
            role=User.Role.ETUDIANT,
        )

        # Course 1 → prof1
        self.course1 = Cours.objects.create(
            code_cours="ISO1",
            nom_cours="Course One",
            nombre_total_periodes=20,
            id_departement=self.dept,
            professeur=self.prof1,
            id_annee=self.annee,
            niveau=1,
        )
        # Course 2 → prof2
        self.course2 = Cours.objects.create(
            code_cours="ISO2",
            nom_cours="Course Two",
            nombre_total_periodes=20,
            id_departement=self.dept,
            professeur=self.prof2,
            id_annee=self.annee,
            niveau=1,
        )

        self.ins1 = Inscription.objects.create(
            id_etudiant=self.student1,
            id_cours=self.course1,
            id_annee=self.annee,
        )
        self.ins2 = Inscription.objects.create(
            id_etudiant=self.student2,
            id_cours=self.course2,
            id_annee=self.annee,
        )

        seance1 = Seance.objects.create(
            date_seance=date(2026, 1, 5),
            heure_debut=time(8, 0),
            heure_fin=time(10, 0),
            id_cours=self.course1,
            id_annee=self.annee,
        )
        seance2 = Seance.objects.create(
            date_seance=date(2026, 1, 5),
            heure_debut=time(8, 0),
            heure_fin=time(10, 0),
            id_cours=self.course2,
            id_annee=self.annee,
        )

        self.absence1 = Absence.objects.create(
            id_inscription=self.ins1,
            id_seance=seance1,
            type_absence="ABSENT",
            duree_absence=Decimal("2.0"),
            statut="NON_JUSTIFIEE",
            encodee_par=self.prof1,
        )
        self.absence2 = Absence.objects.create(
            id_inscription=self.ins2,
            id_seance=seance2,
            type_absence="ABSENT",
            duree_absence=Decimal("2.0"),
            statut="NON_JUSTIFIEE",
            encodee_par=self.prof2,
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


class PdfExportTests(TestCase):
    """Tests for the student PDF export API endpoint."""

    def setUp(self):
        self.faculte = Faculte.objects.create(nom_faculte="Fac PDF")
        self.dept = Departement.objects.create(
            nom_departement="Dept PDF", id_faculte=self.faculte
        )
        self.annee = AnneeAcademique.objects.create(libelle="2025-2026", active=True)
        self.prof = User.objects.create_user(
            email="prof-pdf@example.com",
            nom="Prof",
            prenom="PDF",
            password="pass1234",
            role=User.Role.PROFESSEUR,
        )
        self.secretary = User.objects.create_user(
            email="sec-pdf@example.com",
            nom="Sec",
            prenom="PDF",
            password="pass1234",
            role=User.Role.SECRETAIRE,
        )
        self.student = User.objects.create_user(
            email="stu-pdf@example.com",
            nom="Stu",
            prenom="PDF",
            password="pass1234",
            role=User.Role.ETUDIANT,
        )
        self.course = Cours.objects.create(
            code_cours="PDF1",
            nom_cours="PDF Course",
            nombre_total_periodes=200,
            id_departement=self.dept,
            professeur=self.prof,
            id_annee=self.annee,
            niveau=1,
        )
        self.inscription = Inscription.objects.create(
            id_etudiant=self.student,
            id_cours=self.course,
            id_annee=self.annee,
        )

    def test_pdf_export_with_large_dataset_does_not_crash(self):
        """
        PDF export with many absences (multi-page) completes without error.
        Verifies the 500-row cap and page-break logic handle volume.
        """
        # Create 60 seances + absences — enough to span multiple PDF pages
        seances = Seance.objects.bulk_create(
            [
                Seance(
                    date_seance=date(2026, 1, 1)
                    + __import__("datetime").timedelta(days=i),
                    heure_debut=time(8, 0),
                    heure_fin=time(10, 0),
                    id_cours=self.course,
                    id_annee=self.annee,
                )
                for i in range(60)
            ]
        )
        Absence.objects.bulk_create(
            [
                Absence(
                    id_inscription=self.inscription,
                    id_seance=s,
                    type_absence="ABSENT",
                    duree_absence=Decimal("2.0"),
                    statut="NON_JUSTIFIEE",
                    encodee_par=self.prof,
                )
                for s in seances
            ]
        )

        self.client.force_login(self.secretary)
        url = reverse("api:export-student-pdf", args=[self.student.pk])
        response = self.client.get(url, secure=True)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertIn(b"%PDF", response.content[:10])

    def test_pdf_export_error_returns_500_json(self):
        """If PDF generation crashes, return a clean 500, not an unhandled exception."""
        self.client.force_login(self.secretary)
        url = reverse("api:export-student-pdf", args=[self.student.pk])

        with patch(
            "apps.api.views._build_student_pdf",
            side_effect=RuntimeError("canvas exploded"),
        ):
            response = self.client.get(url, secure=True)

        self.assertEqual(response.status_code, 500)
        self.assertIn("generation", response.json()["detail"])


class StudentApiIsolationTests(TestCase):
    """Tests that the Student API enforces per-role data isolation."""

    def setUp(self):
        self.faculte = Faculte.objects.create(nom_faculte="Fac STU")
        self.dept = Departement.objects.create(
            nom_departement="Dept STU", id_faculte=self.faculte
        )
        self.annee = AnneeAcademique.objects.create(libelle="2025-2026", active=True)

        self.admin = User.objects.create_user(
            email="admin-stu@example.com",
            nom="Admin",
            prenom="Stu",
            password="pass1234",
            role=User.Role.ADMIN,
        )
        self.prof = User.objects.create_user(
            email="prof-stu@example.com",
            nom="Prof",
            prenom="Stu",
            password="pass1234",
            role=User.Role.PROFESSEUR,
        )
        self.prof2 = User.objects.create_user(
            email="prof2-stu@example.com",
            nom="Prof2",
            prenom="Stu",
            password="pass1234",
            role=User.Role.PROFESSEUR,
        )
        self.student1 = User.objects.create_user(
            email="stu1-stu@example.com",
            nom="Stu",
            prenom="One",
            password="pass1234",
            role=User.Role.ETUDIANT,
        )
        self.student2 = User.objects.create_user(
            email="stu2-stu@example.com",
            nom="Stu",
            prenom="Two",
            password="pass1234",
            role=User.Role.ETUDIANT,
        )

        # Course taught by prof — student1 enrolled
        self.course = Cours.objects.create(
            code_cours="STU1",
            nom_cours="Course Stu",
            nombre_total_periodes=20,
            id_departement=self.dept,
            professeur=self.prof,
            id_annee=self.annee,
            niveau=1,
        )
        Inscription.objects.create(
            id_etudiant=self.student1,
            id_cours=self.course,
            id_annee=self.annee,
        )

        self.url = reverse("api:student-list")

    def test_student_cannot_list_other_students(self):
        """A student hitting the student list endpoint sees only themselves."""
        self.client.force_login(self.student1)
        response = self.client.get(self.url, secure=True)
        self.assertEqual(response.status_code, 200)

        ids = [s["id_utilisateur"] for s in response.json()["results"]]
        self.assertEqual(ids, [self.student1.pk])
        self.assertNotIn(self.student2.pk, ids)

    def test_professor_sees_only_enrolled_students(self):
        """A professor sees only students enrolled in their courses."""
        self.client.force_login(self.prof)
        response = self.client.get(self.url, secure=True)
        self.assertEqual(response.status_code, 200)

        ids = [s["id_utilisateur"] for s in response.json()["results"]]
        self.assertIn(self.student1.pk, ids)
        self.assertNotIn(self.student2.pk, ids)

    def test_professor_without_students_sees_empty(self):
        """A professor with no enrolled students gets an empty list."""
        self.client.force_login(self.prof2)
        response = self.client.get(self.url, secure=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["results"], [])

    def test_admin_sees_all_students(self):
        """Admin sees every student."""
        self.client.force_login(self.admin)
        response = self.client.get(self.url, secure=True)
        self.assertEqual(response.status_code, 200)

        ids = [s["id_utilisateur"] for s in response.json()["results"]]
        self.assertIn(self.student1.pk, ids)
        self.assertIn(self.student2.pk, ids)


class ApiAcademicYearIsolationTests(TestCase):
    """Professor API endpoints must restrict data to the active academic year."""

    def setUp(self):
        self.faculte = Faculte.objects.create(nom_faculte="Fac Year Isolation")
        self.dept = Departement.objects.create(
            nom_departement="Dept Year Isolation", id_faculte=self.faculte
        )
        self.old_year = AnneeAcademique.objects.create(
            libelle="2024-2025", active=False
        )
        self.current_year = AnneeAcademique.objects.create(
            libelle="2025-2026", active=True
        )

        self.prof = User.objects.create_user(
            email="prof-yr@example.com",
            nom="Prof",
            prenom="Year",
            password="pass1234",
            role=User.Role.PROFESSEUR,
        )
        self.student = User.objects.create_user(
            email="stu-yr@example.com",
            nom="Stu",
            prenom="Year",
            password="pass1234",
            role=User.Role.ETUDIANT,
        )

        self.course = Cours.objects.create(
            code_cours="YR1",
            nom_cours="Year Course",
            nombre_total_periodes=40,
            id_departement=self.dept,
            professeur=self.prof,
            id_annee=self.current_year,
            niveau=1,
        )

        # Old enrollment (should NOT be visible)
        self.old_inscription = Inscription.objects.create(
            id_etudiant=self.student,
            id_cours=self.course,
            id_annee=self.old_year,
            status=Inscription.Status.EN_COURS,
        )
        # Current enrollment (should be visible)
        self.current_inscription = Inscription.objects.create(
            id_etudiant=self.student,
            id_cours=self.course,
            id_annee=self.current_year,
            status=Inscription.Status.EN_COURS,
        )

    def test_professor_inscriptions_filtered_by_active_year(self):
        """InscriptionViewSet for professors must only return current year inscriptions."""
        self.client.force_login(self.prof)
        response = self.client.get(reverse("api:enrollment-list"), secure=True)
        self.assertEqual(response.status_code, 200)

        ids = [i["id_inscription"] for i in response.json()["results"]]
        self.assertIn(self.current_inscription.id_inscription, ids)
        self.assertNotIn(self.old_inscription.id_inscription, ids)

    def test_professor_absences_filtered_by_active_year(self):
        """AbsenceViewSet for professors must only return current year absences."""
        # Create absences for both years
        old_seance = Seance.objects.create(
            date_seance=date(2025, 3, 1),
            heure_debut=time(8, 0),
            heure_fin=time(10, 0),
            id_cours=self.course,
            id_annee=self.old_year,
        )
        current_seance = Seance.objects.create(
            date_seance=date(2026, 3, 1),
            heure_debut=time(8, 0),
            heure_fin=time(10, 0),
            id_cours=self.course,
            id_annee=self.current_year,
        )
        old_absence = Absence.objects.create(
            id_inscription=self.old_inscription,
            id_seance=old_seance,
            type_absence="ABSENT",
            duree_absence=Decimal("2.0"),
            statut="NON_JUSTIFIEE",
            encodee_par=self.prof,
        )
        current_absence = Absence.objects.create(
            id_inscription=self.current_inscription,
            id_seance=current_seance,
            type_absence="ABSENT",
            duree_absence=Decimal("2.0"),
            statut="NON_JUSTIFIEE",
            encodee_par=self.prof,
        )

        self.client.force_login(self.prof)
        response = self.client.get(reverse("api:absence-list"), secure=True)
        self.assertEqual(response.status_code, 200)

        ids = [a["id_absence"] for a in response.json()["results"]]
        self.assertIn(current_absence.id_absence, ids)
        self.assertNotIn(old_absence.id_absence, ids)
