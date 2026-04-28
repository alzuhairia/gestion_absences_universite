"""
Tests — validation des fichiers uploadés comme justificatifs.
  - UploadValidationTests : rejet MIME-spoofé, extension invalide, taille dépassée
  - UploadSizeGuardTests  : guards unitaires avant read() (taille, IOError, .size manquant)
"""
import shutil
import tempfile
from datetime import date, time

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.test.utils import override_settings
from django.urls import reverse

from apps.absences.models import Absence, Justification
from apps.academic_sessions.models import Seance

from .test_absences import BaseAbsenceTestCase


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
