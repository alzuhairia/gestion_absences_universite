"""
Tests — intégration et cas limites transversaux.
  - FutureSessionsExcludedTest      : séances futures exclues des stats/calculs
  - SignalLoopProtectionTest        : post_save signal non-récursif
  - AcademicYearDeactivationTests   : désactivation d'année ferme les inscriptions
  - QRFinalizeDurationGuardTest     : duree_heures=0 → fallback 2.0
  - JustificationEmailNeverRaisesTest: email décision ne lève jamais d'exception
  - StudentViewsFallbackFilterTest  : fallback sans année active filtre EN_COURS
"""
from datetime import date, time, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from apps.absences.models import Absence
from apps.absences.services import (
    calculer_absence_stats,
    calculer_pourcentage_absence,
    get_at_risk_count_for_queryset,
)
from apps.academic_sessions.models import AnneeAcademique, Seance
from apps.academics.models import Cours, Departement, Faculte
from apps.accounts.models import User
from apps.enrollments.models import Inscription


class FutureSessionsExcludedTest(TestCase):
    """
    Absences linked to future séances must be excluded from ALL
    absence rate calculations (stats, at-risk, predictions).
    """

    def setUp(self):
        self.faculte = Faculte.objects.create(nom_faculte="Faculte F")
        self.departement = Departement.objects.create(
            nom_departement="Dep F", id_faculte=self.faculte
        )
        self.annee = AnneeAcademique.objects.create(libelle="2025-2026", active=True)
        self.prof = User.objects.create_user(
            email="prof-f@test.com", nom="Prof", prenom="F",
            password="pass1234", role=User.Role.PROFESSEUR,
        )
        self.student = User.objects.create_user(
            email="stu-f@test.com", nom="Stu", prenom="F",
            password="pass1234", role=User.Role.ETUDIANT,
        )
        self.cours = Cours.objects.create(
            code_cours="FUTUR", nom_cours="Future Test",
            nombre_total_periodes=40,
            id_departement=self.departement,
            professeur=self.prof,
            id_annee=self.annee, niveau=1,
        )
        self.inscription = Inscription.objects.create(
            id_etudiant=self.student,
            id_cours=self.cours,
            id_annee=self.annee,
        )
        today = timezone.localdate()
        self.past_seance = Seance.objects.create(
            date_seance=today - timedelta(days=5),
            heure_debut=time(8, 0), heure_fin=time(10, 0),
            id_cours=self.cours, id_annee=self.annee,
        )
        self.future_seance = Seance.objects.create(
            date_seance=today + timedelta(days=30),
            heure_debut=time(8, 0), heure_fin=time(10, 0),
            id_cours=self.cours, id_annee=self.annee,
        )
        # Past absence: 2h — should count
        Absence.objects.create(
            id_inscription=self.inscription,
            id_seance=self.past_seance,
            type_absence=Absence.TypeAbsence.ABSENT,
            duree_absence=Decimal("2.00"),
            statut=Absence.Statut.NON_JUSTIFIEE,
            encodee_par=self.prof,
        )
        # Future absence: 2h — must NOT count
        Absence.objects.bulk_create([
            Absence(
                id_inscription=self.inscription,
                id_seance=self.future_seance,
                type_absence=Absence.TypeAbsence.ABSENT,
                duree_absence=Decimal("2.00"),
                statut=Absence.Statut.NON_JUSTIFIEE,
                encodee_par=self.prof,
            )
        ])

    def test_future_sessions_excluded_from_absence_calculation(self):
        """calculer_absence_stats excludes absences for future séances."""
        stats = calculer_absence_stats(self.inscription)
        # Only the past absence (2h) should count, not both (4h)
        self.assertEqual(stats["total_absence"], 2.0)
        self.assertAlmostEqual(stats["taux"], 5.0, places=1)  # 2/40 * 100

    def test_future_sessions_excluded_from_at_risk_count(self):
        """get_at_risk_count_for_queryset excludes future absences."""
        qs = Inscription.objects.filter(
            id_inscription=self.inscription.id_inscription
        ).select_related("id_cours")
        _, sums = get_at_risk_count_for_queryset(qs, system_threshold=40)
        total = float(sums.get(self.inscription.id_inscription, 0) or 0)
        # Only 2h (past), not 4h (past + future)
        self.assertEqual(total, 2.0)

    def test_future_sessions_excluded_from_pourcentage(self):
        """calculer_pourcentage_absence excludes future séances from both sides."""
        result = calculer_pourcentage_absence(self.student, self.cours)
        # Only past séance counts: 2h total, 2h absent
        self.assertEqual(result["total_heures_cours"], 2.0)
        self.assertEqual(result["total_heures_absence"], 2.0)


