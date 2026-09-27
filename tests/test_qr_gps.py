"""
Tests for QR code GPS enforcement, token expiration, and scan logging.
"""

from datetime import date, time, timedelta
from unittest.mock import patch

from django.db import IntegrityError
from django.test import TestCase, RequestFactory, override_settings
from django.urls import reverse
from django.utils import timezone

# Isolate the cache from the shared (production) Redis instance: SystemSettings
# is cached via django.core.cache, and a leaked prod singleton would fail
# full_clean() against the empty test DB. A per-process locmem cache keeps these
# tests hermetic without touching the real cache.
_LOCAL_CACHE = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "qr-gps-tests",
    }
}

from apps.absences.models import QRAttendanceToken, QRScanLog, QRScanRecord
from apps.absences.views import _haversine
from apps.academic_sessions.models import AnneeAcademique, Seance
from apps.academics.models import Cours, Departement, Faculte
from apps.accounts.models import User
from apps.dashboard.models import SystemSettings
from apps.enrollments.models import Inscription


@override_settings(CACHES=_LOCAL_CACHE)
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


class QRExpiredTest(BaseQRTestCase):
    """QR expired → presence REFUSED."""

    def test_expired_qr_rejected(self):
        token = self._create_token(expired=True)
        self.client.login(email="stu_qr@example.com", password="pass1234")
        url = reverse("absences:qr_scan", kwargs={"token": token.token})
        resp = self.client.get(url, secure=True)
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
        resp = self.client.post(url, {"gps_status": "not_required"}, secure=True)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "avec succ")
        self.assertTrue(QRScanRecord.objects.filter(seance=self.seance).exists())


class ScanLogCreatedForEveryAttemptTest(BaseQRTestCase):
    """A QRScanLog is created for each attempt."""

    def test_log_created_for_all_statuses(self):
        self.client.login(email="stu_qr@example.com", password="pass1234")

        # 1) Expired token
        t1 = self._create_token(expired=True)
        self.client.get(
            reverse("absences:qr_scan", kwargs={"token": t1.token}), secure=True
        )
        self.assertEqual(QRScanLog.objects.count(), 1)

        # 2) Valid token, GPS refused
        t2 = self._create_token(verify_location=True)
        self.client.post(
            reverse("absences:qr_scan", kwargs={"token": t2.token}),
            {"gps_status": "refused"},
            secure=True,
        )
        self.assertEqual(QRScanLog.objects.count(), 2)

        # 3) Valid token, success
        t3 = self._create_token(verify_location=False)
        self.client.post(
            reverse("absences:qr_scan", kwargs={"token": t3.token}),
            {"gps_status": "not_required"},
            secure=True,
        )
        self.assertEqual(QRScanLog.objects.count(), 3)

        # 4) Duplicate (already scanned)
        self.client.post(
            reverse("absences:qr_scan", kwargs={"token": t3.token}),
            {"gps_status": "not_required"},
            secure=True,
        )
        self.assertEqual(QRScanLog.objects.count(), 4)


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


class ProfessorGPSReferenceTest(BaseQRTestCase):
    """
    When the establishment GPS is not configured, the reference used must be the
    professor's position stored ON THE TOKEN (i.e. specific to that seance).
    """

    def _clear_establishment_gps(self):
        s = SystemSettings.get_settings()
        s.gps_latitude = None
        s.gps_longitude = None
        s.save()

    def test_professor_gps_used_when_no_establishment_gps(self):
        self._clear_establishment_gps()
        token = self._create_token(
            verify_location=True, latitude=36.75250, longitude=3.04200
        )
        self.client.login(email="stu_qr@example.com", password="pass1234")
        url = reverse("absences:qr_scan", kwargs={"token": token.token})
        resp = self.client.post(url, {
            "latitude": "36.75250", "longitude": "3.04200",
            "gps_status": "accepted",
        }, secure=True)
        self.assertContains(resp, "succ")
        self.assertTrue(QRScanRecord.objects.filter(seance=self.seance).exists())

    def test_professor_gps_rejects_far_student(self):
        self._clear_establishment_gps()
        token = self._create_token(
            verify_location=True, latitude=36.75250, longitude=3.04200
        )
        self.client.login(email="stu_qr@example.com", password="pass1234")
        url = reverse("absences:qr_scan", kwargs={"token": token.token})
        # Paris — ~1500 km from the professor position
        resp = self.client.post(url, {
            "latitude": "48.8566", "longitude": "2.3522",
            "gps_status": "accepted",
        }, secure=True)
        self.assertContains(resp, "zone autoris")
        self.assertFalse(QRScanRecord.objects.filter(seance=self.seance).exists())


