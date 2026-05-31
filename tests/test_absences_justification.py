"""
Tests — cycle de vie des justificatifs (validation, téléchargement, N+1).
  - JustificationStateTests    : transitions de statut (approve/reject/double)
  - JustificationDownloadTests : téléchargement secretary + fichier manquant
  - AbsenceQueryTests          : prefetch + assertNumQueries
"""
import shutil
import tempfile
from datetime import date, time

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test.utils import override_settings
from django.urls import reverse

from apps.absences.models import Absence, Justification
from apps.absences.services import get_absences_queryset
from apps.academic_sessions.models import Seance
from apps.accounts.models import User

from .test_absences import BaseAbsenceTestCase


class JustificationStateTests(BaseAbsenceTestCase):
    """Tests des transitions d'état d'une ``Justification`` (en attente → acceptée/refusée)."""

    def _create_absence_with_justification(self):
        """Fabrique une absence ``EN_ATTENTE`` accompagnée de sa justification associée."""
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
        """L'approbation place la justification en ``ACCEPTEE`` et marque l'absence ``JUSTIFIEE``."""
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
        self.inscription1.eligible_examen = False
        self.inscription1.save(update_fields=["eligible_examen"])

        self.client.force_login(self.secretary)
        url = reverse("absences:process_justification", args=[justification.pk])
        self.client.post(url, {"action": "approve"}, secure=True)

        absence.refresh_from_db()
        self.assertEqual(absence.statut, "JUSTIFIEE")
        self.inscription1.refresh_from_db()
        self.assertTrue(self.inscription1.eligible_examen)

    def test_refuser_justificatif_sets_state(self):
        """Le refus motivé enregistre l'état ``REFUSEE`` et conserve le commentaire de gestion."""
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

        self.client.force_login(self.secretary)
        url = reverse("absences:process_justification", args=[justification.pk])
        resp1 = self.client.post(url, {"action": "approve", "comment": "OK"}, secure=True)
        self.assertEqual(resp1.status_code, 302)

        justification.refresh_from_db()
        absence.refresh_from_db()
        self.assertEqual(justification.state, "ACCEPTEE")
        self.assertEqual(justification.validee_par, self.secretary)
        self.assertEqual(absence.statut, "JUSTIFIEE")

        self.client.force_login(secretary2)
        resp2 = self.client.post(url, {"action": "approve", "comment": "Moi aussi"}, secure=True)
        self.assertEqual(resp2.status_code, 302)

        justification.refresh_from_db()
        absence.refresh_from_db()
        self.assertEqual(justification.state, "ACCEPTEE")
        self.assertEqual(justification.validee_par, self.secretary)
        self.assertEqual(justification.commentaire_gestion, "OK")
        self.assertEqual(absence.statut, "JUSTIFIEE")


class JustificationDownloadTests(BaseAbsenceTestCase):
    """Tests d'accès au téléchargement du document de justification par le secrétaire."""

    def setUp(self):
        """Prépare un MEDIA_ROOT temporaire pour stocker le PDF uploadé pendant le test."""
        super().setUp()
        self._temp_media_root = tempfile.mkdtemp()
        self._override_settings = override_settings(MEDIA_ROOT=self._temp_media_root)
        self._override_settings.enable()
        self.addCleanup(self._cleanup_media_root)

    def _cleanup_media_root(self):
        """Restaure MEDIA_ROOT et purge le dossier temporaire après chaque test."""
        self._override_settings.disable()
        shutil.rmtree(self._temp_media_root, ignore_errors=True)

    def _create_absence(self):
        """Crée une absence ``EN_ATTENTE`` servant de support à un justificatif."""
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
        """Le secrétaire peut télécharger en pièce jointe le document fourni par l'étudiant."""
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
        """Si le fichier physique a disparu du disque, la vue renvoie un 404 propre."""
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
    """Garde-fous SQL sur ``get_absences_queryset`` (anti-N+1 via prefetch)."""

    def test_absences_queryset_prefetch(self):
        """``get_absences_queryset`` doit charger les justifications en une seule requête."""
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
        with self.assertNumQueries(1):
            absences = list(qs)
            for absence in absences:
                _ = absence.justification
