"""
Base test case for absence business logic tests.
Sub-files: test_absence_rates.py, test_absence_validation.py, test_absence_integration.py
"""
from datetime import date, time

from django.test import TestCase

from apps.academic_sessions.models import AnneeAcademique, Seance
from apps.academics.models import Cours, Departement, Faculte
from apps.accounts.models import User
from apps.enrollments.models import Inscription


class AbsenceLogicBaseTestCase(TestCase):
    """Base test case with shared fixtures."""

    def setUp(self):
        self.faculte = Faculte.objects.create(nom_faculte="Faculte Test")
        self.departement = Departement.objects.create(
            nom_departement="Departement Test",
            id_faculte=self.faculte,
        )
        self.annee = AnneeAcademique.objects.create(libelle="2025-2026", active=True)

        self.prof = User.objects.create_user(
            email="prof@test.com",
            nom="Prof",
            prenom="Test",
            password="pass1234",
            role=User.Role.PROFESSEUR,
        )
        self.student = User.objects.create_user(
            email="stu@test.com",
            nom="Etudiant",
            prenom="Test",
            password="pass1234",
            role=User.Role.ETUDIANT,
        )

        # Course: Python — 60h total (15 sessions of 4h)
        self.cours = Cours.objects.create(
            code_cours="PYTHON",
            nom_cours="Python",
            nombre_total_periodes=60,
            id_departement=self.departement,
            professeur=self.prof,
            id_annee=self.annee,
            niveau=1,
        )

        self.inscription = Inscription.objects.create(
            id_etudiant=self.student,
            id_cours=self.cours,
            id_annee=self.annee,
        )

        # Create 15 sessions of 4h each
        self.seances = []
        for day in range(1, 16):
            seance = Seance.objects.create(
                date_seance=date(2026, 1, day),
                heure_debut=time(8, 0),
                heure_fin=time(12, 0),
                id_cours=self.cours,
                id_annee=self.annee,
            )
            self.seances.append(seance)
