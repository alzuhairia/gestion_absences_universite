"""
Tests QR — validation GPS (rayon, refus, GPS indisponible, Null Island).
  - GPSRefusedVerificationEnabledTest   : GPS refusé → présence bloquée
  - GPSAcceptedWithinRadiusTest         : dans le rayon → présence validée
  - GPSAcceptedOutsideRadiusTest        : hors rayon → présence bloquée
  - GPSUnavailableVerificationEnabledTest: GPS indisponible → présence bloquée
  - NullIslandGPSSpoofingTest           : coordonnées (0,0) et proches → rejetées
"""
from django.urls import reverse

from apps.absences.models import QRScanLog, QRScanRecord
from apps.dashboard.models import SystemSettings

from .test_qr_gps import BaseQRTestCase


class GPSRefusedVerificationEnabledTest(BaseQRTestCase):
    """GPS refused + verification enabled → presence REFUSED."""

    def test_gps_refused_blocks_presence(self):
        token = self._create_token(verify_location=True)
        self.client.login(email="stu_qr@example.com", password="pass1234")
        url = reverse("absences:qr_scan", kwargs={"token": token.token})
        resp = self.client.post(url, {"gps_status": "refused"}, secure=True)
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
        }, secure=True)
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
        }, secure=True)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "zone autoris")
        self.assertFalse(QRScanRecord.objects.filter(seance=self.seance).exists())
        log = QRScanLog.objects.filter(
            seance=self.seance, scan_result=QRScanLog.ScanResult.REJECTED_DISTANCE,
        ).first()
        self.assertIsNotNone(log)


class GPSUnavailableVerificationEnabledTest(BaseQRTestCase):
    """GPS unavailable + verification enabled → presence REFUSED."""

    def test_no_coords_blocks_presence(self):
        token = self._create_token(verify_location=True)
        self.client.login(email="stu_qr@example.com", password="pass1234")
        url = reverse("absences:qr_scan", kwargs={"token": token.token})
        # POST with no latitude/longitude
        resp = self.client.post(url, {"gps_status": "unavailable"}, secure=True)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Impossible")
        self.assertFalse(QRScanRecord.objects.filter(seance=self.seance).exists())


class NullIslandGPSSpoofingTest(BaseQRTestCase):
    """Null Island (0,0) and near-zero GPS coordinates are rejected."""

    def test_null_island_gps_coordinates_rejected(self):
        """Sending latitude=0.0, longitude=0.0 must be rejected when GPS is required."""
        token = self._create_token(verify_location=True)
        self.client.login(email="stu_qr@example.com", password="pass1234")
        url = reverse("absences:qr_scan", kwargs={"token": token.token})
        resp = self.client.post(url, {
            "latitude": "0.0",
            "longitude": "0.0",
            "gps_status": "accepted",
        }, secure=True)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Impossible")
        self.assertFalse(QRScanRecord.objects.filter(seance=self.seance).exists())
        log = QRScanLog.objects.filter(
            seance=self.seance, scan_result=QRScanLog.ScanResult.REJECTED_GPS,
        ).first()
        self.assertIsNotNone(log)

    def test_near_zero_coordinates_rejected(self):
        """Coordinates very close to (0,0) — e.g. (0.001, 0.005) — are also rejected."""
        token = self._create_token(verify_location=True)
        self.client.login(email="stu_qr@example.com", password="pass1234")
        url = reverse("absences:qr_scan", kwargs={"token": token.token})
        resp = self.client.post(url, {
            "latitude": "0.005",
            "longitude": "0.001",
            "gps_status": "accepted",
        }, secure=True)
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(QRScanRecord.objects.filter(seance=self.seance).exists())

    def test_valid_negative_coordinates_accepted(self):
        """Legitimate negative coordinates (e.g. Southern hemisphere) are accepted."""
        # Set establishment to match — southern hemisphere location
        settings = SystemSettings.get_settings()
        settings.gps_latitude = -33.8688
        settings.gps_longitude = 151.2093
        settings.save()

        token = self._create_token(verify_location=True)
        self.client.login(email="stu_qr@example.com", password="pass1234")
        url = reverse("absences:qr_scan", kwargs={"token": token.token})
        resp = self.client.post(url, {
            "latitude": "-33.8688",
            "longitude": "151.2093",
            "gps_status": "accepted",
        }, secure=True)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "succ")
        self.assertTrue(QRScanRecord.objects.filter(seance=self.seance).exists())

    def test_gps_misconfiguration_returns_error(self):
        """GPS required but no reference coords configured → system error."""
        # Clear establishment GPS
        settings = SystemSettings.get_settings()
        settings.gps_latitude = None
        settings.gps_longitude = None
        settings.save()

        # Token without professor GPS either
        token = self._create_token(verify_location=True, latitude=None, longitude=None)
        self.client.login(email="stu_qr@example.com", password="pass1234")
        url = reverse("absences:qr_scan", kwargs={"token": token.token})
        resp = self.client.post(url, {
            "latitude": "36.75250",
            "longitude": "3.04200",
            "gps_status": "accepted",
        }, secure=True)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "configuration")
        self.assertFalse(QRScanRecord.objects.filter(seance=self.seance).exists())