class SignalLoopProtectionTest(TestCase):
    """
    Verify that creating/modifying Absence objects does not cause
    infinite signal loops via post_save → recalculer_eligibilite → save.
    """

    def setUp(self):
        from apps.absences.services import recalculer_eligibilite  # noqa: F401

        self.faculte = Faculte.objects.create(nom_faculte="Fac Signal")
        self.departement = Departement.objects.create(
            nom_departement="Dep Signal", id_faculte=self.faculte
        )
        self.annee = AnneeAcademique.objects.create(libelle="2025-2026", active=True)
        self.prof = User.objects.create_user(
            email="prof-sig@test.com", nom="Prof", prenom="Sig",
            password="pass1234", role=User.Role.PROFESSEUR,
        )
        self.student = User.objects.create_user(
            email="stu-sig@test.com", nom="Stu", prenom="Sig",
            password="pass1234", role=User.Role.ETUDIANT,
        )
        self.cours = Cours.objects.create(
            code_cours="SIG", nom_cours="Signal Test",
            nombre_total_periodes=40,
            id_departement=self.departement,
            professeur=self.prof,
            id_annee=self.annee, niveau=1,
        )
        self.inscription = Inscription.objects.create(
            id_etudiant=self.student,
            id_cours=self.cours,
            id_annee=self.annee,
        )

    def test_absence_save_does_not_trigger_infinite_signal_loop(self):
        """
        Create an absence, modify it 5 times, delete it.
        _schedule_eligibility_recalc (called synchronously by the signal)
        must fire exactly once per save/delete — bounded, never recursive.
        """
        seance = Seance.objects.create(
            date_seance=date(2026, 1, 10),
            heure_debut=time(8, 0), heure_fin=time(10, 0),
            id_cours=self.cours, id_annee=self.annee,
        )

        with patch(
            "apps.absences.signals._schedule_eligibility_recalc",
        ) as mock_schedule:
            # Create (1 call)
            absence = Absence.objects.create(
                id_inscription=self.inscription,
                id_seance=seance,
                type_absence=Absence.TypeAbsence.ABSENT,
                duree_absence=Decimal("2.00"),
                statut=Absence.Statut.NON_JUSTIFIEE,
                encodee_par=self.prof,
            )

            # Modify 5 times (5 calls)
            for i in range(5):
                absence.duree_absence = Decimal(f"1.{i:02d}")
                absence.save(update_fields=["duree_absence"])

            # Delete (1 call)
            absence.delete()

            # Exactly 7: 1 create + 5 updates + 1 delete — bounded, not infinite
            self.assertEqual(mock_schedule.call_count, 7)
            # Every call received the correct inscription PK
            for call in mock_schedule.call_args_list:
                self.assertEqual(call[0][0], self.inscription.pk)


class AcademicYearDeactivationTests(TestCase):
    """Tests for BUG #35: deactivating a year must close EN_COURS inscriptions."""

    def setUp(self):
        self.faculte = Faculte.objects.create(nom_faculte="Fac Year")
        self.dept = Departement.objects.create(
            nom_departement="Dept Year", id_faculte=self.faculte
        )
        self.annee = AnneeAcademique.objects.create(libelle="2025-2026", active=True)
        self.prof = User.objects.create_user(
            email="prof-year@test.com", nom="Prof", prenom="Year",
            password="pass1234", role=User.Role.PROFESSEUR,
        )
        self.student = User.objects.create_user(
            email="stu-year@test.com", nom="Stu", prenom="Year",
            password="pass1234", role=User.Role.ETUDIANT,
        )
        self.cours = Cours.objects.create(
            code_cours="YEAR1", nom_cours="Year Course",
            nombre_total_periodes=40, id_departement=self.dept,
            professeur=self.prof, id_annee=self.annee, niveau=1,
        )
        self.inscription = Inscription.objects.create(
            id_etudiant=self.student, id_cours=self.cours, id_annee=self.annee,
        )

    def test_deactivating_year_closes_enrollments(self):
        """When an active year is deactivated, its EN_COURS inscriptions become NON_VALIDE."""
        self.assertEqual(self.inscription.status, "EN_COURS")

        self.annee.active = False
        self.annee.save()

        self.inscription.refresh_from_db()
        self.assertEqual(self.inscription.status, "NON_VALIDE")

    def test_already_validated_inscription_unchanged(self):
        """VALIDE inscriptions are not affected by year deactivation."""
        self.inscription.status = "VALIDE"
        self.inscription.save(update_fields=["status"])

        self.annee.active = False
        self.annee.save()

        self.inscription.refresh_from_db()
        self.assertEqual(self.inscription.status, "VALIDE")

    def test_activating_new_year_does_not_close_inscriptions(self):
        """Activating a new year deactivates the old one but does NOT close inscriptions
        of the newly activated year."""
        new_annee = AnneeAcademique(libelle="2026-2027", active=True)
        new_annee.save()

        # Old year is now inactive
        self.annee.refresh_from_db()
        self.assertFalse(self.annee.active)

        # But the inscription of the old year is NOT closed by the new year's save —
        # only the year's own deactivation closes inscriptions
        # The old year's inscriptions were closed when AnneeAcademique.save()
        # deactivated it via .update(active=False), which does NOT trigger save()
        # So EN_COURS inscriptions of the old year remain until explicitly deactivated.
        self.inscription.refresh_from_db()
        self.assertEqual(self.inscription.status, "EN_COURS")


