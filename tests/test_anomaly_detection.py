"""
Tests — Détection d'anomalies de présence (étapes 4→6).
Règle clé : une anomalie ne bloque JAMAIS un appareil approuvé (flag + audit only).
"""

from datetime import date, time, timedelta

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.absences.anomaly import (
    FLAG_DESKTOP_SCAN,
    FLAG_DEVICE_CHURN,
    FLAG_GEO_VELOCITY,
    FLAG_GPS_TOO_PERFECT,
    FLAG_LOW_GPS_ACCURACY,
    FLAG_MULTI_ACCOUNT_DEVICE,
    FLAG_NEW_DEVICE,
    FLAG_NEW_IP,
    FLAG_RECENTLY_APPROVED,
    FLAG_SAME_DEVICE_SAME_SEANCE,
    SUSPICIOUS_THRESHOLD,
    evaluate_scan_risk,
    is_desktop_user_agent,
    score_flags,
)
from apps.absences.models import QRAttendanceToken, QRScanLog, QRScanRecord
from apps.accounts.devices import DEVICE_COOKIE_NAME, hash_device_id, sign_device_id
from apps.accounts.models import StudentDevice, User
from apps.audits.models import LogAudit
from apps.academic_sessions.models import AnneeAcademique, Seance
from apps.academics.models import Cours, Departement, Faculte
from apps.dashboard.models import SystemSettings
from apps.enrollments.models import Inscription

_LOCAL_CACHE = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "anomaly-tests",
    }
}


@override_settings(CACHES=_LOCAL_CACHE)
class BaseAnomalyTestCase(TestCase):
    def setUp(self):
        self.faculte = Faculte.objects.create(nom_faculte="Fac An")
        self.departement = Departement.objects.create(nom_departement="Dept An", id_faculte=self.faculte)
        self.annee = AnneeAcademique.objects.create(libelle="2025-2026", active=True)
        self.prof = User.objects.create_user(
            email="prof_an@example.com", nom="Prof", prenom="An",
            password="pass1234", role=User.Role.PROFESSEUR,
        )
        self.student = User.objects.create_user(
            email="stu_an@example.com", nom="Stud", prenom="An",
            password="pass1234", role=User.Role.ETUDIANT,
        )
        self.student2 = User.objects.create_user(
            email="stu2_an@example.com", nom="Stud2", prenom="An",
            password="pass1234", role=User.Role.ETUDIANT,
        )
        self.course = Cours.objects.create(
            code_cours="AN101", nom_cours="Anomaly Course",
            id_departement=self.departement, professeur=self.prof,
            nombre_total_periodes=100, niveau=1, id_annee=self.annee,
        )
        self.seance = Seance.objects.create(
            id_cours=self.course, date_seance=date.today(),
            heure_debut=time(8, 0), heure_fin=time(10, 0), id_annee=self.annee,
        )
        self.inscription = Inscription.objects.create(
            id_etudiant=self.student, id_cours=self.course,
            id_annee=self.annee, status=Inscription.Status.EN_COURS,
        )
        self.inscription2 = Inscription.objects.create(
            id_etudiant=self.student2, id_cours=self.course,
            id_annee=self.annee, status=Inscription.Status.EN_COURS,
        )
        s = SystemSettings.get_settings()
        s.gps_latitude = 36.75250
        s.gps_longitude = 3.04200
        s.gps_radius_meters = 100
        s.qr_token_duration_seconds = 60
        s.require_registered_device = True
        s.max_devices_per_student = 2
        s.anomaly_detection_enabled = True
        s.geo_velocity_max_kmh = 900
        s.gps_accuracy_max_meters = 1000
        s.save()
        self.settings = s

    def _token(self, verify_location=False):
        return QRAttendanceToken.objects.create(
            seance=self.seance, created_by=self.prof,
            expires_at=timezone.now() + timedelta(seconds=60),
            verify_location=verify_location,
        )

    def _device(self, user, secret, status=StudentDevice.Status.APPROVED):
        return StudentDevice.objects.create(
            user=user, device_id_hash=hash_device_id(secret), status=status,
            approved_at=timezone.now() if status == StudentDevice.Status.APPROVED else None,
        )

    def _cookie(self, secret):
        self.client.cookies[DEVICE_COOKIE_NAME] = sign_device_id(secret)

    def _scan_url(self, token):
        return reverse("absences:qr_scan", kwargs={"token": token.token})


