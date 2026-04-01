from datetime import date, time
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse

from apps.absences.models import Absence
from apps.absences.services import recalculer_eligibilite
from apps.academic_sessions.models import AnneeAcademique, Seance
from apps.academics.models import Cours, Departement, Faculte
from apps.accounts.models import User
from apps.enrollments.models import Inscription


class ExemptionBaseTestCase(TestCase):
    """Shared fixtures for exemption tests."""

    def setUp(self):
        self.faculte = Faculte.objects.create(nom_faculte="Faculte Test")
        self.departement = Departement.objects.create(
            nom_departement="Departement Test",
            id_faculte=self.faculte,
        )
        self.annee = AnneeAcademique.objects.create(libelle="2024-2025", active=True)

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
        self.student = User.objects.create_user(
            email="stu@example.com",
            nom="Student",
            prenom="One",
            password="pass1234",
            role=User.Role.ETUDIANT,
        )

        # Course with 20h total → seuil default 40% → blocked at 8h+
        self.course = Cours.objects.create(
            code_cours="C1",
            nom_cours="Course 1",
            nombre_total_periodes=20,
            id_departement=self.departement,
            professeur=self.prof,
            id_annee=self.annee,
            niveau=1,
        )

        self.inscription = Inscription.objects.create(
            id_etudiant=self.student,
            id_cours=self.course,
            id_annee=self.annee,
        )

    def _create_absences(self, total_hours):
        """Create absences totalling `total_hours` (2h sessions)."""
        hours_created = 0
        day = 1
        while hours_created < total_hours:
            seance = Seance.objects.create(
                date_seance=date(2026, 1, day),
                heure_debut=time(8, 0),
                heure_fin=time(10, 0),
                id_cours=self.course,
                id_annee=self.annee,
            )
            Absence.objects.create(
                id_inscription=self.inscription,
                id_seance=seance,
                type_absence="ABSENT",
                duree_absence=2.0,
                statut="NON_JUSTIFIEE",
                encodee_par=self.prof,
            )
            hours_created += 2
            day += 1


class ExemptionEligibilityTests(ExemptionBaseTestCase):
    """Tests that toggling exemption immediately recalculates eligibility."""

    def test_exemption_triggers_eligibility_recalc(self):
        """
        Student has 10h absences on 20h course (50%) → blocked (seuil 40%).
        Granting exemption with margin=15 → seuil_effectif=55% → 50% < 55% → unblocked.
        """
        self._create_absences(10)  # 50% rate

        # Recalculate to set blocked state
        recalculer_eligibilite(self.inscription)
        self.inscription.refresh_from_db()
        self.assertFalse(self.inscription.eligible_examen)

        # Grant exemption via the view
        self.client.force_login(self.secretary)
        url = reverse("enrollments:toggle_exemption", args=[self.inscription.pk])
        response = self.client.post(url, {
            "action": "grant",
            "motif": "Raison médicale documentée",
            "exemption_margin": "15",
        }, secure=True)

        self.assertEqual(response.status_code, 302)
        self.inscription.refresh_from_db()
        # Exemption granted: seuil_effectif = 40+15 = 55%, taux = 50% → eligible
        self.assertTrue(self.inscription.eligible_examen)
        self.assertTrue(self.inscription.exemption_40)

    def test_revoke_exemption_recalculates_eligibility(self):
        """
        Student with exemption (eligible despite 50% rate).
        Revoking exemption → seuil back to 40% → 50% >= 40% → blocked.
        """
        self._create_absences(10)  # 50% rate

        # Set up exempted state
        self.inscription.exemption_40 = True
        self.inscription.motif_exemption = "Raison médicale"
        self.inscription.exemption_margin = 15
        self.inscription.save()
        recalculer_eligibilite(self.inscription)
        self.inscription.refresh_from_db()
        self.assertTrue(self.inscription.eligible_examen)

        # Revoke exemption via the view
        self.client.force_login(self.secretary)
        url = reverse("enrollments:toggle_exemption", args=[self.inscription.pk])
        response = self.client.post(url, {"action": "revoke"}, secure=True)

        self.assertEqual(response.status_code, 302)
        self.inscription.refresh_from_db()
        # Revoked: seuil_effectif = 40%, taux = 50% → blocked
        self.assertFalse(self.inscription.eligible_examen)
        self.assertFalse(self.inscription.exemption_40)

    def test_grant_exemption_sends_email_notification(self):
        """Granting exemption sends an email notification to the student."""
        self._create_absences(10)
        recalculer_eligibilite(self.inscription)

        self.client.force_login(self.secretary)
        url = reverse("enrollments:toggle_exemption", args=[self.inscription.pk])

        with patch(
            "apps.enrollments.views_rules.send_with_dedup"
        ) as mock_send:
            # captureOnCommitCallbacks forces on_commit callbacks to execute
            with self.captureOnCommitCallbacks(execute=True):
                self.client.post(url, {
                    "action": "grant",
                    "motif": "Raison médicale documentée",
                    "exemption_margin": "15",
                }, secure=True)

            mock_send.assert_called_once()
            call_kwargs = mock_send.call_args
            # Verify recipient is the student
            self.assertEqual(call_kwargs[0][0], self.student)
            # Verify event_type
            self.assertEqual(call_kwargs[1]["event_type"], "exemption_granted")

    def test_grant_requires_motif(self):
        """Granting without motif is rejected."""
        self.client.force_login(self.secretary)
        url = reverse("enrollments:toggle_exemption", args=[self.inscription.pk])
        response = self.client.post(url, {
            "action": "grant",
            "motif": "",
        }, secure=True)

        self.assertEqual(response.status_code, 302)
        self.inscription.refresh_from_db()
        self.assertFalse(self.inscription.exemption_40)

    def test_invalid_action_rejected(self):
        """An invalid action value is rejected with error message."""
        self.client.force_login(self.secretary)
        url = reverse("enrollments:toggle_exemption", args=[self.inscription.pk])
        response = self.client.post(url, {"action": "invalid"}, secure=True)

        self.assertEqual(response.status_code, 302)
        self.inscription.refresh_from_db()
        self.assertFalse(self.inscription.exemption_40)
