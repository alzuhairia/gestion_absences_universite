"""
Tests — validation du modèle Absence et caps sur le taux.
  - AbsenceValidationTest             : Absence.clean() (durée, type PARTIEL)
  - TauxCappedAt100Test               : taux plafonné à 100% sur données corrompues
  - EnAttenteExcludedFromThresholdTest: EN_ATTENTE exclus de toutes les statistiques
"""
from datetime import date, time
from decimal import Decimal

from django.core.exceptions import ValidationError

from apps.absences.models import Absence
from apps.absences.services import calculer_absence_stats, get_at_risk_count_for_queryset
from apps.academic_sessions.models import Seance
from apps.academics.models import Cours
from apps.enrollments.models import Inscription

from .test_absence_logic import AbsenceLogicBaseTestCase


class AbsenceValidationTest(AbsenceLogicBaseTestCase):
    """Tests de validation au niveau modèle ``Absence`` (méthode ``clean``)."""

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

    def test_absence_exceeds_seance_duration(self):
        """Creating an absence with duration > seance duration raises ValidationError."""
        with self.assertRaises(ValidationError) as ctx:
            Absence.objects.create(
                id_inscription=self.inscription,
                id_seance=self.seances[0],  # 4h session
                type_absence=Absence.TypeAbsence.ABSENT,
                duree_absence=Decimal("6.00"),  # > 4h
                statut=Absence.Statut.NON_JUSTIFIEE,
                encodee_par=self.prof,
            )
        self.assertIn("duree_absence", ctx.exception.message_dict)

    def test_partiel_equal_to_seance_duration_rejected(self):
        """PARTIEL with duration == seance duration is invalid (should use ABSENT)."""
        absence = Absence(
            id_inscription=self.inscription,
            id_seance=self.seances[0],  # 4h session
            type_absence=Absence.TypeAbsence.PARTIEL,
            duree_absence=Decimal("4.00"),  # == seance duration
            statut=Absence.Statut.NON_JUSTIFIEE,
            encodee_par=self.prof,
        )
        with self.assertRaises(ValidationError) as ctx:
            absence.clean()
        self.assertIn("duree_absence", ctx.exception.message_dict)

    def test_partiel_just_under_seance_duration_valid(self):
        """PARTIEL with duration slightly less than seance duration is valid."""
        absence = Absence(
            id_inscription=self.inscription,
            id_seance=self.seances[0],  # 4h session
            type_absence=Absence.TypeAbsence.PARTIEL,
            duree_absence=Decimal("3.99"),
            statut=Absence.Statut.NON_JUSTIFIEE,
            encodee_par=self.prof,
        )
        absence.clean()  # Should not raise


class TauxCappedAt100Test(AbsenceLogicBaseTestCase):
    """Tests that absence rate is capped at 100% even with corrupt data."""

    def test_calculer_absence_stats_capped_at_100(self):
        """
        If total absence hours somehow exceed total periods,
        taux should be capped at 100%.
        """
        # Course with only 2h total periods but we create a 4h absence
        small_course = Cours.objects.create(
            code_cours="TINY",
            nom_cours="Tiny Course",
            nombre_total_periodes=2,
            id_departement=self.departement,
            professeur=self.prof,
            id_annee=self.annee,
            niveau=1,
        )
        inscription = Inscription.objects.create(
            id_etudiant=self.student,
            id_cours=small_course,
            id_annee=self.annee,
        )
        seance = Seance.objects.create(
            date_seance=date(2026, 1, 5),  # past date so it counts after future-filter fix
            heure_debut=time(8, 0),
            heure_fin=time(12, 0),
            id_cours=small_course,
            id_annee=self.annee,
        )
        # Bypass model clean to simulate corrupt data (duree > total_periodes)
        Absence.objects.bulk_create([
            Absence(
                id_inscription=inscription,
                id_seance=seance,
                type_absence=Absence.TypeAbsence.ABSENT,
                duree_absence=Decimal("4.00"),
                statut=Absence.Statut.NON_JUSTIFIEE,
                encodee_par=self.prof,
            )
        ])

        stats = calculer_absence_stats(inscription)
        self.assertLessEqual(stats["taux"], 100)


class EnAttenteExcludedFromThresholdTest(AbsenceLogicBaseTestCase):
    """Les absences ``EN_ATTENTE`` doivent être exclues de tous les calculs de seuil/taux."""

    def _create_absence(self, seance_idx, statut, duree="4.00"):
        """Fabrique une absence sur la séance ``seance_idx`` avec le statut et la durée donnés."""
        return Absence.objects.create(
            id_inscription=self.inscription,
            id_seance=self.seances[seance_idx],
            type_absence=Absence.TypeAbsence.ABSENT,
            duree_absence=Decimal(duree),
            statut=statut,
            encodee_par=self.prof,
        )

    def test_calculer_absence_stats_excludes_en_attente(self):
        """calculer_absence_stats only counts NON_JUSTIFIEE."""
        self._create_absence(0, Absence.Statut.NON_JUSTIFIEE)
        self._create_absence(1, Absence.Statut.EN_ATTENTE)
        self._create_absence(2, Absence.Statut.JUSTIFIEE)

        stats = calculer_absence_stats(self.inscription)
        # Only the NON_JUSTIFIEE absence (4h / 60 periods)
        self.assertEqual(stats["total_absence"], 4.0)
        self.assertAlmostEqual(stats["taux"], 6.67, places=2)

    def test_etudiants_en_alerte_excludes_en_attente(self):
        """etudiants_en_alerte ignores EN_ATTENTE absences."""
        # 3 NON_JUSTIFIEE (12h/60 = 20%) — at threshold
        for i in range(3):
            self._create_absence(i, Absence.Statut.NON_JUSTIFIEE)
        # 3 EN_ATTENTE — should NOT push above threshold
        for i in range(3, 6):
            self._create_absence(i, Absence.Statut.EN_ATTENTE)

        from apps.absences.services import etudiants_en_alerte
        alertes = etudiants_en_alerte(self.cours, seuil=21)
        # 20% < 21% threshold → no alert (would be 40% if EN_ATTENTE counted)
        self.assertEqual(len(alertes), 0)

    def test_get_at_risk_count_excludes_en_attente(self):
        """get_at_risk_count_for_queryset ignores EN_ATTENTE."""
        # 3 NON_JUSTIFIEE (12h) + 3 EN_ATTENTE (12h)
        for i in range(3):
            self._create_absence(i, Absence.Statut.NON_JUSTIFIEE)
        for i in range(3, 6):
            self._create_absence(i, Absence.Statut.EN_ATTENTE)

        qs = Inscription.objects.filter(
            id_inscription=self.inscription.id_inscription
        ).select_related("id_cours")
        count, sums = get_at_risk_count_for_queryset(qs, system_threshold=21)
        # 12h / 60 = 20% < 21% → not at risk
        self.assertEqual(count, 0)
        # Only NON_JUSTIFIEE hours in the sums
        total = sums.get(self.inscription.id_inscription, 0) or 0
        self.assertEqual(float(total), 12.0)