class QRGenerationGPSGuardTest(BaseQRTestCase):
    """
    verify_location=ON must never create a token without an available GPS
    reference — otherwise every student scan fails with a config error.
    """

    def setUp(self):
        super().setUp()
        self.client.login(email="prof_qr@example.com", password="pass1234")
        self.gen_url = reverse(
            "absences:qr_generate", kwargs={"course_id": self.course.id_cours}
        )

    def _post(self, **extra):
        data = {
            "date_seance": date.today().isoformat(),
            "heure_debut": "08:00",
            "heure_fin": "10:00",
        }
        data.update(extra)
        return self.client.post(self.gen_url, data, secure=True, follow=True)

    def _clear_establishment_gps(self):
        s = SystemSettings.get_settings()
        s.gps_latitude = None
        s.gps_longitude = None
        s.save()

    def test_verify_location_without_any_reference_blocks_generation(self):
        self._clear_establishment_gps()
        resp = self._post(verify_location="on")
        self.assertFalse(QRAttendanceToken.objects.filter(seance=self.seance).exists())
        self.assertContains(resp, "aucune position de r")

    def test_verify_location_with_establishment_gps_creates_token(self):
        # Establishment GPS is configured in BaseQRTestCase.setUp
        self._post(verify_location="on")
        token = QRAttendanceToken.objects.filter(seance=self.seance).first()
        self.assertIsNotNone(token)
        self.assertTrue(token.verify_location)

    def test_verify_location_with_professor_gps_creates_token(self):
        self._clear_establishment_gps()
        self._post(verify_location="on", latitude="36.75250", longitude="3.04200")
        token = QRAttendanceToken.objects.filter(seance=self.seance).first()
        self.assertIsNotNone(token)
        self.assertTrue(token.verify_location)
        self.assertAlmostEqual(token.latitude, 36.75250, places=4)

    def test_no_verify_location_creates_token_without_gps(self):
        """GPS disabled → existing behavior preserved even with no coords anywhere."""
        self._clear_establishment_gps()
        self._post()  # verify_location omitted
        token = QRAttendanceToken.objects.filter(seance=self.seance).first()
        self.assertIsNotNone(token)
        self.assertFalse(token.verify_location)


class QRTokenExpirationDurationTest(BaseQRTestCase):
    """Token expiration uses the configured duration and is the single source of truth."""

    def test_token_created_with_configured_duration(self):
        s = SystemSettings.get_settings()
        s.qr_token_duration_seconds = 30
        s.save()
        self.client.login(email="prof_qr@example.com", password="pass1234")
        self.client.post(
            reverse("absences:qr_generate", kwargs={"course_id": self.course.id_cours}),
            {"date_seance": date.today().isoformat(),
             "heure_debut": "08:00", "heure_fin": "10:00"},
            secure=True, follow=True,
        )
        token = QRAttendanceToken.objects.filter(seance=self.seance).latest("created_at")
        delta = (token.expires_at - token.created_at).total_seconds()
        self.assertAlmostEqual(delta, 30, delta=2)

    def test_token_valid_before_expiry(self):
        token = self._create_token()  # +60s
        self.assertFalse(token.is_expired)
        self.assertTrue(token.is_usable)

    def test_token_refused_after_expiry(self):
        token = self._create_token(expired=True)
        self.assertTrue(token.is_expired)
        self.assertFalse(token.is_usable)


