from datetime import date, time
import shutil
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.test.utils import override_settings
from django.urls import reverse

from apps.accounts.models import User
from apps.academics.models import Faculte, Departement, Cours
from apps.academic_sessions.models import AnneeAcademique, Seance
from apps.enrollments.models import Inscription
from apps.absences.models import Absence, Justification
from apps.absences.services import get_absences_queryset


class BaseAbsenceTestCase(TestCase):
    def setUp(self):
        self.faculte = Faculte.objects.create(nom_faculte='Faculte Test')
        self.departement = Departement.objects.create(
            nom_departement='Departement Test',
            id_faculte=self.faculte,
        )
        self.annee = AnneeAcademique.objects.create(libelle='2024-2025', active=True)

        self.prof = User.objects.create_user(
            email='prof@example.com',
            nom='Prof',
            prenom='Test',
            password='pass1234',
            role=User.Role.PROFESSEUR,
        )
        self.secretary = User.objects.create_user(
            email='sec@example.com',
            nom='Sec',
            prenom='Test',
            password='pass1234',
            role=User.Role.SECRETAIRE,
        )
        self.student1 = User.objects.create_user(
            email='stu1@example.com',
            nom='Student',
            prenom='One',
            password='pass1234',
            role=User.Role.ETUDIANT,
        )
        self.student2 = User.objects.create_user(
            email='stu2@example.com',
            nom='Student',
            prenom='Two',
            password='pass1234',
            role=User.Role.ETUDIANT,
        )

        self.course1 = Cours.objects.create(
            code_cours='C1',
            nom_cours='Course 1',
            nombre_total_periodes=20,
            id_departement=self.departement,
            professeur=self.prof,
            id_annee=self.annee,
            niveau=1,
        )
        self.course2 = Cours.objects.create(
            code_cours='C2',
            nom_cours='Course 2',
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

        url = reverse('absences:mark_absence', args=[self.course1.id_cours])
        data = {
            'date_seance': '2026-01-01',
            'heure_debut': '08:00',
            'heure_fin': '10:00',
            f'status_{self.inscription1.id_inscription}': 'ABSENT',
            f'status_{self.inscription2.id_inscription}': 'ABSENT',
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
            type_absence='SEANCE',
            duree_absence=2.0,
            statut='EN_ATTENTE',
            encodee_par=self.secretary,
        )
        justification = Justification.objects.create(
            id_absence=absence,
            state='EN_ATTENTE',
        )
        return absence, justification

    def test_valider_justificatif_sets_state(self):
        absence, justification = self._create_absence_with_justification()

        self.client.force_login(self.secretary)
        url = reverse('absences:valider_justification', args=[absence.id_absence])
        response = self.client.post(url, secure=True)

        self.assertEqual(response.status_code, 302)
        absence.refresh_from_db()
        justification.refresh_from_db()

        self.assertEqual(absence.statut, 'JUSTIFIEE')
        self.assertEqual(justification.state, 'ACCEPTEE')
        self.assertEqual(justification.validee_par, self.secretary)

    def test_refuser_justificatif_sets_state(self):
        absence, justification = self._create_absence_with_justification()

        self.client.force_login(self.secretary)
        url = reverse('absences:refuser_justification', args=[absence.id_absence])
        response = self.client.post(url, secure=True)

        self.assertEqual(response.status_code, 302)
        absence.refresh_from_db()
        justification.refresh_from_db()

        self.assertEqual(absence.statut, 'NON_JUSTIFIEE')
        self.assertEqual(justification.state, 'REFUSEE')
        self.assertEqual(justification.validee_par, self.secretary)


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
            type_absence='SEANCE',
            duree_absence=2.0,
            statut='EN_ATTENTE',
            encodee_par=self.secretary,
        )

    def test_secretary_can_download_uploaded_justification(self):
        absence = self._create_absence()
        pdf_file = SimpleUploadedFile(
            'justificatif_test.pdf',
            b'%PDF-1.4 sample',
            content_type='application/pdf',
        )
        justification = Justification.objects.create(
            id_absence=absence,
            state='EN_ATTENTE',
            document=pdf_file,
        )

        self.client.force_login(self.secretary)
        url = reverse('absences:download_justification', args=[justification.id_justification])
        response = self.client.get(url, secure=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn('attachment;', response['Content-Disposition'])
        self.assertIn(b'%PDF-1.4', b''.join(response.streaming_content))

    def test_download_returns_404_when_file_is_missing(self):
        absence = self._create_absence()
        justification = Justification.objects.create(
            id_absence=absence,
            state='EN_ATTENTE',
        )
        justification.document.name = 'justifications/introuvable.pdf'
        justification.save(update_fields=['document'])

        self.client.force_login(self.secretary)
        url = reverse('absences:download_justification', args=[justification.id_justification])
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
                type_absence='SEANCE',
                duree_absence=2.0,
                statut='EN_ATTENTE',
                encodee_par=self.secretary,
            )
            Justification.objects.create(
                id_absence=absence,
                state='EN_ATTENTE',
            )

        qs = get_absences_queryset(self.inscription1)
        with self.assertNumQueries(2):
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
            type_absence='SEANCE',
            duree_absence=2.0,
            statut='NON_JUSTIFIEE',
            encodee_par=self.secretary,
        )

    def test_upload_rejects_mime_spoofed_file(self):
        absence = self._create_absence()
        fake_pdf = SimpleUploadedFile(
            'proof.pdf',
            b'\x89PNG\r\n\x1a\nspoofed-content',
            content_type='application/pdf',
        )

        response = self.client.post(
            reverse('absences:upload', args=[absence.id_absence]),
            data={'comment': 'test', 'document': fake_pdf},
            secure=True,
        )

        self.assertEqual(response.status_code, 302)
        self.assertFalse(Justification.objects.filter(id_absence=absence).exists())

    def test_upload_rejects_invalid_extension(self):
        absence = self._create_absence()
        bad_ext = SimpleUploadedFile(
            'proof.txt',
            b'%PDF-1.4 real-content',
            content_type='application/pdf',
        )

        response = self.client.post(
            reverse('absences:upload', args=[absence.id_absence]),
            data={'comment': 'test', 'document': bad_ext},
            secure=True,
        )

        self.assertEqual(response.status_code, 302)
        self.assertFalse(Justification.objects.filter(id_absence=absence).exists())

    def test_upload_rejects_forged_binary_file(self):
        absence = self._create_absence()
        forged_jpeg = SimpleUploadedFile(
            'proof.jpg',
            b'%PDF-1.4 forged-jpeg',
            content_type='image/jpeg',
        )

        response = self.client.post(
            reverse('absences:upload', args=[absence.id_absence]),
            data={'comment': 'test', 'document': forged_jpeg},
            secure=True,
        )

        self.assertEqual(response.status_code, 302)
        self.assertFalse(Justification.objects.filter(id_absence=absence).exists())

    def test_upload_rejects_file_over_size_limit(self):
        absence = self._create_absence()
        oversized = SimpleUploadedFile(
            'proof.pdf',
            b'%PDF-1.4\n' + (b'a' * (5 * 1024 * 1024)),
            content_type='application/pdf',
        )

        response = self.client.post(
            reverse('absences:upload', args=[absence.id_absence]),
            data={'comment': 'test', 'document': oversized},
            secure=True,
        )

        self.assertEqual(response.status_code, 302)
        self.assertFalse(Justification.objects.filter(id_absence=absence).exists())
