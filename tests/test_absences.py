import shutil
import tempfile
from datetime import date, time, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.utils import timezone

from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError
from django.db.models.deletion import ProtectedError
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


class LockedSeanceTests(BaseAbsenceTestCase):
    """Tests that a validated (locked) seance blocks absence creation."""

    def test_absence_creation_blocked_for_locked_seance(self):
        """
        Simulates TOCTOU: seance is unlocked when the form loads,
        but gets validated before the POST is processed. The
        select_for_update + re-check must reject the submission.
        """
        # Create an unlocked seance
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

        # Professor loads the form — seance is not validated
        get_resp = self.client.get(url, {"date": "2026-04-10"}, secure=True)
        self.assertEqual(get_resp.status_code, 200)

        # Meanwhile, the seance is validated (e.g. by another tab)
        seance.validated = True
        seance.validated_by = self.prof
        seance.date_validated = timezone.now()
        seance.save(update_fields=["validated", "validated_by", "date_validated"])

        # Professor submits the form — must be rejected
        data = {
            "date_seance": "2026-04-10",
            "heure_debut": "08:00",
            "heure_fin": "10:00",
            f"status_{self.inscription1.id_inscription}": "ABSENT",
            f"type_{self.inscription1.id_inscription}": "ABSENT",
        }
        response = self.client.post(url, data, secure=True)

        self.assertEqual(response.status_code, 302)
        # No absence should have been created
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

    def test_double_justification_processing_prevented(self):
        """
        First secretary approves, second secretary tries to approve the same
        justification — the second attempt must be rejected without altering
        the first decision or its metadata.
        """
        absence, justification = self._create_absence_with_justification()

        secretary2 = User.objects.create_user(
            email="sec2@example.com",
            nom="Sec2",
            prenom="Test",
            password="pass1234",
            role=User.Role.SECRETAIRE,
        )

        # First secretary approves
        self.client.force_login(self.secretary)
        url = reverse("absences:process_justification", args=[justification.pk])
        resp1 = self.client.post(url, {"action": "approve", "comment": "OK"}, secure=True)
        self.assertEqual(resp1.status_code, 302)

        justification.refresh_from_db()
        absence.refresh_from_db()
        self.assertEqual(justification.state, "ACCEPTEE")
        self.assertEqual(justification.validee_par, self.secretary)
        self.assertEqual(absence.statut, "JUSTIFIEE")

        # Second secretary tries to approve the same justification
        self.client.force_login(secretary2)
        resp2 = self.client.post(url, {"action": "approve", "comment": "Moi aussi"}, secure=True)
        self.assertEqual(resp2.status_code, 302)

        # State and metadata must remain from the first processing
        justification.refresh_from_db()
        absence.refresh_from_db()
        self.assertEqual(justification.state, "ACCEPTEE")
        self.assertEqual(justification.validee_par, self.secretary)  # NOT secretary2
        self.assertEqual(justification.commentaire_gestion, "OK")  # NOT "Moi aussi"
        self.assertEqual(absence.statut, "JUSTIFIEE")


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


