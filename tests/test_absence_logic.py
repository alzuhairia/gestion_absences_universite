"""
Tests for the new absence business logic:
- calculer_pourcentage_absence() — hours-based percentage calculation
- etudiants_en_alerte() — threshold alert detection
- Absence.clean() — duration vs seance validation
- Type choices: only ABSENT and PARTIEL allowed
"""

from datetime import date, time, timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from apps.absences.models import Absence
from apps.absences.services import (
    calculer_pourcentage_absence,
    etudiants_en_alerte,
)
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


class CalculerPourcentageAbsenceTest(AbsenceLogicBaseTestCase):
    """Tests for calculer_pourcentage_absence()."""

    def test_no_absences_returns_zero(self):
        """Student with no absences has 0% absence, 100% presence."""
        result = calculer_pourcentage_absence(self.student, self.cours)
        self.assertEqual(result["total_heures_absence"], 0.0)
        self.assertEqual(result["pourcentage_absence"], 0.0)
        self.assertEqual(result["pourcentage_presence"], 100.0)
        # 15 sessions * 4h = 60h total
        self.assertEqual(result["total_heures_cours"], 60.0)

    def test_one_full_absence(self):
        """One full absence of 4h → 4/60 = 6.67%."""
        Absence.objects.create(
            id_inscription=self.inscription,
            id_seance=self.seances[0],
            type_absence=Absence.TypeAbsence.ABSENT,
            duree_absence=Decimal("4.00"),
            statut=Absence.Statut.NON_JUSTIFIEE,
            encodee_par=self.prof,
        )
        result = calculer_pourcentage_absence(self.student, self.cours)
        self.assertEqual(result["total_heures_absence"], 4.0)
        self.assertAlmostEqual(result["pourcentage_absence"], 6.67, places=2)
        self.assertAlmostEqual(result["pourcentage_presence"], 93.33, places=2)

    def test_mixed_absent_and_partiel(self):
        """
        Example from requirements:
        - 1 full absence = 4h
        - 2 absences partielles = 1h + 2h = 3h
        - Total = 7h → 7/60 = 11.67%
        """
        # Full absence
        Absence.objects.create(
            id_inscription=self.inscription,
            id_seance=self.seances[0],
            type_absence=Absence.TypeAbsence.ABSENT,
            duree_absence=Decimal("4.00"),
            statut=Absence.Statut.NON_JUSTIFIEE,
            encodee_par=self.prof,
        )
        # Partiel 1: 1h
        Absence.objects.create(
            id_inscription=self.inscription,
            id_seance=self.seances[1],
            type_absence=Absence.TypeAbsence.PARTIEL,
            duree_absence=Decimal("1.00"),
            statut=Absence.Statut.NON_JUSTIFIEE,
            encodee_par=self.prof,
        )
        # Partiel 2: 2h
        Absence.objects.create(
            id_inscription=self.inscription,
            id_seance=self.seances[2],
            type_absence=Absence.TypeAbsence.PARTIEL,
            duree_absence=Decimal("2.00"),
            statut=Absence.Statut.NON_JUSTIFIEE,
            encodee_par=self.prof,
        )

        result = calculer_pourcentage_absence(self.student, self.cours)
        self.assertEqual(result["total_heures_absence"], 7.0)
        self.assertAlmostEqual(result["pourcentage_absence"], 11.67, places=2)
        self.assertAlmostEqual(result["pourcentage_presence"], 88.33, places=2)

    def test_justified_absences_not_counted(self):
        """Justified absences should NOT be counted in the percentage."""
        # 1 absence non justifiée (4h)
        Absence.objects.create(
            id_inscription=self.inscription,
            id_seance=self.seances[0],
            type_absence=Absence.TypeAbsence.ABSENT,
            duree_absence=Decimal("4.00"),
            statut=Absence.Statut.NON_JUSTIFIEE,
            encodee_par=self.prof,
        )
        # 1 absence justifiée (4h) — ne doit pas compter
        Absence.objects.create(
            id_inscription=self.inscription,
            id_seance=self.seances[1],
            type_absence=Absence.TypeAbsence.ABSENT,
            duree_absence=Decimal("4.00"),
            statut=Absence.Statut.JUSTIFIEE,
            encodee_par=self.prof,
        )

        result = calculer_pourcentage_absence(self.student, self.cours)
        self.assertEqual(result["total_heures_absence"], 4.0)  # Only the unjustified one
        self.assertAlmostEqual(result["pourcentage_absence"], 6.67, places=2)

    def test_en_attente_counts_as_non_justified(self):
        """EN_ATTENTE absences count as non-justified."""
        Absence.objects.create(
            id_inscription=self.inscription,
            id_seance=self.seances[0],
            type_absence=Absence.TypeAbsence.ABSENT,
            duree_absence=Decimal("4.00"),
            statut=Absence.Statut.EN_ATTENTE,
            encodee_par=self.prof,
        )
        result = calculer_pourcentage_absence(self.student, self.cours)
        self.assertEqual(result["total_heures_absence"], 4.0)

    def test_no_inscription_returns_zero(self):
        """Non-enrolled student returns 0% absence."""
        other_student = User.objects.create_user(
            email="other@test.com",
            nom="Other",
            prenom="Student",
            password="pass1234",
            role=User.Role.ETUDIANT,
        )
        result = calculer_pourcentage_absence(other_student, self.cours)
        self.assertEqual(result["total_heures_absence"], 0.0)
        self.assertEqual(result["pourcentage_absence"], 0.0)

    def test_zero_seances_returns_zero_percent(self):
        """Course with no séances → 0h total, 0% absence, 0% presence."""
        empty_cours = Cours.objects.create(
            code_cours="EMPTY",
            nom_cours="Empty Course",
            nombre_total_periodes=30,
            id_departement=self.departement,
            professeur=self.prof,
            id_annee=self.annee,
            niveau=1,
        )
        Inscription.objects.create(
            id_etudiant=self.student,
            id_cours=empty_cours,
            id_annee=self.annee,
        )
        result = calculer_pourcentage_absence(self.student, empty_cours)
        self.assertEqual(result["total_heures_cours"], 0.0)
        self.assertEqual(result["total_heures_absence"], 0.0)
        self.assertEqual(result["pourcentage_absence"], 0.0)
        self.assertEqual(result["pourcentage_presence"], 0.0)

    def test_future_seances_excluded(self):
        """Séances in the future should NOT be counted in total hours."""
        future_cours = Cours.objects.create(
            code_cours="FUTURE",
            nom_cours="Future Course",
            nombre_total_periodes=40,
            id_departement=self.departement,
            professeur=self.prof,
            id_annee=self.annee,
            niveau=1,
        )
        future_inscription = Inscription.objects.create(
            id_etudiant=self.student,
            id_cours=future_cours,
            id_annee=self.annee,
        )
        today = timezone.localdate()
        # 1 past séance (2h)
        past_seance = Seance.objects.create(
            date_seance=today - timedelta(days=5),
            heure_debut=time(10, 0),
            heure_fin=time(12, 0),
            id_cours=future_cours,
            id_annee=self.annee,
        )
        # 1 future séance (3h) — should be excluded
        Seance.objects.create(
            date_seance=today + timedelta(days=5),
            heure_debut=time(9, 0),
            heure_fin=time(12, 0),
            id_cours=future_cours,
            id_annee=self.annee,
        )
        # Absent on the past séance
        Absence.objects.create(
            id_inscription=future_inscription,
            id_seance=past_seance,
            type_absence=Absence.TypeAbsence.ABSENT,
            duree_absence=Decimal("2.00"),
            statut=Absence.Statut.NON_JUSTIFIEE,
            encodee_par=self.prof,
        )
        result = calculer_pourcentage_absence(self.student, future_cours)
        # Only the past séance counts: 2h total, 2h absent → 100%
        self.assertEqual(result["total_heures_cours"], 2.0)
        self.assertEqual(result["total_heures_absence"], 2.0)
        self.assertAlmostEqual(result["pourcentage_absence"], 100.0, places=2)

    def test_student_without_absence_full_presence(self):
        """Student enrolled but with zero absences → 100% presence."""
        result = calculer_pourcentage_absence(self.student, self.cours)
        self.assertEqual(result["pourcentage_presence"], 100.0)
        self.assertEqual(result["pourcentage_absence"], 0.0)
        self.assertEqual(result["total_heures_absence"], 0.0)


