"""
Cas de tests pour les fonctionnalités liées aux absences.

Ce module contient les tests unitaires couvrant la création d'absences, le
workflow de justification et la logique métier associée. Il définit aussi le
cas de test de base (utilisateurs, cours, inscriptions) réutilisé par les
autres classes de tests d'absences.

Fait partie de la suite de tests UniAbsences.
"""
from django.test import TestCase

from apps.academic_sessions.models import AnneeAcademique
from apps.academics.models import Cours, Departement, Faculte
from apps.accounts.models import User
from apps.enrollments.models import Inscription


class BaseAbsenceTestCase(TestCase):
    """
    Cas de test de base fournissant un setup commun aux tests d'absences.

    Crée les utilisateurs de test (admin, professeur, secrétaire, étudiants),
    une faculté, un département, une année académique, des cours et les
    inscriptions correspondantes.
    """

    def setUp(self):
        """Initialise les acteurs et le dataset minimal partagés par les sous-classes."""
        self.faculte = Faculte.objects.create(nom_faculte="Faculte Test")
        self.departement = Departement.objects.create(
            nom_departement="Departement Test",
            id_faculte=self.faculte,
        )
        self.annee = AnneeAcademique.objects.create(libelle="2024-2025", active=True)

        self.admin = User.objects.create_user(
            email="admin@example.com",
            nom="Admin",
            prenom="Test",
            password="pass1234",
            role=User.Role.ADMIN,
        )
        self.prof = User.objects.create_user(
            email="prof@example.com",
            nom="Prof",
            prenom="Test",
            password="pass1234",
            role=User.Role.PROFESSEUR,
        )
        self.secretary = User.objects.create_user(
            email="sec@example.com",
            nom="Sec",
            prenom="Test",
            password="pass1234",
            role=User.Role.SECRETAIRE,
        )
        self.student1 = User.objects.create_user(
            email="stu1@example.com",
            nom="Student",
            prenom="One",
            password="pass1234",
            role=User.Role.ETUDIANT,
        )
        self.student2 = User.objects.create_user(
            email="stu2@example.com",
            nom="Student",
            prenom="Two",
            password="pass1234",
            role=User.Role.ETUDIANT,
        )

        self.course1 = Cours.objects.create(
            code_cours="C1",
            nom_cours="Course 1",
            nombre_total_periodes=20,
            id_departement=self.departement,
            professeur=self.prof,
            id_annee=self.annee,
            niveau=1,
        )
        self.course2 = Cours.objects.create(
            code_cours="C2",
            nom_cours="Course 2",
            nombre_total_periodes=20,
            id_departement=self.departement,
            professeur=self.prof,
            id_annee=self.annee,
            niveau=1,
        )

        self.inscription1 = Inscription.objects.create(
            id_etudiant=self.student1,
            id_cours=self.course1,
            id_annee=self.annee,
        )
        self.inscription2 = Inscription.objects.create(
            id_etudiant=self.student2,
            id_cours=self.course2,
            id_annee=self.annee,
        )
