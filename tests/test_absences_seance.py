"""
Tests — séances verrouillées et sécurité d'accès aux absences.
  - LockedSeanceTests   : TOCTOU sur séance validée
  - AbsenceSecurityTests: rejet d'id_inscription invalide
"""
from datetime import date, time

from django.urls import reverse
from django.utils import timezone

from apps.absences.models import Absence
from apps.academic_sessions.models import Seance

from .test_absences import BaseAbsenceTestCase


class LockedSeanceTests(BaseAbsenceTestCase):
    """Tests that a validated (locked) seance blocks absence creation."""

    def test_absence_creation_blocked_for_locked_seance(self):
        """
        Simulates TOCTOU: seance is unlocked when the form loads,
        but gets validated before the POST is processed. The
        select_for_update + re-check must reject the submission.
        """
        seance = Seance.objects.create(
            date_seance=date(2026, 4, 10),
            heure_debut=time(8, 0),
            heure_fin=time(10, 0),
            id_cours=self.course1,
            id_annee=self.annee,
            validated=False,
        )

        self.client.force_login(self.prof)
        url = reverse("absences:mark_absence", args=[self.course1.id_cours])

        get_resp = self.client.get(url, {"date": "2026-04-10"}, secure=True)
        self.assertEqual(get_resp.status_code, 200)

        seance.validated = True
        seance.validated_by = self.prof
        seance.date_validated = timezone.now()
        seance.save(update_fields=["validated", "validated_by", "date_validated"])

        data = {
            "date_seance": "2026-04-10",
            "heure_debut": "08:00",
            "heure_fin": "10:00",
            f"status_{self.inscription1.id_inscription}": "ABSENT",
            f"type_{self.inscription1.id_inscription}": "ABSENT",
        }
        response = self.client.post(url, data, secure=True)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            Absence.objects.filter(id_seance=seance).count(), 0
        )

    def test_absence_creation_allowed_for_unlocked_seance(self):
        """Normal case: unlocked seance allows absence creation."""
        self.client.force_login(self.prof)
        url = reverse("absences:mark_absence", args=[self.course1.id_cours])

        data = {
            "date_seance": "2026-04-11",
            "heure_debut": "08:00",
            "heure_fin": "10:00",
            f"status_{self.inscription1.id_inscription}": "ABSENT",
            f"type_{self.inscription1.id_inscription}": "ABSENT",
        }
        response = self.client.post(url, data, secure=True)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(Absence.objects.count(), 1)


class AbsenceSecurityTests(BaseAbsenceTestCase):
    def test_mark_absence_rejects_invalid_inscription_id(self):
        self.client.force_login(self.prof)

        url = reverse("absences:mark_absence", args=[self.course1.id_cours])
        data = {
            "date_seance": "2026-01-01",
            "heure_debut": "08:00",
            "heure_fin": "10:00",
            f"status_{self.inscription1.id_inscription}": "ABSENT",
            f"status_{self.inscription2.id_inscription}": "ABSENT",
        }
        response = self.client.post(url, data, secure=True)

        self.assertEqual(response.status_code, 403)
        self.assertEqual(Absence.objects.count(), 0)