class EtudiantsEnAlerteTest(AbsenceLogicBaseTestCase):
    """Tests for etudiants_en_alerte()."""

    def test_no_absences_no_alerts(self):
        """No absences → no students in alert."""
        alertes = etudiants_en_alerte(self.cours, seuil=20)
        self.assertEqual(len(alertes), 0)

    def test_above_threshold_triggers_alert(self):
        """Student above 20% threshold appears in alert list."""
        # Create 4 full absences (4 * 4h = 16h → 16/60 = 26.7%)
        for i in range(4):
            Absence.objects.create(
                id_inscription=self.inscription,
                id_seance=self.seances[i],
                type_absence=Absence.TypeAbsence.ABSENT,
                duree_absence=Decimal("4.00"),
                statut=Absence.Statut.NON_JUSTIFIEE,
                encodee_par=self.prof,
            )

        alertes = etudiants_en_alerte(self.cours, seuil=20)
        self.assertEqual(len(alertes), 1)
        self.assertEqual(alertes[0]["etudiant"], self.student)
        self.assertAlmostEqual(alertes[0]["pourcentage_absence"], 26.67, places=2)
        self.assertTrue(alertes[0]["depasse_seuil"])

    def test_below_threshold_no_alert(self):
        """Student below threshold does not appear."""
        # 1 absence (4/60 = 6.67% < 20%)
        Absence.objects.create(
            id_inscription=self.inscription,
            id_seance=self.seances[0],
            type_absence=Absence.TypeAbsence.ABSENT,
            duree_absence=Decimal("4.00"),
            statut=Absence.Statut.NON_JUSTIFIEE,
            encodee_par=self.prof,
        )
        alertes = etudiants_en_alerte(self.cours, seuil=20)
        self.assertEqual(len(alertes), 0)

    def test_custom_threshold(self):
        """Custom threshold (10%) triggers alert at lower rate."""
        # 2 absences (8/60 = 13.33% > 10%)
        for i in range(2):
            Absence.objects.create(
                id_inscription=self.inscription,
                id_seance=self.seances[i],
                type_absence=Absence.TypeAbsence.ABSENT,
                duree_absence=Decimal("4.00"),
                statut=Absence.Statut.NON_JUSTIFIEE,
                encodee_par=self.prof,
            )
        alertes = etudiants_en_alerte(self.cours, seuil=10)
        self.assertEqual(len(alertes), 1)

    def test_multiple_students_sorted_by_rate(self):
        """Multiple students sorted by descending absence rate."""
        student2 = User.objects.create_user(
            email="stu2@test.com",
            nom="Student",
            prenom="Two",
            password="pass1234",
            role=User.Role.ETUDIANT,
        )
        inscription2 = Inscription.objects.create(
            id_etudiant=student2,
            id_cours=self.cours,
            id_annee=self.annee,
        )

        # Student 1: 4 absences (26.67%)
        for i in range(4):
            Absence.objects.create(
                id_inscription=self.inscription,
                id_seance=self.seances[i],
                type_absence=Absence.TypeAbsence.ABSENT,
                duree_absence=Decimal("4.00"),
                statut=Absence.Statut.NON_JUSTIFIEE,
                encodee_par=self.prof,
            )

        # Student 2: 5 absences (33.33%)
        for i in range(5):
            Absence.objects.create(
                id_inscription=inscription2,
                id_seance=self.seances[i],
                type_absence=Absence.TypeAbsence.ABSENT,
                duree_absence=Decimal("4.00"),
                statut=Absence.Statut.NON_JUSTIFIEE,
                encodee_par=self.prof,
            )

        alertes = etudiants_en_alerte(self.cours, seuil=20)
        self.assertEqual(len(alertes), 2)
        # Highest rate first
        self.assertEqual(alertes[0]["etudiant"], student2)
        self.assertEqual(alertes[1]["etudiant"], self.student)