# --------------------------------------------------------------------------- #
#                           UNIT — evaluate_scan_risk                          #
# --------------------------------------------------------------------------- #
class EvaluateScanRiskUnitTest(BaseAnomalyTestCase):
    def test_clean_scan_no_flags(self):
        dev = self._device(self.student, "phone-A")
        # Make device "old" so recently_approved does not fire.
        StudentDevice.objects.filter(pk=dev.pk).update(created_at=timezone.now() - timedelta(days=5), approved_at=timezone.now() - timedelta(days=5))
        dev.refresh_from_db()
        score, flags = evaluate_scan_risk(
            user=self.student, device=dev, device_id_hash=dev.device_id_hash,
            ip_address="1.2.3.4", latitude=None, longitude=None,
            accuracy=None, settings_obj=self.settings,
        )
        self.assertEqual(flags, [])
        self.assertEqual(score, 0)

    def test_multi_account_device_flag(self):
        d1 = self._device(self.student, "shared")
        d2 = self._device(self.student2, "shared")
        StudentDevice.objects.filter(pk__in=[d1.pk, d2.pk]).update(created_at=timezone.now() - timedelta(days=5), approved_at=timezone.now() - timedelta(days=5))
        d1.refresh_from_db()
        score, flags = evaluate_scan_risk(
            user=self.student, device=d1, device_id_hash=d1.device_id_hash,
            ip_address="1.2.3.4", settings_obj=self.settings,
        )
        self.assertIn(FLAG_MULTI_ACCOUNT_DEVICE, flags)
        self.assertGreaterEqual(score, 50)

    def test_new_ip_flag(self):
        dev = self._device(self.student, "phone-A")
        StudentDevice.objects.filter(pk=dev.pk).update(created_at=timezone.now() - timedelta(days=5), approved_at=timezone.now() - timedelta(days=5))
        QRScanLog.objects.create(
            etudiant=self.student, seance=self.seance,
            gps_status=QRScanLog.GPSStatus.NOT_REQUIRED,
            scan_result=QRScanLog.ScanResult.VALIDATED, ip_address="9.9.9.9",
        )
        dev.refresh_from_db()
        score, flags = evaluate_scan_risk(
            user=self.student, device=dev, device_id_hash=dev.device_id_hash,
            ip_address="1.2.3.4", settings_obj=self.settings,
        )
        self.assertIn(FLAG_NEW_IP, flags)

    def test_geo_velocity_flag(self):
        dev = self._device(self.student, "phone-A")
        StudentDevice.objects.filter(pk=dev.pk).update(created_at=timezone.now() - timedelta(days=5), approved_at=timezone.now() - timedelta(days=5))
        # Prior scan in Paris, 1 minute ago.
        log = QRScanLog.objects.create(
            etudiant=self.student, seance=self.seance,
            gps_status=QRScanLog.GPSStatus.ACCEPTED,
            scan_result=QRScanLog.ScanResult.VALIDATED,
            ip_address="1.2.3.4", latitude=48.8566, longitude=2.3522,
        )
        QRScanLog.objects.filter(pk=log.pk).update(timestamp=timezone.now() - timedelta(minutes=1))
        dev.refresh_from_db()
        # New scan in Algiers → ~1500 km in 1 min → impossible.
        score, flags = evaluate_scan_risk(
            user=self.student, device=dev, device_id_hash=dev.device_id_hash,
            ip_address="1.2.3.4", latitude=36.7525, longitude=3.0420,
            settings_obj=self.settings,
        )
        self.assertIn(FLAG_GEO_VELOCITY, flags)

    def test_low_gps_accuracy_flag(self):
        dev = self._device(self.student, "phone-A")
        StudentDevice.objects.filter(pk=dev.pk).update(created_at=timezone.now() - timedelta(days=5), approved_at=timezone.now() - timedelta(days=5))
        dev.refresh_from_db()
        score, flags = evaluate_scan_risk(
            user=self.student, device=dev, device_id_hash=dev.device_id_hash,
            ip_address="1.2.3.4", latitude=36.7525, longitude=3.0420,
            accuracy=5000, settings_obj=self.settings,
        )
        self.assertIn(FLAG_LOW_GPS_ACCURACY, flags)

    def test_recently_approved_flag(self):
        dev = self._device(self.student, "phone-A")  # approved just now
        score, flags = evaluate_scan_risk(
            user=self.student, device=dev, device_id_hash=dev.device_id_hash,
            ip_address="1.2.3.4", settings_obj=self.settings,
        )
        self.assertIn(FLAG_RECENTLY_APPROVED, flags)
        self.assertGreaterEqual(score, SUSPICIOUS_THRESHOLD)  # suspicious on its own

    def test_pre_enrolled_device_approved_today_is_flagged(self):
        """Enrolled days ago (PENDING), approved just now → still flagged."""
        dev = self._device(self.student, "phone-A")
        StudentDevice.objects.filter(pk=dev.pk).update(created_at=timezone.now() - timedelta(days=5))
        dev.refresh_from_db()
        _, flags = evaluate_scan_risk(
            user=self.student, device=dev, device_id_hash=dev.device_id_hash,
            ip_address="1.2.3.4", settings_obj=self.settings,
        )
        self.assertIn(FLAG_RECENTLY_APPROVED, flags)

    def test_device_approved_long_ago_not_flagged(self):
        dev = self._device(self.student, "phone-A")
        StudentDevice.objects.filter(pk=dev.pk).update(approved_at=timezone.now() - timedelta(hours=25))
        dev.refresh_from_db()
        _, flags = evaluate_scan_risk(
            user=self.student, device=dev, device_id_hash=dev.device_id_hash,
            ip_address="1.2.3.4", settings_obj=self.settings,
        )
        self.assertNotIn(FLAG_RECENTLY_APPROVED, flags)
        self.assertNotIn(FLAG_NEW_DEVICE, flags)  # legacy flag is no longer emitted


