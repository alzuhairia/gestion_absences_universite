"""
Tests for QR code GPS enforcement, token expiration, and scan logging.
"""

from datetime import date, time, timedelta
from unittest.mock import patch

from django.core.cache import cache
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
from apps.accounts.devices import DEVICE_COOKIE_NAME, hash_device_id, sign_device_id
from apps.accounts.models import StudentDevice, User
from apps.dashboard.models import SystemSettings
from apps.enrollments.models import Inscription


@override_settings(CACHES=_LOCAL_CACHE)
class BaseQRTestCase(TestCase):
    def setUp(self):
        # The locmem cache outlives each test's DB rollback: drop any cached
        # SystemSettings left by a previous test so defaults are really defaults.
        cache.clear()
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
        # These tests exercise QR/GPS, not device binding: the student scans from
        # an already-approved device (no auto-approval since the OTP is mandatory).
        StudentDevice.objects.create(
            user=self.student, device_id_hash=hash_device_id("qr-test-device"),
            status=StudentDevice.Status.APPROVED, approved_at=timezone.now(),
        )
        self.client.cookies[DEVICE_COOKIE_NAME] = sign_device_id("qr-test-device")

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
        assert log is not None
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
        assert log is not None


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
        assert log is not None


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
        assert log is not None


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
        assert log is not None

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
        assert token is not None
        self.assertTrue(token.verify_location)

    def test_verify_location_with_professor_gps_creates_token(self):
        self._clear_establishment_gps()
        self._post(verify_location="on", latitude="36.75250", longitude="3.04200")
        token = QRAttendanceToken.objects.filter(seance=self.seance).first()
        assert token is not None
        self.assertTrue(token.verify_location)
        assert token.latitude is not None
        self.assertAlmostEqual(float(token.latitude), 36.75250, places=4)

    def test_no_verify_location_creates_token_without_gps(self):
        """Policy off + GPS unchecked → no GPS, even with no coords anywhere."""
        s = SystemSettings.get_settings()
        s.qr_gps_required = False
        s.save()
        self._clear_establishment_gps()
        self._post()  # verify_location omitted
        token = QRAttendanceToken.objects.filter(seance=self.seance).first()
        assert token is not None
        self.assertFalse(token.verify_location)


