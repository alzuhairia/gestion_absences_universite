"""
Tests — isolation des données par rôle dans les endpoints API.
  - AbsenceApiIsolationTests       : prof voit seulement ses cours, étudiant ses propres absences
  - StudentApiIsolationTests       : étudiant/prof/admin — filtrage de la liste étudiants
  - ApiAcademicYearIsolationTests  : données filtrées par année académique active
"""
from datetime import date, time
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from apps.absences.models import Absence
from apps.academic_sessions.models import AnneeAcademique, Seance
from apps.academics.models import Cours, Departement, Faculte
from apps.accounts.models import User
from apps.enrollments.models import Inscription


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