class MultiAccountWindowTest(BaseAnomalyTestCase):
    def _flags(self, device):
        return evaluate_scan_risk(
            user=self.student, device=device, device_id_hash=device.device_id_hash,
            ip_address="1.2.3.4", settings_obj=self.settings,
        )[1]

    def _mine(self):
        d = self._device(self.student, "shared")
        old = timezone.now() - timedelta(days=5)
        StudentDevice.objects.filter(pk=d.pk).update(created_at=old, approved_at=old)
        d.refresh_from_db()
        return d

    def test_other_account_approved_and_recent_flagged(self):
        mine = self._mine()
        self._device(self.student2, "shared")  # approved, seen now
        self.assertIn(FLAG_MULTI_ACCOUNT_DEVICE, self._flags(mine))

    def test_other_account_seen_long_ago_not_flagged(self):
        """Family PC used once by a sibling 2 months ago: no lifelong flag."""
        mine = self._mine()
        other = self._device(self.student2, "shared")
        StudentDevice.objects.filter(pk=other.pk).update(
            last_seen_at=timezone.now() - timedelta(days=60))
        self.assertNotIn(FLAG_MULTI_ACCOUNT_DEVICE, self._flags(mine))

    def test_other_account_never_approved_not_flagged(self):
        """A blocked login attempt (PENDING) is traced by rejected scans instead."""
        mine = self._mine()
        self._device(self.student2, "shared", status=StudentDevice.Status.PENDING)
        self.assertNotIn(FLAG_MULTI_ACCOUNT_DEVICE, self._flags(mine))

    def test_other_account_approved_then_revoked_still_counts(self):
        mine = self._mine()
        other = self._device(self.student2, "shared")
        StudentDevice.objects.filter(pk=other.pk).update(status=StudentDevice.Status.REVOKED)
        self.assertIn(FLAG_MULTI_ACCOUNT_DEVICE, self._flags(mine))