class QRRefreshTokenTest(BaseQRTestCase):
    """Regeneration creates a brand-new token with its own fresh expiration."""

    def test_refresh_creates_new_token_with_own_expiration(self):
        s = SystemSettings.get_settings()
        s.qr_token_duration_seconds = 30
        s.save()
        old = self._create_token(verify_location=False)  # helper sets +60s
        old_expires = old.expires_at
        self.client.login(email="prof_qr@example.com", password="pass1234")
        url = reverse("absences:qr_refresh_token", kwargs={"token": old.token})
        resp = self.client.post(
            url, secure=True, HTTP_X_REQUESTED_WITH="XMLHttpRequest"
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()

        # A different token is issued
        self.assertNotEqual(data["token"], str(old.token))
        # Old token is deactivated
        old.refresh_from_db()
        self.assertFalse(old.is_active)
        # New token is active with a fresh expiration derived from the config
        new = QRAttendanceToken.objects.get(token=data["token"])
        self.assertTrue(new.is_active)
        now = timezone.now()
        self.assertAlmostEqual((new.expires_at - now).total_seconds(), 30, delta=3)
        # The OLD expiration (+60s) must NOT be reused
        self.assertNotEqual(new.expires_at, old_expires)

    def test_refresh_json_exposes_source_of_truth_values(self):
        s = SystemSettings.get_settings()
        s.qr_token_duration_seconds = 30
        s.save()
        old = self._create_token(verify_location=False)
        self.client.login(email="prof_qr@example.com", password="pass1234")
        resp = self.client.post(
            reverse("absences:qr_refresh_token", kwargs={"token": old.token}),
            secure=True, HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        data = resp.json()
        self.assertEqual(data["duration_seconds"], 30)
        self.assertLessEqual(data["remaining_seconds"], 30)
        self.assertGreaterEqual(data["remaining_seconds"], 27)


class QRDashboardFrontendValuesTest(BaseQRTestCase):
    """
    The dashboard sends SECONDS (not milliseconds) and a server-computed remaining
    time, so a 30s validity can never render as 1:45 / 2:00.
    """

    def _dashboard(self, duration_seconds):
        s = SystemSettings.get_settings()
        s.qr_token_duration_seconds = duration_seconds
        s.save()
        token = QRAttendanceToken.objects.create(
            seance=self.seance, created_by=self.prof,
            expires_at=timezone.now() + timedelta(seconds=duration_seconds),
        )
        self.client.login(email="prof_qr@example.com", password="pass1234")
        return self.client.get(
            reverse("absences:qr_dashboard", kwargs={"token": token.token}),
            secure=True,
        )

    def test_30s_values_are_seconds_under_a_minute(self):
        resp = self._dashboard(30)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context["qr_duration_seconds"], 30)
        remaining = resp.context["qr_remaining_seconds"]
        self.assertLessEqual(remaining, 30)
        self.assertGreaterEqual(remaining, 28)
        # 30 seconds must never be interpreted as minutes (1:45 / 2:00).
        self.assertLess(remaining, 60)

    def test_short_duration_values_are_seconds_not_milliseconds(self):
        resp = self._dashboard(5)
        self.assertEqual(resp.context["qr_duration_seconds"], 5)
        remaining = resp.context["qr_remaining_seconds"]
        self.assertLessEqual(remaining, 5)
        # If seconds were confused with ms, remaining would be ~5000.
        self.assertLess(remaining, 10)

    def test_progress_bar_percentage_never_exceeds_100(self):
        """remaining <= duration guarantees (remaining/duration)*100 <= 100."""
        resp = self._dashboard(30)
        remaining = resp.context["qr_remaining_seconds"]
        duration = resp.context["qr_duration_seconds"]
        pct = (remaining / duration) * 100
        self.assertLessEqual(pct, 100)
        self.assertGreaterEqual(pct, 0)


class DuplicateQRScanTest(BaseQRTestCase):
    """Tests that double QR scans are properly rejected."""

    def test_duplicate_qr_scan_rejected(self):
        """Second scan by the same student for the same seance is rejected."""
        token = self._create_token(verify_location=False)
        self.client.login(email="stu_qr@example.com", password="pass1234")
        url = reverse("absences:qr_scan", kwargs={"token": token.token})

        # First scan — success
        resp1 = self.client.post(url, {"gps_status": "not_required"}, secure=True)
        self.assertEqual(resp1.status_code, 200)
        self.assertContains(resp1, "succ")
        self.assertEqual(QRScanRecord.objects.filter(seance=self.seance).count(), 1)

        # Second scan — duplicate rejected
        resp2 = self.client.post(url, {"gps_status": "not_required"}, secure=True)
        self.assertEqual(resp2.status_code, 200)
        self.assertContains(resp2, "déjà été enregistrée")
        # Still only one record
        self.assertEqual(QRScanRecord.objects.filter(seance=self.seance).count(), 1)
        # Audit log records the duplicate attempt
        log = QRScanLog.objects.filter(
            seance=self.seance, scan_result=QRScanLog.ScanResult.REJECTED_DUPLICATE,
        ).first()
        self.assertIsNotNone(log)

    def test_concurrent_duplicate_scan_handled_by_integrity_error(self):
        """
        Simulates a race condition: select_for_update check passes (no row yet)
        but IntegrityError fires on create (concurrent insert between check and create).
        """
        token = self._create_token(verify_location=False)
        self.client.login(email="stu_qr@example.com", password="pass1234")
        url = reverse("absences:qr_scan", kwargs={"token": token.token})

        # Patch create() to raise IntegrityError — simulates a concurrent insert
        # that happened between the select_for_update check and the create call.
        # No first scan needed: the checks will naturally return None.
        # Patch ONLY the QRScanRecord manager instance (not the shared Manager
        # class) so unrelated ORM creates — e.g. device enrolment — are untouched.
        with patch.object(
            QRScanRecord.objects, "create",
            side_effect=IntegrityError("UNIQUE constraint failed"),
        ):
            resp = self.client.post(url, {"gps_status": "not_required"}, secure=True)

        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "déjà été enregistrée")

    def test_unique_constraint_on_scan_record(self):
        """DB-level unique_together on (seance, inscription) prevents duplicates."""
        token = self._create_token(verify_location=False)

        # Create first record directly
        QRScanRecord.objects.create(
            seance=self.seance,
            student=self.student,
            inscription=self.inscription,
        )

        # Second direct create should fail at DB level
        with self.assertRaises(IntegrityError):
            QRScanRecord.objects.create(
                seance=self.seance,
                student=self.student,
                inscription=self.inscription,
            )