class AbsenceValidationTest(AbsenceLogicBaseTestCase):
    """Tests for Absence model validation (clean method)."""

    def test_duration_cannot_exceed_seance(self):
        """duree_absence > seance duration raises ValidationError."""
        absence = Absence(
            id_inscription=self.inscription,
            id_seance=self.seances[0],  # 4h session
            type_absence=Absence.TypeAbsence.ABSENT,
            duree_absence=Decimal("5.00"),  # > 4h
            statut=Absence.Statut.NON_JUSTIFIEE,
            encodee_par=self.prof,
        )
        with self.assertRaises(ValidationError) as ctx:
            absence.clean()
        self.assertIn("duree_absence", ctx.exception.message_dict)

    def test_duration_equal_to_seance_is_valid(self):
        """duree_absence == seance duration is valid."""
        absence = Absence(
            id_inscription=self.inscription,
            id_seance=self.seances[0],  # 4h session
            type_absence=Absence.TypeAbsence.ABSENT,
            duree_absence=Decimal("4.00"),
            statut=Absence.Statut.NON_JUSTIFIEE,
            encodee_par=self.prof,
        )
        absence.clean()  # Should not raise

    def test_partiel_requires_positive_duration(self):
        """PARTIEL type with zero or missing duration raises ValidationError."""
        absence = Absence(
            id_inscription=self.inscription,
            id_seance=self.seances[0],
            type_absence=Absence.TypeAbsence.PARTIEL,
            duree_absence=Decimal("0"),
            statut=Absence.Statut.NON_JUSTIFIEE,
            encodee_par=self.prof,
        )
        with self.assertRaises(ValidationError):
            absence.clean()

    def test_partiel_with_valid_duration(self):
        """PARTIEL with valid partial duration passes validation."""
        absence = Absence(
            id_inscription=self.inscription,
            id_seance=self.seances[0],  # 4h session
            type_absence=Absence.TypeAbsence.PARTIEL,
            duree_absence=Decimal("1.50"),
            statut=Absence.Statut.NON_JUSTIFIEE,
            encodee_par=self.prof,
        )
        absence.clean()  # Should not raise

    def test_absent_type_choices(self):
        """Only ABSENT and PARTIEL are the primary type choices."""
        self.assertEqual(Absence.TypeAbsence.ABSENT, "ABSENT")
        self.assertEqual(Absence.TypeAbsence.PARTIEL, "PARTIEL")