class DesktopScanTest(BaseAnomalyTestCase):
    UA = {
        "windows": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/125.0 Safari/537.36",
        "mac": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4) AppleWebKit/605.1.15 Version/17.4 Safari/605.1.15",
        "linux": "Mozilla/5.0 (X11; Linux x86_64; rv:126.0) Gecko/20100101 Firefox/126.0",
        "android": "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 Chrome/125.0 Mobile Safari/537.36",
        "iphone": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148 Safari/604.1",
        "android_tablet": "Mozilla/5.0 (Linux; Android 13; SM-X700) AppleWebKit/537.36 Chrome/125.0 Safari/537.36",
    }

    def test_user_agent_classification(self):
        for name in ("windows", "mac", "linux"):
            self.assertTrue(is_desktop_user_agent(self.UA[name]), name)
        for name in ("android", "iphone", "android_tablet"):
            self.assertFalse(is_desktop_user_agent(self.UA[name]), name)
        self.assertFalse(is_desktop_user_agent(""))
        self.assertFalse(is_desktop_user_agent(None))

    def test_desktop_scan_flagged_but_not_suspicious_alone(self):
        dev = self._device(self.student, "pc")
        old = timezone.now() - timedelta(days=5)
        StudentDevice.objects.filter(pk=dev.pk).update(created_at=old, approved_at=old)
        token = self._token(verify_location=False)
        self.client.login(email="stu_an@example.com", password="pass1234")
        self._cookie("pc")
        resp = self.client.post(
            self._scan_url(token), {"gps_status": "not_required"},
            secure=True, HTTP_USER_AGENT=self.UA["windows"],
        )
        self.assertContains(resp, "succ")  # never blocks
        log = QRScanLog.objects.get(etudiant=self.student, scan_result=QRScanLog.ScanResult.VALIDATED)
        self.assertEqual(log.anomaly_flags, [FLAG_DESKTOP_SCAN])
        self.assertLess(log.risk_score, SUSPICIOUS_THRESHOLD)
        self.assertFalse(QRScanRecord.objects.get(seance=self.seance, inscription=self.inscription).is_suspicious)


class GPSTooPerfectTest(BaseAnomalyTestCase):
    REF = (36.75250, 3.04200)

    def setUp(self):
        super().setUp()
        self.dev = self._device(self.student, "phone")
        old = timezone.now() - timedelta(days=5)
        StudentDevice.objects.filter(pk=self.dev.pk).update(created_at=old, approved_at=old)
        self.dev.refresh_from_db()

    def _flags(self, lat, lng, accuracy):
        return evaluate_scan_risk(
            user=self.student, device=self.dev, device_id_hash=self.dev.device_id_hash,
            ip_address="1.2.3.4", latitude=lat, longitude=lng, accuracy=accuracy,
            settings_obj=self.settings, reference_points=[self.REF, (None, None)],
        )[1]

    def _prior_scan(self, lat, lng, user=None):
        QRScanLog.objects.create(
            etudiant=user or self.student2, seance=self.seance,
            gps_status=QRScanLog.GPSStatus.ACCEPTED,
            scan_result=QRScanLog.ScanResult.VALIDATED, latitude=lat, longitude=lng,
        )

    def test_realistic_fix_not_flagged(self):
        self.assertNotIn(FLAG_GPS_TOO_PERFECT, self._flags(36.752537, 3.042081, 12.5))

    def test_sub_3m_accuracy_flagged(self):
        self.assertIn(FLAG_GPS_TOO_PERFECT, self._flags(36.752537, 3.042081, 1))

    def test_exact_reference_point_flagged(self):
        self.assertIn(FLAG_GPS_TOO_PERFECT, self._flags(36.7525, 3.042, 15))

    def test_identical_to_other_scan_with_precise_fix_flagged(self):
        self._prior_scan(36.752611, 3.042133)
        self.assertIn(FLAG_GPS_TOO_PERFECT, self._flags(36.752611, 3.042133, 5))

    def test_identical_to_other_scan_without_accuracy_flagged(self):
        self._prior_scan(36.752611, 3.042133)
        self.assertIn(FLAG_GPS_TOO_PERFECT, self._flags(36.752611, 3.042133, None))

    def test_identical_wifi_positions_in_a_room_not_flagged(self):
        """Wi-Fi positioning gives every phone in the room the same point (±40 m)."""
        self._prior_scan(36.752611, 3.042133)
        self.assertNotIn(FLAG_GPS_TOO_PERFECT, self._flags(36.752611, 3.042133, 40))

    def test_no_coordinates_no_flag(self):
        self.assertNotIn(FLAG_GPS_TOO_PERFECT, self._flags(None, None, 1))

    def test_view_passes_reference_point(self):
        """Integration: posting the establishment's exact coordinates is flagged."""
        token = self._token(verify_location=True)
        self.client.login(email="stu_an@example.com", password="pass1234")
        self._cookie("phone")
        resp = self.client.post(self._scan_url(token), {
            "gps_status": "ok", "latitude": "36.7525", "longitude": "3.0420", "accuracy": "20",
        }, secure=True)
        self.assertContains(resp, "succ")  # never blocks
        log = QRScanLog.objects.get(etudiant=self.student, scan_result=QRScanLog.ScanResult.VALIDATED)
        self.assertIn(FLAG_GPS_TOO_PERFECT, log.anomaly_flags)


