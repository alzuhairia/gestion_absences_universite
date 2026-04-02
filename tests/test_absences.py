import shutil
import tempfile
from datetime import date, time, timedelta
from unittest.mock import patch

from django.utils import timezone

from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError
from django.test import TestCase
from django.test.utils import override_settings
from django.urls import reverse

from apps.absences.models import Absence, Justification
from apps.absences.services import get_absences_queryset
from apps.academic_sessions.models import AnneeAcademique, Seance
from apps.academics.models import Cours, Departement, Faculte
from apps.accounts.models import User
from apps.enrollments.models import Inscription


class BaseAbsenceTestCase(TestCase):
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


class JustificationStateTests(BaseAbsenceTestCase):
    def _create_absence_with_justification(self):
        seance = Seance.objects.create(
            date_seance=date(2026, 1, 1),
            heure_debut=time(8, 0),
            heure_fin=time(10, 0),
            id_cours=self.course1,
            id_annee=self.annee,
        )
        absence = Absence.objects.create(
            id_inscription=self.inscription1,
            id_seance=seance,
            type_absence="ABSENT",
            duree_absence=2.0,
            statut="EN_ATTENTE",
            encodee_par=self.secretary,
        )
        justification = Justification.objects.create(
            id_absence=absence,
            state="EN_ATTENTE",
        )
        return absence, justification

    def test_valider_justificatif_sets_state(self):
        absence, justification = self._create_absence_with_justification()

        self.client.force_login(self.secretary)
        url = reverse("absences:process_justification", args=[justification.pk])
        response = self.client.post(url, {"action": "approve"}, secure=True)

        self.assertEqual(response.status_code, 302)
        absence.refresh_from_db()
        justification.refresh_from_db()

        self.assertEqual(absence.statut, "JUSTIFIEE")
        self.assertEqual(justification.state, "ACCEPTEE")
        self.assertEqual(justification.validee_par, self.secretary)
        self.assertIsNotNone(justification.date_validation)

    def test_valider_justificatif_recalculates_eligibility(self):
        """Approving a justification triggers eligibility recalculation via signal."""
        absence, justification = self._create_absence_with_justification()
        # Block the student first
        self.inscription1.eligible_examen = False
        self.inscription1.save(update_fields=["eligible_examen"])

        self.client.force_login(self.secretary)
        url = reverse("absences:process_justification", args=[justification.pk])
        self.client.post(url, {"action": "approve"}, secure=True)

        absence.refresh_from_db()
        self.assertEqual(absence.statut, "JUSTIFIEE")
        # Eligibility should be recalculated (signal fires via on_commit)
        self.inscription1.refresh_from_db()
        self.assertTrue(self.inscription1.eligible_examen)

    def test_refuser_justificatif_sets_state(self):
        absence, justification = self._create_absence_with_justification()

        self.client.force_login(self.secretary)
        url = reverse("absences:process_justification", args=[justification.pk])
        response = self.client.post(url, {
            "action": "reject",
            "comment": "Document illisible",
        }, secure=True)

        self.assertEqual(response.status_code, 302)
        absence.refresh_from_db()
        justification.refresh_from_db()

        self.assertEqual(absence.statut, "NON_JUSTIFIEE")
        self.assertEqual(justification.state, "REFUSEE")
        self.assertEqual(justification.validee_par, self.secretary)
        self.assertIsNotNone(justification.date_validation)
        self.assertEqual(justification.commentaire_gestion, "Document illisible")

    def test_reject_without_comment_is_refused(self):
        """Rejecting a justification without a motif is refused."""
        absence, justification = self._create_absence_with_justification()

        self.client.force_login(self.secretary)
        url = reverse("absences:process_justification", args=[justification.pk])
        response = self.client.post(url, {"action": "reject"}, secure=True)

        self.assertEqual(response.status_code, 302)
        # Justification should remain EN_ATTENTE (not processed)
        justification.refresh_from_db()
        self.assertEqual(justification.state, "EN_ATTENTE")

    def test_reprocessing_already_handled_justification(self):
        """Processing an already-handled justification shows a warning."""
        absence, justification = self._create_absence_with_justification()
        justification.state = "ACCEPTEE"
        justification.save(update_fields=["state"])

        self.client.force_login(self.secretary)
        url = reverse("absences:process_justification", args=[justification.pk])
        response = self.client.post(url, {"action": "approve"}, secure=True)

        self.assertEqual(response.status_code, 302)
        # State should remain unchanged
        justification.refresh_from_db()
        self.assertEqual(justification.state, "ACCEPTEE")