class UploadSizeGuardTests(TestCase):
    """Unit tests for validate_uploaded_file size/IO guards."""

    def test_oversized_file_rejected_before_read(self):
        """
        Size check must happen BEFORE read(). A file-like whose read()
        would raise proves the size guard fires first.
        """
        from apps.absences.utils_upload import UploadValidationError, validate_uploaded_file

        class OversizedFile:
            name = "big.pdf"
            content_type = "application/pdf"
            size = 10 * 1024 * 1024  # 10 MB — exceeds 5 MB limit

            def read(self, n=-1):
                raise AssertionError("read() should not be called for oversized files")

            def seek(self, pos):
                pass

        with self.assertRaises(UploadValidationError) as ctx:
            validate_uploaded_file(OversizedFile())
        self.assertIn("trop volumineux", str(ctx.exception))

    def test_read_io_error_handled_gracefully(self):
        """IOError during read() raises UploadValidationError, not 500."""
        from apps.absences.utils_upload import UploadValidationError, validate_uploaded_file

        class BadReadFile:
            name = "doc.pdf"
            content_type = "application/pdf"
            size = 1024  # valid size

            def read(self, n=-1):
                raise IOError("disk failure")

            def seek(self, pos):
                pass

        with self.assertRaises(UploadValidationError) as ctx:
            validate_uploaded_file(BadReadFile())
        self.assertIn("lecture", str(ctx.exception))

    def test_missing_size_attribute_handled(self):
        """File object without .size attribute raises UploadValidationError."""
        from apps.absences.utils_upload import UploadValidationError, validate_uploaded_file

        class FakeFile:
            name = "doc.pdf"
            content_type = "application/pdf"
            # No .size attribute

            def read(self, n=-1):
                return b"%PDF-1.4"

            def seek(self, pos):
                pass

        with self.assertRaises(UploadValidationError) as ctx:
            validate_uploaded_file(FakeFile())
        self.assertIn("indisponible", str(ctx.exception))


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


class CourseDeletionTests(BaseAbsenceTestCase):
    """Tests for course deletion cascade and ProtectedError handling."""

    def _build_course_with_deps(self):
        """Create a course with seance, absence, and justification."""
        seance = Seance.objects.create(
            date_seance=date(2026, 2, 1),
            heure_debut=time(8, 0),
            heure_fin=time(10, 0),
            id_cours=self.course1,
            id_annee=self.annee,
        )
        absence = Absence.objects.create(
            id_inscription=self.inscription1,
            id_seance=seance,
            type_absence="ABSENT",
            duree_absence=Decimal("2.00"),
            statut="NON_JUSTIFIEE",
            encodee_par=self.prof,
        )
        justification = Justification.objects.create(
            id_absence=absence,
            state="EN_ATTENTE",
        )
        return seance, absence, justification

    def test_secretary_cascade_deletes_all_related_objects(self):
        """Full cascade deletion removes justifications, absences, inscriptions, seances, and course."""
        seance, absence, justification = self._build_course_with_deps()
        course_pk = self.course1.id_cours

        self.client.force_login(self.secretary)
        url = reverse("dashboard:secretary_course_delete", args=[course_pk])
        response = self.client.post(url, secure=True)

        self.assertEqual(response.status_code, 302)
        self.assertFalse(Cours.objects.filter(pk=course_pk).exists())
        self.assertFalse(Seance.objects.filter(pk=seance.pk).exists())
        self.assertFalse(Absence.objects.filter(pk=absence.pk).exists())
        self.assertFalse(Justification.objects.filter(pk=justification.pk).exists())
        self.assertFalse(Inscription.objects.filter(pk=self.inscription1.pk).exists())

    def test_course_deletion_with_protected_references_shows_error(self):
        """
        When a ProtectedError bubbles up (e.g. an unforeseen FK), the view
        must show a clear, grouped error message — NOT a 500.
        """
        seance, absence, justification = self._build_course_with_deps()
        course_pk = self.course1.id_cours

        self.client.force_login(self.secretary)
        url = reverse("dashboard:secretary_course_delete", args=[course_pk])

        # Simulate ProtectedError on Cours.delete (last step in the cascade)
        protected_err = ProtectedError(
            "Cannot delete some instances of model 'Cours'.",
            {self.inscription1},
        )
        with patch.object(Cours, "delete", side_effect=protected_err), \
             patch("apps.dashboard.views_secretary.messages") as mock_messages:
            response = self.client.post(url, secure=True)

        # View returns a redirect, not a 500
        self.assertEqual(response.status_code, 302)
        # The course must NOT have been deleted (transaction rolled back)
        self.assertTrue(Cours.objects.filter(pk=course_pk).exists())

        # Check messages.error was called with a user-friendly message
        mock_messages.error.assert_called_once()
        error_text = mock_messages.error.call_args[0][1]
        self.assertIn("Impossible de supprimer", error_text)
        self.assertIn("bloquants", error_text)
        # Verify the blocking type is mentioned (grouped by verbose_name)
        self.assertIn("inscription", error_text.lower())

    def test_course_deletion_generic_exception_shows_error(self):
        """
        A generic exception during deletion must be logged and produce
        a user-friendly error message, not a 500.
        """
        self._build_course_with_deps()
        course_pk = self.course1.id_cours

        self.client.force_login(self.secretary)
        url = reverse("dashboard:secretary_course_delete", args=[course_pk])

        with patch.object(Cours, "delete", side_effect=RuntimeError("DB connection lost")), \
             patch("apps.dashboard.views_secretary.messages") as mock_messages:
            response = self.client.post(url, secure=True)

        # View returns a redirect, not a 500
        self.assertEqual(response.status_code, 302)
        # Course still exists
        self.assertTrue(Cours.objects.filter(pk=course_pk).exists())

        # Check messages.error was called with a generic error message
        mock_messages.error.assert_called_once()
        error_text = mock_messages.error.call_args[0][1]
        self.assertIn("Erreur lors de la suppression", error_text)


