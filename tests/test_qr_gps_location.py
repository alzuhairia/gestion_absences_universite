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
    """GPS refusé + vérification activée → présence REFUSÉE."""

    def test_gps_refused_blocks_presence(self):
        """Étudiant qui refuse de partager sa position : la présence est bloquée et le refus journalisé."""
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
    """GPS accepté + dans le rayon autorisé → présence VALIDÉE."""

    def test_gps_ok_within_radius(self):
        """Position GPS proche de l'établissement : la présence est validée et journalisée."""
        token = self._create_token(verify_location=True)
        self.client.login(email="stu_qr@example.com", password="pass1234")
        url = reverse("absences:qr_scan", kwargs={"token": token.token})
        # Position très proche de l'établissement
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
    """GPS accepté + hors du rayon autorisé → présence REFUSÉE."""

    def test_gps_ok_outside_radius(self):
        """Étudiant à plus de 1500 km : la présence est refusée pour distance hors zone."""
        token = self._create_token(verify_location=True)
        self.client.login(email="stu_qr@example.com", password="pass1234")
        url = reverse("absences:qr_scan", kwargs={"token": token.token})
        # Position éloignée (Paris ~1500 km)
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
    """GPS indisponible + vérification activée → présence REFUSÉE."""

    def test_no_coords_blocks_presence(self):
        """Téléphone sans GPS : aucune coordonnée envoyée → présence bloquée."""
        token = self._create_token(verify_location=True)
        self.client.login(email="stu_qr@example.com", password="pass1234")
        url = reverse("absences:qr_scan", kwargs={"token": token.token})
        # POST sans latitude/longitude
        resp = self.client.post(url, {"gps_status": "unavailable"}, secure=True)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Impossible")
        self.assertFalse(QRScanRecord.objects.filter(seance=self.seance).exists())


class NullIslandGPSSpoofingTest(BaseQRTestCase):
    """Coordonnées GPS Null Island (0,0) ou proches : rejet anti-spoofing."""

    def test_null_island_gps_coordinates_rejected(self):
        """Envoyer ``latitude=0.0, longitude=0.0`` doit être rejeté quand le GPS est requis."""
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
        """Coordonnées très proches de (0,0) — ex. (0.001, 0.005) — sont également rejetées."""
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
        """Les coordonnées négatives légitimes (ex. hémisphère sud) sont acceptées."""
        # Place l'établissement dans l'hémisphère sud pour faire correspondre
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
        """GPS requis mais aucune coordonnée de référence configurée → erreur système."""
        # Vide les coordonnées GPS de l'établissement
        settings = SystemSettings.get_settings()
        settings.gps_latitude = None
        settings.gps_longitude = None
        settings.save()

        # Token sans coordonnées GPS du professeur non plus
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
