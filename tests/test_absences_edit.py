"""
Tests — délai de soumission et édition directe d'une absence.
  - JustificationDeadlineTests : upload refusé après 3 jours
  - EditAbsenceTests           : édition bloquée si statut JUSTIFIEE (TOCTOU)
"""
from datetime import date, time, timedelta

from django.urls import reverse
from django.utils import timezone

from apps.absences.models import Absence, Justification
from apps.academic_sessions.models import Seance

from .test_absences import BaseAbsenceTestCase


class JustificationDeadlineTests(BaseAbsenceTestCase):
    """Tests that justification upload is rejected after the deadline."""

    def _create_old_absence(self, days_ago):
        """Create an absence whose seance was `days_ago` days in the past."""
        seance_date = timezone.localdate() - timedelta(days=days_ago)
        seance = Seance.objects.create(
            date_seance=seance_date,
            heure_debut=time(8, 0),
            heure_fin=time(10, 0),
            id_cours=self.course1,
            id_annee=self.annee,
        )
        return Absence.objects.create(
            id_inscription=self.inscription1,
            id_seance=seance,
            type_absence="ABSENT",
            duree_absence=2.0,
            statut="NON_JUSTIFIEE",
            encodee_par=self.secretary,
        )

    def test_justification_upload_after_deadline_rejected(self):
        """Upload is rejected when the 3-day deadline has passed."""
        absence = self._create_old_absence(days_ago=10)
        self.client.force_login(self.student1)

        url = reverse("absences:upload", args=[absence.id_absence])
        response = self.client.get(url, secure=True)

        self.assertEqual(response.status_code, 302)
        self.assertFalse(Justification.objects.filter(id_absence=absence).exists())

    def test_justification_upload_within_deadline_allowed(self):
        """Upload page is accessible when within the 3-day deadline."""
        absence = self._create_old_absence(days_ago=1)
        self.client.force_login(self.student1)

        url = reverse("absences:upload", args=[absence.id_absence])
        response = self.client.get(url, secure=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn("deadline", response.context)
        self.assertIn("days_remaining", response.context)
        self.assertGreaterEqual(response.context["days_remaining"], 0)


class EditAbsenceTests(BaseAbsenceTestCase):
    """Tests for the edit_absence view (secretary editing an absence)."""

    def _create_absence(self, statut="NON_JUSTIFIEE"):
        seance = Seance.objects.create(
            date_seance=date(2026, 2, 1),
            heure_debut=time(8, 0),
            heure_fin=time(10, 0),
            id_cours=self.course1,
            id_annee=self.annee,
        )
        return Absence.objects.create(
            id_inscription=self.inscription1,
            id_seance=seance,
            type_absence="ABSENT",
            duree_absence=2.0,
            statut=statut,
            encodee_par=self.secretary,
        )

    def test_edit_justified_absence_rejected_get(self):
        """GET on an already-justified absence redirects with error."""
        absence = self._create_absence(statut="JUSTIFIEE")
        self.client.force_login(self.secretary)

        url = reverse("absences:edit_absence", args=[absence.pk])
        response = self.client.get(url, secure=True)

        self.assertEqual(response.status_code, 302)
        absence.refresh_from_db()
        self.assertEqual(absence.statut, "JUSTIFIEE")

    def test_edit_justified_absence_rejected_post(self):
        """POST on an already-justified absence redirects with error."""
        absence = self._create_absence(statut="JUSTIFIEE")
        self.client.force_login(self.secretary)

        url = reverse("absences:edit_absence", args=[absence.pk])
        response = self.client.post(url, {
            "type_absence": "PARTIEL",
            "statut": "NON_JUSTIFIEE",
            "duree_absence": "1.0",
            "reason": "correction",
        }, secure=True)

        self.assertEqual(response.status_code, 302)
        absence.refresh_from_db()
        self.assertEqual(absence.statut, "JUSTIFIEE")
        self.assertEqual(absence.type_absence, "ABSENT")
        self.assertEqual(float(absence.duree_absence), 2.0)

    def test_edit_justified_absence_rejected_race_condition(self):
        """
        Simulates TOCTOU: absence is NON_JUSTIFIEE when the form loads,
        but becomes JUSTIFIEE before the POST is processed. The
        select_for_update + re-check must reject the edit.
        """
        absence = self._create_absence(statut="NON_JUSTIFIEE")
        self.client.force_login(self.secretary)

        url = reverse("absences:edit_absence", args=[absence.pk])

        get_response = self.client.get(url, secure=True)
        self.assertEqual(get_response.status_code, 200)

        absence.statut = "JUSTIFIEE"
        absence.save(update_fields=["statut"])

        response = self.client.post(url, {
            "type_absence": "PARTIEL",
            "statut": "NON_JUSTIFIEE",
            "duree_absence": "1.0",
            "reason": "correction tardive",
        }, secure=True)

        self.assertEqual(response.status_code, 302)
        absence.refresh_from_db()
        self.assertEqual(absence.statut, "JUSTIFIEE")
        self.assertEqual(absence.type_absence, "ABSENT")