class QRGPSRequiredPolicyTest(BaseQRTestCase):
    """
    SystemSettings.qr_gps_required (default ON): the server forces GPS on every
    QR token; the professor cannot opt out through the form.
    """

    def setUp(self):
        super().setUp()
        self.client.login(email="prof_qr@example.com", password="pass1234")
        self.form_data = {
            "date_seance": date.today().isoformat(),
            "heure_debut": "08:00",
            "heure_fin": "10:00",
        }

    def _set_policy(self, value):
        s = SystemSettings.get_settings()
        s.qr_gps_required = value
        s.save()

    def test_policy_enabled_by_default(self):
        self.assertTrue(SystemSettings.get_settings().qr_gps_required)

    def test_qr_generate_forces_gps_without_checkbox(self):
        self.client.post(
            reverse("absences:qr_generate", kwargs={"course_id": self.course.id_cours}),
            self.form_data, secure=True, follow=True,
        )
        token = QRAttendanceToken.objects.get(seance=self.seance)
        self.assertTrue(token.verify_location)

    def test_session_create_qr_mode_forces_gps_without_checkbox(self):
        self.client.post(
            reverse("absences:session_create", kwargs={"course_id": self.course.id_cours}),
            {**self.form_data, "mode": "qr"}, secure=True, follow=True,
        )
        token = QRAttendanceToken.objects.get(seance=self.seance)
        self.assertTrue(token.verify_location)

    def test_forced_gps_without_reference_blocks_generation(self):
        s = SystemSettings.get_settings()
        s.gps_latitude = None
        s.gps_longitude = None
        s.save()
        resp = self.client.post(
            reverse("absences:qr_generate", kwargs={"course_id": self.course.id_cours}),
            self.form_data, secure=True, follow=True,
        )
        self.assertFalse(QRAttendanceToken.objects.filter(seance=self.seance).exists())
        self.assertContains(resp, "aucune position de r")

    def test_policy_disabled_honours_checkbox(self):
        self._set_policy(False)
        self.client.post(
            reverse("absences:qr_generate", kwargs={"course_id": self.course.id_cours}),
            {**self.form_data, "verify_location": "on"}, secure=True, follow=True,
        )
        token = QRAttendanceToken.objects.get(seance=self.seance)
        self.assertTrue(token.verify_location)

    def test_refresh_upgrades_legacy_token_when_reference_available(self):
        old = self._create_token(verify_location=False)
        self.client.post(
            reverse("absences:qr_refresh_token", kwargs={"token": old.token}),
            secure=True, HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        new = QRAttendanceToken.objects.get(seance=self.seance, is_active=True)
        self.assertTrue(new.verify_location)

    def test_refresh_keeps_legacy_token_without_reference(self):
        s = SystemSettings.get_settings()
        s.gps_latitude = None
        s.gps_longitude = None
        s.save()
        old = self._create_token(verify_location=False)
        self.client.post(
            reverse("absences:qr_refresh_token", kwargs={"token": old.token}),
            secure=True, HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        new = QRAttendanceToken.objects.get(seance=self.seance, is_active=True)
        self.assertFalse(new.verify_location)

    def test_refresh_policy_disabled_preserves_token_setting(self):
        self._set_policy(False)
        old = self._create_token(verify_location=False)
        self.client.post(
            reverse("absences:qr_refresh_token", kwargs={"token": old.token}),
            secure=True, HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        new = QRAttendanceToken.objects.get(seance=self.seance, is_active=True)
        self.assertFalse(new.verify_location)

    def test_generate_form_shows_locked_checkbox(self):
        resp = self.client.get(
            reverse("absences:qr_generate", kwargs={"course_id": self.course.id_cours}),
            secure=True,
        )
        self.assertContains(resp, "Imposé par l'administration")
        self.assertContains(resp, "checked disabled")


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
        assert log is not None

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


class QRFinalizeNotifiesAbsentStudentsTest(BaseQRTestCase):
    """QR finalization must email newly-absent students, like manual mark_absence."""

    def test_finalize_sends_absence_email_to_non_scanner(self):
        from django.core import mail
        from apps.absences.models import Absence

        token = self._create_token(verify_location=False)
        self.client.login(email="prof_qr@example.com", password="pass1234")
        mail.outbox.clear()

        url = reverse("absences:qr_finalize", kwargs={"token": token.token})
        # on_commit callbacks only fire when the surrounding transaction commits.
        with self.captureOnCommitCallbacks(execute=True):  # pyright: ignore[reportAttributeAccessIssue]  (absent des stubs)
            resp = self.client.post(url, secure=True)
        self.assertEqual(resp.status_code, 302)

        # The student who did not scan is marked absent...
        self.assertTrue(
            Absence.objects.filter(id_inscription=self.inscription, id_seance=self.seance).exists()
        )
        # ...and receives the absence-recorded email.
        recipients = [addr for m in mail.outbox for addr in m.to]
        self.assertIn(self.student.email, recipients)
        self.assertTrue(any("Absence" in m.subject for m in mail.outbox))

    def test_finalize_does_not_email_student_who_scanned(self):
        from django.core import mail

        token = self._create_token(verify_location=False)
        # Student scanned → present, must NOT be marked absent nor emailed.
        QRScanRecord.objects.create(
            seance=self.seance, student=self.student, inscription=self.inscription,
        )
        self.client.login(email="prof_qr@example.com", password="pass1234")
        mail.outbox.clear()

        url = reverse("absences:qr_finalize", kwargs={"token": token.token})
        with self.captureOnCommitCallbacks(execute=True):  # pyright: ignore[reportAttributeAccessIssue]  (absent des stubs)
            self.client.post(url, secure=True)

        recipients = [addr for m in mail.outbox for addr in m.to]
        self.assertNotIn(self.student.email, recipients)


class ProfessorVisualCheckTest(BaseQRTestCase):
    """
    P3 — the professor checks suspicious scans in class. "Pas présent" never
    deletes the attendance record: it is invalidated (who/when/why), audited,
    and counted ABSENT at finalization.
    """

    def setUp(self):
        super().setUp()
        self.token = self._create_token(verify_location=False)
        self.record = QRScanRecord.objects.create(
            seance=self.seance, student=self.student, inscription=self.inscription,
            is_suspicious=True,
        )
        self.log = QRScanLog.objects.create(
            etudiant=self.student, seance=self.seance,
            gps_status=QRScanLog.GPSStatus.NOT_REQUIRED,
            scan_result=QRScanLog.ScanResult.VALIDATED,
            risk_score=30, anomaly_flags=["recently_approved"],
        )
        self.url = reverse("absences:qr_record_verify", kwargs={"record_id": self.record.pk})
        self.client.login(email="prof_qr@example.com", password="pass1234")

    def _post(self, action, **extra):
        return self.client.post(self.url, {"action": action, **extra}, secure=True)

    def _finalize(self):
        with self.captureOnCommitCallbacks(execute=True):  # pyright: ignore[reportAttributeAccessIssue]  (absent des stubs)
            self.client.post(
                reverse("absences:qr_finalize", kwargs={"token": self.token.token}), secure=True,
            )

    def _dashboard_partial(self):
        return self.client.get(
            reverse("absences:qr_dashboard", kwargs={"token": self.token.token}),
            secure=True, HTTP_HX_REQUEST="true",
        )

    def test_dashboard_lists_suspicious_scan_to_verify(self):
        resp = self._dashboard_partial()
        self.assertContains(resp, "À vérifier visuellement (1)")
        self.assertContains(resp, "Appareil approuvé très récemment")

    def test_seen_in_class_marks_false_positive_and_keeps_presence(self):
        resp = self._post("seen")
        self.assertEqual(resp.status_code, 302)
        self.record.refresh_from_db()
        self.log.refresh_from_db()
        self.assertFalse(self.record.invalidated)
        self.assertEqual(self.log.review_status, QRScanLog.ReviewStatus.FALSE_POSITIVE)
        self.assertEqual(self.log.reviewed_by, self.prof)
        self.assertNotContains(self._dashboard_partial(), "À vérifier visuellement")
        self.assertContains(self._dashboard_partial(), "Vérifié")

    def test_confirmation_page_before_invalidation(self):
        resp = self.client.get(self.url, secure=True)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, self.student.get_full_name())
        self.record.refresh_from_db()
        self.assertFalse(self.record.invalidated)  # GET changes nothing

    def test_invalidate_keeps_record_and_audits(self):
        from apps.audits.models import LogAudit

        self._post("invalidate", reason="Place vide à l'appel")
        self.record.refresh_from_db()
        self.log.refresh_from_db()
        self.assertTrue(QRScanRecord.objects.filter(pk=self.record.pk).exists())  # never deleted
        self.assertTrue(self.record.invalidated)
        self.assertEqual(self.record.invalidated_by, self.prof)
        self.assertIsNotNone(self.record.invalidated_at)
        self.assertEqual(self.record.invalidation_reason, "Place vide à l'appel")
        self.assertEqual(self.log.review_status, QRScanLog.ReviewStatus.CONFIRMED)
        audit = LogAudit.objects.filter(action__contains="Présence QR invalidée").get()
        self.assertEqual(audit.niveau, "WARNING")
        self.assertIn("Place vide", audit.action)

    def test_invalidated_not_counted_present_on_dashboard(self):
        self._post("invalidate")
        resp = self._dashboard_partial()
        self.assertContains(resp, "Présents (0)")
        self.assertContains(resp, "Présences invalidées (1)")

    def test_finalize_counts_invalidated_as_absent_and_emails(self):
        from django.core import mail
        from apps.absences.models import Absence

        self._post("invalidate", reason="Place vide")
        mail.outbox.clear()
        self._finalize()
        absence = Absence.objects.get(id_inscription=self.inscription, id_seance=self.seance)
        self.assertIn("invalidée par le professeur", absence.note_professeur)
        self.assertIn("Place vide", absence.note_professeur)
        self.assertTrue(QRScanRecord.objects.filter(pk=self.record.pk).exists())
        self.assertIn(self.student.email, [a for m in mail.outbox for a in m.to])

    def test_reset_restores_presence(self):
        from apps.absences.models import Absence

        self._post("invalidate")
        self._post("reset")
        self.record.refresh_from_db()
        self.log.refresh_from_db()
        self.assertFalse(self.record.invalidated)
        self.assertIsNone(self.record.invalidated_by)
        self.assertEqual(self.log.review_status, QRScanLog.ReviewStatus.TO_REVIEW)
        self._finalize()
        self.assertFalse(
            Absence.objects.filter(id_inscription=self.inscription, id_seance=self.seance).exists()
        )

    def test_seen_refused_on_invalidated_record(self):
        self._post("invalidate")
        self._post("seen")
        self.record.refresh_from_db()
        self.assertTrue(self.record.invalidated)

    def test_no_change_after_finalization(self):
        self._finalize()
        self._post("invalidate")
        self.record.refresh_from_db()
        self.assertFalse(self.record.invalidated)

    def test_other_professor_and_student_cannot_act(self):
        User.objects.create_user(
            email="other_prof@example.com", nom="Other", prenom="Prof",
            password="pass1234", role=User.Role.PROFESSEUR,
        )
        for email in ("other_prof@example.com", "stu_qr@example.com"):
            self.client.login(email=email, password="pass1234")
            self._post("invalidate")
            self.record.refresh_from_db()
            self.assertFalse(self.record.invalidated, email)

    def test_invalid_action_rejected(self):
        self._post("delete")
        self.assertTrue(QRScanRecord.objects.filter(pk=self.record.pk, invalidated=False).exists())