class PaginationFallbackTests(BaseAbsenceTestCase):
    """Invalid page numbers must fall back to page 1, not crash or show empty."""

    def setUp(self):
        super().setUp()
        self.client.force_login(self.secretary)
        self.url = reverse("dashboard:secretary_courses")

    def test_invalid_page_number_redirects_to_page_1(self):
        """page=999, page=abc, page=-1 all return page 1 content (200)."""
        for bad_page in ("999", "abc", "-1", "0", ""):
            with self.subTest(page=bad_page):
                response = self.client.get(
                    self.url, {"page": bad_page}, secure=True
                )
                self.assertEqual(response.status_code, 200)
                page_obj = response.context["courses"]
                self.assertEqual(page_obj.number, 1)


class UserDeletionTests(BaseAbsenceTestCase):
    """Tests for admin user deletion with FK cleanup and last-admin guard."""

    def setUp(self):
        super().setUp()
        self.client.force_login(self.admin)

    def test_user_deletion_cleans_up_all_references(self):
        """Deleting a professor with courses detaches courses and deletes the user."""
        # prof has course1 assigned via professeur FK
        url = reverse("dashboard:admin_user_delete", args=[self.prof.pk])
        response = self.client.post(url, secure=True)

        self.assertEqual(response.status_code, 302)
        self.assertFalse(User.objects.filter(pk=self.prof.pk).exists())
        # Course still exists but professor is detached
        self.course1.refresh_from_db()
        self.assertIsNone(self.course1.professeur)

    def test_user_with_inscriptions_is_deactivated_not_deleted(self):
        """A student with inscriptions is deactivated, not hard-deleted."""
        url = reverse("dashboard:admin_user_delete", args=[self.student1.pk])
        response = self.client.post(url, secure=True)

        self.assertEqual(response.status_code, 302)
        self.student1.refresh_from_db()
        self.assertTrue(User.objects.filter(pk=self.student1.pk).exists())
        self.assertFalse(self.student1.actif)

    def test_cannot_delete_last_admin(self):
        """The last active admin cannot be deleted."""
        # self.admin is the only admin
        url = reverse("dashboard:admin_user_delete", args=[self.admin.pk])
        response = self.client.post(url, secure=True)

        self.assertEqual(response.status_code, 302)
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.actif)  # still active, not deleted

    def test_cannot_delete_self(self):
        """An admin cannot delete their own account."""
        url = reverse("dashboard:admin_user_delete", args=[self.admin.pk])
        response = self.client.post(url, secure=True)

        self.assertEqual(response.status_code, 302)
        self.assertTrue(User.objects.filter(pk=self.admin.pk).exists())