class DeviceChurnTest(BaseAnomalyTestCase):
    def _approved(self, secret, days_ago, status=StudentDevice.Status.APPROVED):
        d = self._device(self.student, secret, status=status)
        when = timezone.now() - timedelta(days=days_ago)
        StudentDevice.objects.filter(pk=d.pk).update(created_at=when, approved_at=when)
        d.refresh_from_db()
        return d

    def _flags(self, device):
        return evaluate_scan_risk(
            user=self.student, device=device, device_id_hash=device.device_id_hash,
            ip_address="1.2.3.4", settings_obj=self.settings,
        )[1]

    def test_three_approvals_in_30_days_flagged(self):
        # Revoked devices keep their approved_at: they count.
        revoked = self._approved("old-1", 20)
        StudentDevice.objects.filter(pk=revoked.pk).update(status=StudentDevice.Status.REVOKED)
        self._approved("old-2", 10)
        current = self._approved("cur", 2)
        self.assertIn(FLAG_DEVICE_CHURN, self._flags(current))

    def test_two_approvals_not_flagged(self):
        self._approved("phone", 10)
        current = self._approved("tablet", 2)
        self.assertNotIn(FLAG_DEVICE_CHURN, self._flags(current))

    def test_old_approvals_outside_window_ignored(self):
        self._approved("old-1", 90)
        self._approved("old-2", 60)
        current = self._approved("cur", 2)
        self.assertNotIn(FLAG_DEVICE_CHURN, self._flags(current))

    def test_pending_devices_from_cleared_cookies_ignored(self):
        for i in range(5):
            self._device(self.student, f"pending-{i}", status=StudentDevice.Status.PENDING)
        current = self._approved("cur", 2)
        self.assertNotIn(FLAG_DEVICE_CHURN, self._flags(current))


