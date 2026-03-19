"""
Tests for QR code GPS enforcement, token expiration, and scan logging.
"""

from datetime import date, time, timedelta

from django.test import TestCase, RequestFactory
from django.urls import reverse
from django.utils import timezone

from apps.absences.models import QRAttendanceToken, QRScanLog, QRScanRecord
from apps.absences.views import _haversine
from apps.academic_sessions.models import AnneeAcademique, Seance
from apps.academics.models import Cours, Departement, Faculte
from apps.accounts.models import User
from apps.dashboard.models import SystemSettings
from apps.enrollments.models import Inscription


class BaseQRTestCase(TestCase):
    def setUp(self):
        self.faculte = Faculte.objects.create(nom_faculte="Faculte QR")
        self.departement = Departement.objects.create(
            nom_departement="Dept QR", id_faculte=self.faculte,
        )
        self.annee = AnneeAcademique.objects.create(libelle="2025-2026", active=True)
        self.prof = User.objects.create_user(
            email="prof_qr@example.com", nom="Prof", prenom="QR",
            password="pass1234", role=User.Role.PROFESSEUR,
        )
        self.student = User.objects.create_user(
            email="stu_qr@example.com", nom="Student", prenom="QR",
            password="pass1234", role=User.Role.ETUDIANT,
        )
        self.course = Cours.objects.create(
            code_cours="QR101", nom_cours="QR Test Course",
            id_departement=self.departement, professeur=self.prof,
            nombre_total_periodes=100, niveau=1, id_annee=self.annee,
        )
        self.seance = Seance.objects.create(
            id_cours=self.course, date_seance=date.today(),
            heure_debut=time(8, 0), heure_fin=time(10, 0),
            id_annee=self.annee,
        )
        self.inscription = Inscription.objects.create(
            id_etudiant=self.student, id_cours=self.course,
            id_annee=self.annee, status=Inscription.Status.EN_COURS,
        )
        # Set up GPS coords for the establishment
        settings = SystemSettings.get_settings()
        settings.gps_latitude = 36.75250
        settings.gps_longitude = 3.04200
        settings.gps_radius_meters = 100
        settings.qr_token_duration_seconds = 60
        settings.save()

    def _create_token(self, verify_location=False, expired=False, **kwargs):
        expires_at = timezone.now() + (
            timedelta(seconds=-10) if expired else timedelta(seconds=60)
        )
        return QRAttendanceToken.objects.create(
            seance=self.seance, created_by=self.prof,
            expires_at=expires_at, verify_location=verify_location,
            **kwargs,
        )


class HaversineTest(TestCase):
    def test_same_point_zero_distance(self):
        self.assertAlmostEqual(_haversine(36.75, 3.04, 36.75, 3.04), 0, places=0)

    def test_known_distance(self):
        # ~111 km between these latitudes
        dist = _haversine(36.0, 3.0, 37.0, 3.0)
        self.assertAlmostEqual(dist, 111_195, delta=500)


class GPSRefusedVerificationEnabledTest(BaseQRTestCase):
    """GPS refused + verification enabled → presence REFUSED."""

    def test_gps_refused_blocks_presence(self):
        token = self._create_token(verify_location=True)
        self.client.login(email="stu_qr@example.com", password="pass1234")
        url = reverse("absences:qr_scan", kwargs={"token": token.token})
        resp = self.client.post(url, {"gps_status": "refused"})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "localisation est obligatoire")
        # No scan record created
        self.assertFalse(QRScanRecord.objects.filter(seance=self.seance).exists())
        # But a log was created
        log = QRScanLog.objects.filter(seance=self.seance).first()
        self.assertIsNotNone(log)
        self.assertEqual(log.scan_result, QRScanLog.ScanResult.REJECTED_GPS)
        self.assertEqual(log.gps_status, QRScanLog.GPSStatus.REFUSED)


