from datetime import date, time

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apps.accounts.models import User
from apps.academics.models import Cours, Departement, Faculte
from apps.academic_sessions.models import AnneeAcademique, Seance
from apps.absences.models import Absence
from apps.enrollments.models import Inscription


class QueryBudgetTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.faculte = Faculte.objects.create(nom_faculte='Faculte Perf')
        cls.departement = Departement.objects.create(
            nom_departement='Departement Perf',
            id_faculte=cls.faculte,
        )
        cls.annee = AnneeAcademique.objects.create(libelle='2025-2026', active=True)

        cls.admin = User.objects.create_user(
            email='admin-perf@example.com',
            nom='Admin',
            prenom='Perf',
            password='pass1234',
            role=User.Role.ADMIN,
        )
        cls.secretary = User.objects.create_user(
            email='secretary-perf@example.com',
            nom='Secretary',
            prenom='Perf',
            password='pass1234',
            role=User.Role.SECRETAIRE,
        )
        cls.professor = User.objects.create_user(
            email='prof-perf@example.com',
            nom='Professor',
            prenom='Perf',
            password='pass1234',
            role=User.Role.PROFESSEUR,
        )

        cls.students = []
        for idx in range(1, 11):
            cls.students.append(
                User.objects.create_user(
                    email=f'student-perf-{idx}@example.com',
                    nom='Student',
                    prenom=f'Perf{idx}',
                    password='pass1234',
                    role=User.Role.ETUDIANT,
                )
            )

        cls.courses = []
        cls.inscriptions_by_course = {}

        for idx in range(1, 6):
            course = Cours.objects.create(
                code_cours=f'PERF{idx}',
                nom_cours=f'Course Perf {idx}',
                nombre_total_periodes=30,
                id_departement=cls.departement,
                professeur=cls.professor,
                id_annee=cls.annee,
                niveau=1,
            )
            cls.courses.append(course)

            seances = []
            for day in range(1, 5):
                seances.append(
                    Seance.objects.create(
                        date_seance=date(2026, idx, day),
                        heure_debut=time(8, 0),
                        heure_fin=time(10, 0),
                        id_cours=course,
                        id_annee=cls.annee,
                    )
                )

            inscriptions = []
            for student in cls.students:
                inscriptions.append(
                    Inscription.objects.create(
                        id_etudiant=student,
                        id_cours=course,
                        id_annee=cls.annee,
                        status='EN_COURS',
                    )
                )
            cls.inscriptions_by_course[course.id_cours] = inscriptions

            for ins in inscriptions[:4]:
                Absence.objects.create(
                    id_inscription=ins,
                    id_seance=seances[0],
                    type_absence='SEANCE',
                    duree_absence=2.0,
                    statut='NON_JUSTIFIEE',
                    encodee_par=cls.secretary,
                )

    def assert_max_queries(self, max_queries, func, *args, **kwargs):
        # Warm up session/auth and URL resolver to reduce CI flakiness.
        func(*args, **kwargs)

        with CaptureQueriesContext(connection) as captured:
            response = func(*args, **kwargs)
            if hasattr(response, 'render') and callable(response.render):
                response.render()

        self.assertLessEqual(
            len(captured),
            max_queries,
            (
                f"Trop de requetes SQL: {len(captured)} (max: {max_queries}).\n"
                + "\n".join(q['sql'] for q in captured.captured_queries[:12])
            ),
        )
        return response

    def test_active_courses_query_budget(self):
        self.client.force_login(self.admin)
        response = self.assert_max_queries(
            12,
            self.client.get,
            reverse('dashboard:active_courses'),
            secure=True,
        )
        self.assertEqual(response.status_code, 200)

    def test_student_courses_query_budget(self):
        self.client.force_login(self.students[0])
        response = self.assert_max_queries(
            10,
            self.client.get,
            reverse('dashboard:student_courses'),
            secure=True,
        )
        self.assertEqual(response.status_code, 200)

    def test_instructor_course_detail_query_budget(self):
        self.client.force_login(self.professor)
        response = self.assert_max_queries(
            14,
            self.client.get,
            reverse('dashboard:instructor_course_detail', args=[self.courses[0].id_cours]),
            secure=True,
        )
        self.assertEqual(response.status_code, 200)

    def test_rules_management_query_budget(self):
        self.client.force_login(self.secretary)
        response = self.assert_max_queries(
            8,
            self.client.get,
            reverse('enrollments:rules_management'),
            secure=True,
        )
        self.assertEqual(response.status_code, 200)

    def test_get_courses_api_query_budget(self):
        self.client.force_login(self.secretary)
        response = self.assert_max_queries(
            5,
            self.client.get,
            reverse('enrollments:get_courses'),
            {'dept_id': self.departement.id_departement, 'year_id': self.annee.id_annee},
            secure=True,
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIsInstance(payload, list)