# --------------------------------------------------------------------------- #
#                        INTEGRATION — qr_scan + anomalies                     #
# --------------------------------------------------------------------------- #
class AnomalyIntegrationTest(BaseAnomalyTestCase):
    def test_scan_stores_device_and_anomaly_fields(self):
        self._device(self.student, "phone-A")
        token = self._token(verify_location=False)
        self.client.login(email="stu_an@example.com", password="pass1234")
        self._cookie("phone-A")
        resp = self.client.post(self._scan_url(token), {"gps_status": "not_required"}, secure=True)
        self.assertContains(resp, "succ")
        log = QRScanLog.objects.get(seance=self.seance, scan_result=QRScanLog.ScanResult.VALIDATED)
        self.assertEqual(log.device_id_hash, hash_device_id("phone-A"))
        self.assertTrue(log.device_recognized)

    def test_multi_account_device_flagged_but_not_blocked(self):
        # Same physical device (same secret) approved for two students.
        d1 = self._device(self.student, "shared-phone")
        d2 = self._device(self.student2, "shared-phone")
        StudentDevice.objects.filter(pk__in=[d1.pk, d2.pk]).update(created_at=timezone.now() - timedelta(days=5), approved_at=timezone.now() - timedelta(days=5))
        token = self._token(verify_location=False)

        # Student A scans → present.
        self.client.login(email="stu_an@example.com", password="pass1234")
        self._cookie("shared-phone")
        r1 = self.client.post(self._scan_url(token), {"gps_status": "not_required"}, secure=True)
        self.assertContains(r1, "succ")
        self.assertTrue(QRScanRecord.objects.filter(seance=self.seance, inscription=self.inscription).exists())

        # Student B scans on the SAME device → present (NOT blocked) + flagged.
        self.client.logout()
        self.client.login(email="stu2_an@example.com", password="pass1234")
        self._cookie("shared-phone")
        r2 = self.client.post(self._scan_url(token), {"gps_status": "not_required"}, secure=True)
        self.assertContains(r2, "succ")  # présence acceptée malgré l'anomalie
        self.assertTrue(QRScanRecord.objects.filter(seance=self.seance, inscription=self.inscription2).exists())

        log_b = QRScanLog.objects.get(
            etudiant=self.student2, seance=self.seance,
            scan_result=QRScanLog.ScanResult.VALIDATED,
        )
        self.assertIn(FLAG_MULTI_ACCOUNT_DEVICE, log_b.anomaly_flags)
        self.assertGreaterEqual(log_b.risk_score, 50)

    def _scan_as(self, email, secret, token):
        self.client.login(email=email, password="pass1234")
        self._cookie(secret)
        return self.client.post(self._scan_url(token), {"gps_status": "not_required"}, secure=True)

    def _aged_shared_device(self):
        d1 = self._device(self.student, "shared-phone")
        d2 = self._device(self.student2, "shared-phone")
        old = timezone.now() - timedelta(days=5)
        StudentDevice.objects.filter(pk__in=[d1.pk, d2.pk]).update(created_at=old, approved_at=old)

    def test_same_device_same_seance_flags_both_scans(self):
        self._aged_shared_device()
        token = self._token(verify_location=False)
        self._scan_as("stu_an@example.com", "shared-phone", token)
        log_a = QRScanLog.objects.get(etudiant=self.student, scan_result=QRScanLog.ScanResult.VALIDATED)
        self.assertNotIn(FLAG_SAME_DEVICE_SAME_SEANCE, log_a.anomaly_flags)  # nothing known yet

        r2 = self._scan_as("stu2_an@example.com", "shared-phone", token)
        self.assertContains(r2, "succ")  # never blocks
        log_b = QRScanLog.objects.get(etudiant=self.student2, scan_result=QRScanLog.ScanResult.VALIDATED)
        self.assertIn(FLAG_SAME_DEVICE_SAME_SEANCE, log_b.anomaly_flags)

        # The FIRST scan is flagged retroactively, score and record included.
        log_a.refresh_from_db()
        self.assertIn(FLAG_SAME_DEVICE_SAME_SEANCE, log_a.anomaly_flags)
        self.assertEqual(log_a.risk_score, score_flags(log_a.anomaly_flags))
        for ins in (self.inscription, self.inscription2):
            self.assertTrue(QRScanRecord.objects.get(seance=self.seance, inscription=ins).is_suspicious)

    def test_same_device_other_seance_not_flagged(self):
        self._aged_shared_device()
        other_seance = Seance.objects.create(
            id_cours=self.course, date_seance=date.today() - timedelta(days=7),
            heure_debut=time(8, 0), heure_fin=time(10, 0), id_annee=self.annee,
        )
        QRScanLog.objects.create(
            etudiant=self.student, seance=other_seance, device_id_hash=hash_device_id("shared-phone"),
            gps_status=QRScanLog.GPSStatus.NOT_REQUIRED, scan_result=QRScanLog.ScanResult.VALIDATED,
        )
        token = self._token(verify_location=False)
        self._scan_as("stu2_an@example.com", "shared-phone", token)
        log_b = QRScanLog.objects.get(etudiant=self.student2, seance=self.seance)
        self.assertNotIn(FLAG_SAME_DEVICE_SAME_SEANCE, log_b.anomaly_flags)

    def test_different_devices_same_seance_not_flagged(self):
        """Limit (documented): Chrome for A + Firefox for B = two cookies, no flag."""
        for user, secret in ((self.student, "chrome"), (self.student2, "firefox")):
            d = self._device(user, secret)
            old = timezone.now() - timedelta(days=5)
            StudentDevice.objects.filter(pk=d.pk).update(created_at=old, approved_at=old)
        token = self._token(verify_location=False)
        self._scan_as("stu_an@example.com", "chrome", token)
        self._scan_as("stu2_an@example.com", "firefox", token)
        for log in QRScanLog.objects.filter(seance=self.seance):
            self.assertNotIn(FLAG_SAME_DEVICE_SAME_SEANCE, log.anomaly_flags)

    def test_anomaly_detection_disabled_no_flags(self):
        s = SystemSettings.get_settings()
        s.anomaly_detection_enabled = False
        s.save()
        d1 = self._device(self.student, "shared-phone")
        self._device(self.student2, "shared-phone")  # would trigger multi-account
        token = self._token(verify_location=False)
        self.client.login(email="stu_an@example.com", password="pass1234")
        self._cookie("shared-phone")
        self.client.post(self._scan_url(token), {"gps_status": "not_required"}, secure=True)
        log = QRScanLog.objects.get(seance=self.seance, scan_result=QRScanLog.ScanResult.VALIDATED)
        self.assertEqual(log.anomaly_flags, [])
        self.assertEqual(log.risk_score, 0)