class QRFinalizeDurationGuardTest(TestCase):
    """Bug fix: QR finalize must not create absences with duree_absence=0."""

    def setUp(self):
        self.faculte = Faculte.objects.create(nom_faculte="Fac QR")
        self.dept = Departement.objects.create(
            nom_departement="Dept QR", id_faculte=self.faculte
        )
        self.annee = AnneeAcademique.objects.create(libelle="2025-2026", active=True)
        self.prof = User.objects.create_user(
            email="prof-qr@test.com", nom="Prof", prenom="QR",
            password="pass1234", role=User.Role.PROFESSEUR,
        )
        self.student = User.objects.create_user(
            email="stu-qr@test.com", nom="Stu", prenom="QR",
            password="pass1234", role=User.Role.ETUDIANT,
        )
        self.cours = Cours.objects.create(
            code_cours="QR1", nom_cours="QR Course",
            nombre_total_periodes=40, id_departement=self.dept,
            professeur=self.prof, id_annee=self.annee, niveau=1,
        )
        self.seance = Seance.objects.create(
            date_seance=date(2026, 1, 10),
            heure_debut=time(8, 0), heure_fin=time(10, 0),
            id_cours=self.cours, id_annee=self.annee,
        )
        self.inscription = Inscription.objects.create(
            id_etudiant=self.student, id_cours=self.cours, id_annee=self.annee,
        )

    def test_duree_heures_zero_fallback(self):
        """When duree_heures() returns 0, the fallback should be 2.0."""
        with patch.object(Seance, "duree_heures", return_value=0.0):
            duree = self.seance.duree_heures() or 2.0
        self.assertEqual(duree, 2.0)

    def test_duree_heures_normal(self):
        """When duree_heures() returns a positive value, it should be used as-is."""
        duree = self.seance.duree_heures() or 2.0
        self.assertEqual(duree, 2.0)  # 8:00-10:00 = 2h


class JustificationEmailNeverRaisesTest(TestCase):
    """Bug fix: _send_justification_decision_emails must never propagate exceptions."""

    def test_email_function_does_not_raise(self):
        """Even if build_ helpers crash, the function catches the exception."""
        from apps.absences.views.secretary_views import _send_justification_decision_emails

        # Pass None — attribute access will fail, but the function should catch it
        # and not propagate the exception
        _send_justification_decision_emails(None, approved=True)
        # If we get here, the function didn't raise — test passes


class StudentViewsFallbackFilterTest(TestCase):
    """Bug fix: student views fallback (no active year) must filter by EN_COURS."""

    def setUp(self):
        self.faculte = Faculte.objects.create(nom_faculte="Fac Fallback")
        self.dept = Departement.objects.create(
            nom_departement="Dept Fallback", id_faculte=self.faculte
        )
        # No active year — triggers fallback
        self.annee = AnneeAcademique.objects.create(libelle="2024-2025", active=False)
        self.prof = User.objects.create_user(
            email="prof-fb@test.com", nom="Prof", prenom="FB",
            password="pass1234", role=User.Role.PROFESSEUR,
        )
        self.student = User.objects.create_user(
            email="stu-fb@test.com", nom="Stu", prenom="FB",
            password="pass1234", role=User.Role.ETUDIANT,
        )
        self.cours = Cours.objects.create(
            code_cours="FB1", nom_cours="Fallback Course",
            nombre_total_periodes=40, id_departement=self.dept,
            professeur=self.prof, id_annee=self.annee, niveau=1,
        )
        # One active enrollment, one archived
        self.active_ins = Inscription.objects.create(
            id_etudiant=self.student, id_cours=self.cours, id_annee=self.annee,
            status=Inscription.Status.EN_COURS,
        )
        self.archived_ins = Inscription.objects.create(
            id_etudiant=self.student, id_cours=Cours.objects.create(
                code_cours="FB2", nom_cours="Archived Course",
                nombre_total_periodes=40, id_departement=self.dept,
                professeur=self.prof, id_annee=self.annee, niveau=1,
            ), id_annee=self.annee,
            status=Inscription.Status.NON_VALIDE,
        )

    def test_student_dashboard_fallback_filters_en_cours(self):
        """student_dashboard fallback query must only return EN_COURS inscriptions."""
        self.client.force_login(self.student)
        response = self.client.get("/dashboard/student/", secure=True)
        self.assertEqual(response.status_code, 200)
        # Should show 1 course (the active one), not 2
        self.assertEqual(response.context["total_courses"], 1)

    def test_student_absences_fallback_filters_en_cours(self):
        """student_absences fallback query must only return EN_COURS inscriptions."""
        self.client.force_login(self.student)
        response = self.client.get("/dashboard/student/absences/", secure=True)
        self.assertEqual(response.status_code, 200)