class JustificationDownloadTests(BaseAbsenceTestCase):
    def setUp(self):
        super().setUp()
        self._temp_media_root = tempfile.mkdtemp()
        self._override_settings = override_settings(MEDIA_ROOT=self._temp_media_root)
        self._override_settings.enable()
        self.addCleanup(self._cleanup_media_root)

    def _cleanup_media_root(self):
        self._override_settings.disable()
        shutil.rmtree(self._temp_media_root, ignore_errors=True)

    def _create_absence(self):
        seance = Seance.objects.create(
            date_seance=date(2026, 1, 1),
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
            statut="EN_ATTENTE",
            encodee_par=self.secretary,
        )

    def test_secretary_can_download_uploaded_justification(self):
        absence = self._create_absence()
        pdf_file = SimpleUploadedFile(
            "justificatif_test.pdf",
            b"%PDF-1.4 sample",
            content_type="application/pdf",
        )
        justification = Justification.objects.create(
            id_absence=absence,
            state="EN_ATTENTE",
            document=pdf_file,
        )

        self.client.force_login(self.secretary)
        url = reverse(
            "absences:download_justification", args=[justification.id_justification]
        )
        response = self.client.get(url, secure=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn("attachment;", response["Content-Disposition"])
        self.assertIn(b"%PDF-1.4", b"".join(response.streaming_content))

    def test_download_returns_404_when_file_is_missing(self):
        absence = self._create_absence()
        justification = Justification.objects.create(
            id_absence=absence,
            state="EN_ATTENTE",
        )
        justification.document.name = "justifications/introuvable.pdf"
        justification.save(update_fields=["document"])

        self.client.force_login(self.secretary)
        url = reverse(
            "absences:download_justification", args=[justification.id_justification]
        )
        response = self.client.get(url, secure=True)

        self.assertEqual(response.status_code, 404)


class AbsenceQueryTests(BaseAbsenceTestCase):
    def test_absences_queryset_prefetch(self):
        # Create multiple absences with justifications to detect N+1
        for day in range(1, 4):
            seance = Seance.objects.create(
                date_seance=date(2026, 1, day),
                heure_debut=time(8, 0),
                heure_fin=time(10, 0),
                id_cours=self.course1,
                id_annee=self.annee,
            )
            absence = Absence.objects.create(
                id_inscription=self.inscription1,
                id_seance=seance,
                type_absence="ABSENT",
                duree_absence=2.0,
                statut="EN_ATTENTE",
                encodee_par=self.secretary,
            )
            Justification.objects.create(
                id_absence=absence,
                state="EN_ATTENTE",
            )

        qs = get_absences_queryset(self.inscription1)
        # select_related("justification") does a single JOIN — 1 query total,
        # accessing absence.justification triggers no extra query.
        with self.assertNumQueries(1):
            absences = list(qs)
            for absence in absences:
                _ = absence.justification


class UploadValidationTests(BaseAbsenceTestCase):
    def setUp(self):
        super().setUp()
        self._temp_media_root = tempfile.mkdtemp()
        self._override_settings = override_settings(MEDIA_ROOT=self._temp_media_root)
        self._override_settings.enable()
        self.addCleanup(self._cleanup_media_root)
        self.client.force_login(self.student1)

    def _cleanup_media_root(self):
        self._override_settings.disable()
        shutil.rmtree(self._temp_media_root, ignore_errors=True)

    def _create_absence(self):
        seance = Seance.objects.create(
            date_seance=date(2026, 1, 2),
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

    def test_upload_rejects_mime_spoofed_file(self):
        absence = self._create_absence()
        fake_pdf = SimpleUploadedFile(
            "proof.pdf",
            b"\x89PNG\r\n\x1a\nspoofed-content",
            content_type="application/pdf",
        )

        response = self.client.post(
            reverse("absences:upload", args=[absence.id_absence]),
            data={"comment": "test", "document": fake_pdf},
            secure=True,
        )

        self.assertEqual(response.status_code, 302)
        self.assertFalse(Justification.objects.filter(id_absence=absence).exists())

    def test_upload_rejects_invalid_extension(self):
        absence = self._create_absence()
        bad_ext = SimpleUploadedFile(
            "proof.txt",
            b"%PDF-1.4 real-content",
            content_type="application/pdf",
        )

        response = self.client.post(
            reverse("absences:upload", args=[absence.id_absence]),
            data={"comment": "test", "document": bad_ext},
            secure=True,
        )

        self.assertEqual(response.status_code, 302)
        self.assertFalse(Justification.objects.filter(id_absence=absence).exists())

    def test_upload_rejects_forged_binary_file(self):
        absence = self._create_absence()
        forged_jpeg = SimpleUploadedFile(
            "proof.jpg",
            b"%PDF-1.4 forged-jpeg",
            content_type="image/jpeg",
        )

        response = self.client.post(
            reverse("absences:upload", args=[absence.id_absence]),
            data={"comment": "test", "document": forged_jpeg},
            secure=True,
        )

        self.assertEqual(response.status_code, 302)
        self.assertFalse(Justification.objects.filter(id_absence=absence).exists())

    def test_upload_rejects_file_over_size_limit(self):
        absence = self._create_absence()
        oversized = SimpleUploadedFile(
            "proof.pdf",
            b"%PDF-1.4\n" + (b"a" * (5 * 1024 * 1024)),
            content_type="application/pdf",
        )

        response = self.client.post(
            reverse("absences:upload", args=[absence.id_absence]),
            data={"comment": "test", "document": oversized},
            secure=True,
        )

        self.assertEqual(response.status_code, 302)
        self.assertFalse(Justification.objects.filter(id_absence=absence).exists())


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
        absence = self._create_old_absence(days_ago=10)  # well past the 3-day deadline
        self.client.force_login(self.student1)

        url = reverse("absences:upload", args=[absence.id_absence])
        response = self.client.get(url, secure=True)

        # Should redirect away with an error message
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Justification.objects.filter(id_absence=absence).exists())

    def test_justification_upload_within_deadline_allowed(self):
        """Upload page is accessible when within the 3-day deadline."""
        absence = self._create_old_absence(days_ago=1)  # within deadline
        self.client.force_login(self.student1)

        url = reverse("absences:upload", args=[absence.id_absence])
        response = self.client.get(url, secure=True)

        # Should render the upload form (200), not redirect
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
        # Absence must remain untouched
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

        # Secretary loads the form (GET succeeds because status is NON_JUSTIFIEE)
        get_response = self.client.get(url, secure=True)
        self.assertEqual(get_response.status_code, 200)

        # Meanwhile, the justification is approved (status changes to JUSTIFIEE)
        absence.statut = "JUSTIFIEE"
        absence.save(update_fields=["statut"])

        # Secretary submits the form (POST must be rejected)
        response = self.client.post(url, {
            "type_absence": "PARTIEL",
            "statut": "NON_JUSTIFIEE",
            "duree_absence": "1.0",
            "reason": "correction tardive",
        }, secure=True)

        self.assertEqual(response.status_code, 302)
        absence.refresh_from_db()
        # Absence must still be JUSTIFIEE — edit rejected
        self.assertEqual(absence.statut, "JUSTIFIEE")
        self.assertEqual(absence.type_absence, "ABSENT")


class ConcurrentAbsenceCreationTests(BaseAbsenceTestCase):
    """Tests race condition protection on simultaneous absence creation."""

    def test_concurrent_absence_creation(self):
        """
        Simulates a race condition: two requests try to create the same absence
        simultaneously. The unique_together constraint + IntegrityError handling
        ensures only one absence is created and the duplicate is gracefully ignored.
        """
        seance = Seance.objects.create(
            date_seance=date(2026, 3, 15),
            heure_debut=time(8, 0),
            heure_fin=time(10, 0),
            id_cours=self.course1,
            id_annee=self.annee,
        )
        self.client.force_login(self.prof)
        url = reverse("absences:mark_absence", args=[self.course1.id_cours])
        data = {
            "date_seance": "2026-03-15",
            "heure_debut": "08:00",
            "heure_fin": "10:00",
            f"status_{self.inscription1.id_inscription}": "ABSENT",
            f"type_{self.inscription1.id_inscription}": "ABSENT",
        }

        # First call — normal, creates the absence
        response1 = self.client.post(url, data, secure=True)
        self.assertEqual(response1.status_code, 302)
        self.assertEqual(Absence.objects.filter(id_seance=seance).count(), 1)

        # Second call — simulates concurrent request by patching update_or_create
        # to raise IntegrityError (as if another transaction already inserted the row)
        def raise_on_create(self_qs, **kwargs):
            raise IntegrityError("duplicate key violates unique constraint")

        with patch.object(
            type(Absence.objects), "update_or_create", raise_on_create
        ):
            response2 = self.client.post(url, data, secure=True)

        # Should redirect (not crash), and still only one absence in DB
        self.assertEqual(response2.status_code, 302)
        self.assertEqual(Absence.objects.filter(id_seance=seance).count(), 1)

    def test_unique_constraint_prevents_duplicate_absence(self):
        """
        Verifies the unique_together constraint on (id_inscription, id_seance)
        prevents duplicate absences. The model's full_clean() catches it as
        ValidationError; the DB constraint catches it as IntegrityError.
        """
        from django.core.exceptions import ValidationError

        seance = Seance.objects.create(
            date_seance=date(2026, 3, 16),
            heure_debut=time(8, 0),
            heure_fin=time(10, 0),
            id_cours=self.course1,
            id_annee=self.annee,
        )

        Absence.objects.create(
            id_inscription=self.inscription1,
            id_seance=seance,
            type_absence="ABSENT",
            duree_absence=2.0,
            statut="NON_JUSTIFIEE",
            encodee_par=self.prof,
        )

        # Model-level validation catches the duplicate via full_clean()
        with self.assertRaises(ValidationError):
            Absence.objects.create(
                id_inscription=self.inscription1,
                id_seance=seance,
                type_absence="ABSENT",
                duree_absence=2.0,
                statut="NON_JUSTIFIEE",
                encodee_par=self.prof,
            )

        self.assertEqual(Absence.objects.filter(id_seance=seance).count(), 1)

    def test_select_for_update_on_seance(self):
        """
        Verifies that the seance is fetched with select_for_update() inside
        the transaction, preventing concurrent modification of the same session.
        """
        self.client.force_login(self.prof)
        url = reverse("absences:mark_absence", args=[self.course1.id_cours])
        data = {
            "date_seance": "2026-03-17",
            "heure_debut": "08:00",
            "heure_fin": "10:00",
            f"status_{self.inscription1.id_inscription}": "ABSENT",
            f"type_{self.inscription1.id_inscription}": "ABSENT",
        }

        with patch.object(
            Seance.objects, "select_for_update", wraps=Seance.objects.select_for_update
        ) as mock_sfu:
            self.client.post(url, data, secure=True)
            mock_sfu.assert_called_once()