class GPSAcceptedWithinRadiusTest(BaseQRTestCase):
    """GPS OK + within radius → presence VALIDATED."""

    def test_gps_ok_within_radius(self):
        token = self._create_token(verify_location=True)
        self.client.login(email="stu_qr@example.com", password="pass1234")
        url = reverse("absences:qr_scan", kwargs={"token": token.token})
        # Position very close to establishment
        resp = self.client.post(url, {
            "latitude": "36.75250",
            "longitude": "3.04200",
            "gps_status": "accepted",
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "avec succ")
        self.assertTrue(QRScanRecord.objects.filter(seance=self.seance).exists())
        log = QRScanLog.objects.filter(
            seance=self.seance, scan_result=QRScanLog.ScanResult.VALIDATED,
        ).first()
        self.assertIsNotNone(log)


class GPSAcceptedOutsideRadiusTest(BaseQRTestCase):
    """GPS OK + outside radius → presence REFUSED."""

    def test_gps_ok_outside_radius(self):
        token = self._create_token(verify_location=True)
        self.client.login(email="stu_qr@example.com", password="pass1234")
        url = reverse("absences:qr_scan", kwargs={"token": token.token})
        # Position far away (Paris ~1500km)
        resp = self.client.post(url, {
            "latitude": "48.8566",
            "longitude": "2.3522",
            "gps_status": "accepted",
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "zone autoris")
        self.assertFalse(QRScanRecord.objects.filter(seance=self.seance).exists())
        log = QRScanLog.objects.filter(
            seance=self.seance, scan_result=QRScanLog.ScanResult.REJECTED_DISTANCE,
        ).first()
        self.assertIsNotNone(log)


class QRExpiredTest(BaseQRTestCase):
    """QR expired → presence REFUSED."""

    def test_expired_qr_rejected(self):
        token = self._create_token(expired=True)
        self.client.login(email="stu_qr@example.com", password="pass1234")
        url = reverse("absences:qr_scan", kwargs={"token": token.token})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "expir")
        self.assertFalse(QRScanRecord.objects.filter(seance=self.seance).exists())
        log = QRScanLog.objects.filter(
            seance=self.seance, scan_result=QRScanLog.ScanResult.REJECTED_EXPIRED,
        ).first()
        self.assertIsNotNone(log)


class QRValidNoGPSRequiredTest(BaseQRTestCase):
    """Verification disabled + scan OK → presence validated without GPS."""

    def test_no_gps_required_validates(self):
        token = self._create_token(verify_location=False)
        self.client.login(email="stu_qr@example.com", password="pass1234")
        url = reverse("absences:qr_scan", kwargs={"token": token.token})
        resp = self.client.post(url, {"gps_status": "not_required"})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "avec succ")
        self.assertTrue(QRScanRecord.objects.filter(seance=self.seance).exists())


class ScanLogCreatedForEveryAttemptTest(BaseQRTestCase):
    """A QRScanLog is created for each attempt."""

    def test_log_created_for_all_statuses(self):
        self.client.login(email="stu_qr@example.com", password="pass1234")

        # 1) Expired token
        t1 = self._create_token(expired=True)
        self.client.get(reverse("absences:qr_scan", kwargs={"token": t1.token}))
        self.assertEqual(QRScanLog.objects.count(), 1)

        # 2) Valid token, GPS refused
        t2 = self._create_token(verify_location=True)
        self.client.post(
            reverse("absences:qr_scan", kwargs={"token": t2.token}),
            {"gps_status": "refused"},
        )
        self.assertEqual(QRScanLog.objects.count(), 2)

        # 3) Valid token, success
        t3 = self._create_token(verify_location=False)
        self.client.post(
            reverse("absences:qr_scan", kwargs={"token": t3.token}),
            {"gps_status": "not_required"},
        )
        self.assertEqual(QRScanLog.objects.count(), 3)

        # 4) Duplicate (already scanned)
        self.client.post(
            reverse("absences:qr_scan", kwargs={"token": t3.token}),
            {"gps_status": "not_required"},
        )
        self.assertEqual(QRScanLog.objects.count(), 4)


class GPSUnavailableVerificationEnabledTest(BaseQRTestCase):
    """GPS unavailable + verification enabled → presence REFUSED."""

    def test_no_coords_blocks_presence(self):
        token = self._create_token(verify_location=True)
        self.client.login(email="stu_qr@example.com", password="pass1234")
        url = reverse("absences:qr_scan", kwargs={"token": token.token})
        # POST with no latitude/longitude
        resp = self.client.post(url, {"gps_status": "unavailable"})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Impossible")
        self.assertFalse(QRScanRecord.objects.filter(seance=self.seance).exists())