# --------------------------------------------------------------------------- #
#                    INTEGRATION — écran de revue secrétariat                  #
# --------------------------------------------------------------------------- #
class SecretariatReviewTest(BaseAnomalyTestCase):
    def setUp(self):
        super().setUp()
        self.secretary = User.objects.create_user(
            email="sec_an@example.com", nom="Sec", prenom="An",
            password="pass1234", role=User.Role.SECRETAIRE,
        )

    def _make_flagged_log(self):
        return QRScanLog.objects.create(
            etudiant=self.student, seance=self.seance,
            gps_status=QRScanLog.GPSStatus.NOT_REQUIRED,
            scan_result=QRScanLog.ScanResult.VALIDATED,
            ip_address="1.2.3.4", device_id_hash="abc123",
            risk_score=50, anomaly_flags=[FLAG_MULTI_ACCOUNT_DEVICE],
        )

    def test_review_requires_staff(self):
        self.client.login(email="stu_an@example.com", password="pass1234")
        resp = self.client.get(reverse("absences:qr_anomaly_review"), secure=True)
        self.assertEqual(resp.status_code, 302)  # redirected away

    def test_review_lists_flagged_scans(self):
        self._make_flagged_log()
        self.client.login(email="sec_an@example.com", password="pass1234")
        resp = self.client.get(reverse("absences:qr_anomaly_review"), secure=True)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Même appareil utilisé par plusieurs comptes")

    def test_review_multi_filter(self):
        self._make_flagged_log()
        # A non-multi flagged log
        QRScanLog.objects.create(
            etudiant=self.student2, seance=self.seance,
            gps_status=QRScanLog.GPSStatus.NOT_REQUIRED,
            scan_result=QRScanLog.ScanResult.VALIDATED,
            ip_address="5.5.5.5", risk_score=15, anomaly_flags=[FLAG_NEW_IP],
        )
        self.client.login(email="sec_an@example.com", password="pass1234")
        resp = self.client.get(reverse("absences:qr_anomaly_review") + "?multi=1", secure=True)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Même appareil")
        self.assertNotContains(resp, "Nouvelle adresse IP")


