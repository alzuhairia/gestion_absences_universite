"""
Tests — Liaison d'appareil de confiance (anti-fraude « présence par procuration »).
Couvre les étapes 1→3 : modèle StudentDevice, cookie signé, enrôlement, OTP e-mail,
contrôle d'appareil dans qr_scan, limite de 2 appareils approuvés.
"""

from datetime import date, time, timedelta

from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.absences.models import QRAttendanceToken, QRScanLog, QRScanRecord
from apps.accounts.devices import (
    DEVICE_COOKIE_NAME,
    hash_device_id,
    sign_device_id,
)
from apps.accounts.models import StudentDevice, User
from apps.academic_sessions.models import AnneeAcademique, Seance
from apps.academics.models import Cours, Departement, Faculte
from apps.dashboard.models import SystemSettings
from apps.enrollments.models import Inscription

_LOCAL_CACHE = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "device-binding-tests",
    }
}


@override_settings(CACHES=_LOCAL_CACHE)
class BaseDeviceTestCase(TestCase):
    def setUp(self):
        self.faculte = Faculte.objects.create(nom_faculte="Fac Dev")
        self.departement = Departement.objects.create(
            nom_departement="Dept Dev", id_faculte=self.faculte,
        )
        self.annee = AnneeAcademique.objects.create(libelle="2025-2026", active=True)
        self.prof = User.objects.create_user(
            email="prof_dev@example.com", nom="Prof", prenom="Dev",
            password="pass1234", role=User.Role.PROFESSEUR,
        )
        self.student = User.objects.create_user(
            email="stu_dev@example.com", nom="Stud", prenom="Dev",
            password="pass1234", role=User.Role.ETUDIANT,
        )
        self.course = Cours.objects.create(
            code_cours="DEV101", nom_cours="Device Course",
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
        s = SystemSettings.get_settings()
        s.gps_latitude = 36.75250
        s.gps_longitude = 3.04200
        s.gps_radius_meters = 100
        s.qr_token_duration_seconds = 60
        s.require_registered_device = True
        s.max_devices_per_student = 2
        s.save()

    # --- helpers ---
    def _token(self, verify_location=False, expired=False, **kw):
        expires_at = timezone.now() + (timedelta(seconds=-10) if expired else timedelta(seconds=60))
        return QRAttendanceToken.objects.create(
            seance=self.seance, created_by=self.prof,
            expires_at=expires_at, verify_location=verify_location, **kw,
        )

    def _login(self):
        self.client.login(email="stu_dev@example.com", password="pass1234")

    def _set_device_cookie(self, device_id):
        self.client.cookies[DEVICE_COOKIE_NAME] = sign_device_id(device_id)

    def _make_device(self, device_id, status, user=None):
        u = user or self.student
        return StudentDevice.objects.create(
            user=u, device_id_hash=hash_device_id(device_id), status=status,
            approved_at=timezone.now() if status == StudentDevice.Status.APPROVED else None,
        )

    def _scan_url(self, token):
        return reverse("absences:qr_scan", kwargs={"token": token.token})


class FirstDeviceAutoApprovedTest(BaseDeviceTestCase):
    def test_first_device_auto_approved_and_presence_recorded(self):
        token = self._token(verify_location=False)
        self._login()
        # No device cookie → first device ever → auto-approved.
        resp = self.client.post(self._scan_url(token), {"gps_status": "not_required"}, secure=True)
        self.assertContains(resp, "succ")
        self.assertTrue(QRScanRecord.objects.filter(seance=self.seance).exists())
        dev = StudentDevice.objects.get(user=self.student)
        self.assertEqual(dev.status, StudentDevice.Status.APPROVED)


class KnownDeviceAcceptedTest(BaseDeviceTestCase):
    def test_known_approved_device_accepted(self):
        self._make_device("dev-A", StudentDevice.Status.APPROVED)
        token = self._token(verify_location=False)
        self._login()
        self._set_device_cookie("dev-A")
        resp = self.client.post(self._scan_url(token), {"gps_status": "not_required"}, secure=True)
        self.assertContains(resp, "succ")
        self.assertTrue(QRScanRecord.objects.filter(seance=self.seance).exists())


class NewDevicePendingBlocksTest(BaseDeviceTestCase):
    def test_new_device_is_pending_and_presence_blocked(self):
        # Student already has one approved device.
        self._make_device("dev-A", StudentDevice.Status.APPROVED)
        token = self._token(verify_location=False)
        self._login()
        # Present an unknown device → must become PENDING and block presence.
        self._set_device_cookie("dev-NEW")
        resp = self.client.post(self._scan_url(token), {"gps_status": "not_required"}, secure=True)
        self.assertFalse(QRScanRecord.objects.filter(seance=self.seance).exists())
        self.assertContains(resp, "Nouvel appareil")
        new_dev = StudentDevice.objects.get(device_id_hash=hash_device_id("dev-NEW"))
        self.assertEqual(new_dev.status, StudentDevice.Status.PENDING)
        log = QRScanLog.objects.filter(
            seance=self.seance, scan_result=QRScanLog.ScanResult.REJECTED_DEVICE,
        ).first()
        self.assertIsNotNone(log)


class OTPVerificationTest(BaseDeviceTestCase):
    def test_correct_otp_approves_device(self):
        dev = self._make_device("dev-P", StudentDevice.Status.PENDING)
        code = dev.set_otp()
        self._login()
        self._set_device_cookie("dev-P")
        resp = self.client.post(reverse("accounts:verify_device"), {"code": code}, secure=True, follow=True)
        dev.refresh_from_db()
        self.assertEqual(dev.status, StudentDevice.Status.APPROVED)

    def test_incorrect_otp_keeps_device_pending(self):
        dev = self._make_device("dev-P", StudentDevice.Status.PENDING)
        code = dev.set_otp()
        wrong = "654321" if code != "654321" else "123456"
        self._login()
        self._set_device_cookie("dev-P")
        self.client.post(reverse("accounts:verify_device"), {"code": wrong}, secure=True, follow=True)
        dev.refresh_from_db()
        self.assertEqual(dev.status, StudentDevice.Status.PENDING)
        self.assertGreaterEqual(dev.otp_attempts, 1)

    def test_get_verify_device_sends_email(self):
        self._make_device("dev-P", StudentDevice.Status.PENDING)
        self._login()
        self._set_device_cookie("dev-P")
        mail.outbox.clear()
        resp = self.client.get(reverse("accounts:verify_device"), secure=True)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(self.student.email, mail.outbox[0].to)


class RevokedDeviceBlocksTest(BaseDeviceTestCase):
    def test_revoked_device_blocks_presence(self):
        self._make_device("dev-R", StudentDevice.Status.REVOKED)
        token = self._token(verify_location=False)
        self._login()
        self._set_device_cookie("dev-R")
        resp = self.client.post(self._scan_url(token), {"gps_status": "not_required"}, secure=True)
        self.assertFalse(QRScanRecord.objects.filter(seance=self.seance).exists())
        self.assertContains(resp, "révoqu")


class MaxTwoApprovedTest(BaseDeviceTestCase):
    def test_third_device_cannot_be_approved_over_limit(self):
        self._make_device("dev-A", StudentDevice.Status.APPROVED)
        self._make_device("dev-B", StudentDevice.Status.APPROVED)
        dev_c = self._make_device("dev-C", StudentDevice.Status.PENDING)
        code = dev_c.set_otp()
        self._login()
        self._set_device_cookie("dev-C")
        self.client.post(reverse("accounts:verify_device"), {"code": code}, secure=True, follow=True)
        dev_c.refresh_from_db()
        # OTP was correct, but the limit (2) blocks approval → stays PENDING.
        self.assertEqual(dev_c.status, StudentDevice.Status.PENDING)
        self.assertEqual(
            StudentDevice.objects.filter(
                user=self.student, status=StudentDevice.Status.APPROVED
            ).count(),
            2,
        )

    def test_pending_and_revoked_do_not_count_toward_limit(self):
        self._make_device("dev-A", StudentDevice.Status.APPROVED)
        self._make_device("dev-X", StudentDevice.Status.PENDING)
        self._make_device("dev-Y", StudentDevice.Status.REVOKED)
        # Only 1 approved → a new device CAN still be approved.
        dev_b = self._make_device("dev-B", StudentDevice.Status.PENDING)
        code = dev_b.set_otp()
        self._login()
        self._set_device_cookie("dev-B")
        self.client.post(reverse("accounts:verify_device"), {"code": code}, secure=True, follow=True)
        dev_b.refresh_from_db()
        self.assertEqual(dev_b.status, StudentDevice.Status.APPROVED)


class TamperedAndMissingCookieTest(BaseDeviceTestCase):
    def test_tampered_cookie_not_recognized(self):
        self._make_device("dev-A", StudentDevice.Status.APPROVED)
        token = self._token(verify_location=False)
        self._login()
        # Forged/garbage cookie → invalid signature → treated as a NEW device.
        self.client.cookies[DEVICE_COOKIE_NAME] = "not-a-valid-signed-value"
        resp = self.client.post(self._scan_url(token), {"gps_status": "not_required"}, secure=True)
        self.assertFalse(QRScanRecord.objects.filter(seance=self.seance).exists())
        self.assertContains(resp, "Nouvel appareil")

    def test_deleted_cookie_triggers_new_device(self):
        self._make_device("dev-A", StudentDevice.Status.APPROVED)
        token = self._token(verify_location=False)
        self._login()
        # No cookie at all, but student already has an approved device → new = PENDING.
        resp = self.client.post(self._scan_url(token), {"gps_status": "not_required"}, secure=True)
        self.assertFalse(QRScanRecord.objects.filter(seance=self.seance).exists())
        self.assertContains(resp, "Nouvel appareil")


class DeviceWithGPSInteractionTest(BaseDeviceTestCase):
    def test_gps_ok_and_approved_device_accepted(self):
        self._make_device("dev-A", StudentDevice.Status.APPROVED)
        token = self._token(verify_location=True)
        self._login()
        self._set_device_cookie("dev-A")
        resp = self.client.post(self._scan_url(token), {
            "latitude": "36.75250", "longitude": "3.04200", "gps_status": "accepted",
        }, secure=True)
        self.assertContains(resp, "succ")
        self.assertTrue(QRScanRecord.objects.filter(seance=self.seance).exists())

    def test_gps_out_of_zone_refused_even_with_approved_device(self):
        self._make_device("dev-A", StudentDevice.Status.APPROVED)
        token = self._token(verify_location=True)
        self._login()
        self._set_device_cookie("dev-A")
        resp = self.client.post(self._scan_url(token), {
            "latitude": "48.8566", "longitude": "2.3522", "gps_status": "accepted",
        }, secure=True)
        self.assertContains(resp, "zone autoris")
        self.assertFalse(QRScanRecord.objects.filter(seance=self.seance).exists())

    def test_expired_qr_refused_even_with_approved_device(self):
        self._make_device("dev-A", StudentDevice.Status.APPROVED)
        token = self._token(expired=True)
        self._login()
        self._set_device_cookie("dev-A")
        resp = self.client.get(self._scan_url(token), secure=True)
        self.assertContains(resp, "expir")
        self.assertFalse(QRScanRecord.objects.filter(seance=self.seance).exists())


class RequireRegisteredDeviceToggleTest(BaseDeviceTestCase):
    def test_disabled_toggle_allows_unregistered_device(self):
        s = SystemSettings.get_settings()
        s.require_registered_device = False
        s.save()
        # Student has an approved device, but scans from a brand-new one.
        self._make_device("dev-A", StudentDevice.Status.APPROVED)
        token = self._token(verify_location=False)
        self._login()
        self._set_device_cookie("dev-NEW")
        resp = self.client.post(self._scan_url(token), {"gps_status": "not_required"}, secure=True)
        self.assertContains(resp, "succ")
        self.assertTrue(QRScanRecord.objects.filter(seance=self.seance).exists())