class AnomalyReviewWorkflowTest(BaseAnomalyTestCase):
    """Secretariat classifies flagged scans; decisions are attributed and audited."""

    def setUp(self):
        super().setUp()
        self.secretary = User.objects.create_user(
            email="sec_wf@example.com", nom="Sec", prenom="Wf",
            password="pass1234", role=User.Role.SECRETAIRE,
        )
        self.record = QRScanRecord.objects.create(
            seance=self.seance, student=self.student, inscription=self.inscription,
            is_suspicious=True,
        )
        self.log = QRScanLog.objects.create(
            etudiant=self.student, seance=self.seance,
            gps_status=QRScanLog.GPSStatus.NOT_REQUIRED,
            scan_result=QRScanLog.ScanResult.VALIDATED,
            risk_score=30, anomaly_flags=[FLAG_RECENTLY_APPROVED],
        )

    def _decide(self, decision, note="", **extra):
        return self.client.post(
            reverse("absences:qr_anomaly_decide", kwargs={"log_id": self.log.pk}),
            {"decision": decision, "note": note, **extra}, secure=True,
        )

    def _review_page(self, query=""):
        return self.client.get(reverse("absences:qr_anomaly_review") + query, secure=True)

    def test_new_flagged_scan_is_to_review_and_listed_by_default(self):
        self.assertEqual(self.log.review_status, QRScanLog.ReviewStatus.TO_REVIEW)
        self.client.login(email="sec_wf@example.com", password="pass1234")
        self.assertContains(self._review_page(), "Appareil approuvé très récemment")

    def test_confirm_records_reviewer_note_and_audit(self):
        self.client.login(email="sec_wf@example.com", password="pass1234")
        self._decide(QRScanLog.ReviewStatus.CONFIRMED, "Absent au contrôle visuel")
        self.log.refresh_from_db()
        self.assertEqual(self.log.review_status, QRScanLog.ReviewStatus.CONFIRMED)
        self.assertEqual(self.log.reviewed_by, self.secretary)
        self.assertIsNotNone(self.log.reviewed_at)
        self.assertEqual(self.log.review_note, "Absent au contrôle visuel")
        audit = LogAudit.objects.filter(action__contains=f"Revue anomalie QR #{self.log.pk}").get()
        self.assertEqual(audit.niveau, "WARNING")
        self.assertIn("Absent au contrôle visuel", audit.action)

    def test_decision_never_touches_the_presence(self):
        self.client.login(email="sec_wf@example.com", password="pass1234")
        self._decide(QRScanLog.ReviewStatus.CONFIRMED)
        self.assertTrue(QRScanRecord.objects.filter(pk=self.record.pk).exists())

    def test_false_positive_leaves_the_queue(self):
        self.client.login(email="sec_wf@example.com", password="pass1234")
        self._decide(QRScanLog.ReviewStatus.FALSE_POSITIVE)
        self.assertNotContains(self._review_page(), "Appareil approuvé très récemment")
        self.assertContains(self._review_page("?status=false_positive"), "Appareil approuvé très récemment")
        self.assertContains(self._review_page("?status=all"), "Appareil approuvé très récemment")

    def test_reopen_clears_reviewer(self):
        self.client.login(email="sec_wf@example.com", password="pass1234")
        self._decide(QRScanLog.ReviewStatus.CONFIRMED)
        self._decide(QRScanLog.ReviewStatus.TO_REVIEW)
        self.log.refresh_from_db()
        self.assertEqual(self.log.review_status, QRScanLog.ReviewStatus.TO_REVIEW)
        self.assertIsNone(self.log.reviewed_by)
        self.assertIsNone(self.log.reviewed_at)

    def test_invalid_decision_rejected(self):
        self.client.login(email="sec_wf@example.com", password="pass1234")
        self._decide("delete_everything")
        self.log.refresh_from_db()
        self.assertEqual(self.log.review_status, QRScanLog.ReviewStatus.TO_REVIEW)

    def test_redirect_keeps_filters(self):
        self.client.login(email="sec_wf@example.com", password="pass1234")
        resp = self._decide(QRScanLog.ReviewStatus.FALSE_POSITIVE, status="all", multi="1")
        self.assertEqual(resp.status_code, 302)
        self.assertIn("status=all", resp["Location"])
        self.assertIn("multi=1", resp["Location"])

    def test_unknown_status_filter_falls_back(self):
        self.client.login(email="sec_wf@example.com", password="pass1234")
        resp = self._review_page("?status=<script>")
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, "<script>")

    def test_students_and_professors_cannot_decide(self):
        for email in ("stu_an@example.com", "prof_an@example.com"):
            self.client.login(email=email, password="pass1234")
            self._decide(QRScanLog.ReviewStatus.FALSE_POSITIVE)
            self.log.refresh_from_db()
            self.assertEqual(self.log.review_status, QRScanLog.ReviewStatus.TO_REVIEW, email)

    def test_rejected_scans_cannot_be_decided(self):
        rejected = QRScanLog.objects.create(
            etudiant=self.student, seance=self.seance,
            gps_status=QRScanLog.GPSStatus.NOT_REQUIRED,
            scan_result=QRScanLog.ScanResult.REJECTED_DEVICE,
        )
        self.client.login(email="sec_wf@example.com", password="pass1234")
        resp = self.client.post(
            reverse("absences:qr_anomaly_decide", kwargs={"log_id": rejected.pk}),
            {"decision": QRScanLog.ReviewStatus.CONFIRMED}, secure=True,
        )
        self.assertEqual(resp.status_code, 404)
