"""
Tests — Liaison d'appareil de confiance (anti-fraude « présence par procuration »).
Couvre les étapes 1→3 : modèle StudentDevice, cookie signé, enrôlement, OTP e-mail,
contrôle d'appareil dans qr_scan, limite de 2 appareils approuvés.
"""

import re
from datetime import date, time, timedelta
from unittest.mock import patch

from django.core import mail
from django.core.cache import cache
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
        # The locmem cache outlives each test's DB rollback: drop cached
        # SystemSettings and OTP rate-limit counters left by a previous test.
        cache.clear()
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


class FirstDeviceRequiresOTPTest(BaseDeviceTestCase):
    """No auto-approval: even the very first device of an account needs the OTP."""

    def test_first_device_is_pending_and_presence_blocked(self):
        token = self._token(verify_location=False)
        self._login()
        # No device cookie, no device ever → still PENDING.
        resp = self.client.post(self._scan_url(token), {"gps_status": "not_required"}, secure=True)
        self.assertContains(resp, "Nouvel appareil")
        self.assertFalse(QRScanRecord.objects.filter(seance=self.seance).exists())
        dev = StudentDevice.objects.get(user=self.student)
        self.assertEqual(dev.status, StudentDevice.Status.PENDING)
        self.assertIsNone(dev.approved_at)

    def test_first_device_approved_after_otp_then_presence_recorded(self):
        token = self._token(verify_location=False)
        self._login()
        mail.outbox.clear()
        self.client.get(reverse("accounts:verify_device"), secure=True)
        code = re.search(r"\b(\d{6})\b", mail.outbox[-1].body).group(1)
        self.client.post(reverse("accounts:verify_device"), {"code": code}, secure=True)
        dev = StudentDevice.objects.get(user=self.student)
        self.assertEqual(dev.status, StudentDevice.Status.APPROVED)
        resp = self.client.post(self._scan_url(token), {"gps_status": "not_required"}, secure=True)
        self.assertContains(resp, "succ")
        self.assertTrue(QRScanRecord.objects.filter(seance=self.seance).exists())

    def test_other_students_browser_on_account_without_device_is_pending(self):
        """Buddy-punching case: account never enrolled, someone else's browser."""
        other = User.objects.create_user(
            email="other_dev@example.com", nom="Other", prenom="Dev",
            password="pass1234", role=User.Role.ETUDIANT,
        )
        self._make_device("friend-phone", StudentDevice.Status.APPROVED, user=other)
        token = self._token(verify_location=False)
        self._login()
        self._set_device_cookie("friend-phone")
        self.client.post(self._scan_url(token), {"gps_status": "not_required"}, secure=True)
        self.assertFalse(QRScanRecord.objects.filter(seance=self.seance).exists())
        dev = StudentDevice.objects.get(user=self.student)
        self.assertEqual(dev.status, StudentDevice.Status.PENDING)


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


class OTPSendQuotaTest(BaseDeviceTestCase):
    """OTP e-mails are capped per USER (3/h, 10/d), whatever the device."""

    def setUp(self):
        super().setUp()
        self._make_device("dev-A", StudentDevice.Status.APPROVED)
        self._login()
        mail.outbox.clear()

    def _resend(self):
        return self.client.post(
            reverse("accounts:verify_device"), {"action": "resend"},
            secure=True, follow=True,
        )

    def test_fourth_code_within_an_hour_is_refused(self):
        self._set_device_cookie("dev-P")
        self.client.get(reverse("accounts:verify_device"), secure=True)  # code #1
        self._resend()  # code #2
        self._resend()  # code #3
        resp = self._resend()  # refused
        self.assertEqual(len(mail.outbox), 3)
        self.assertContains(resp, "Trop de codes demand")

    def test_refused_resend_does_not_reset_attempts(self):
        self._set_device_cookie("dev-P")
        for _ in range(3):
            self._resend()
        dev = StudentDevice.objects.get(device_id_hash=hash_device_id("dev-P"))
        StudentDevice.objects.filter(pk=dev.pk).update(otp_attempts=StudentDevice.OTP_MAX_ATTEMPTS)
        self._resend()  # over quota → no new code, counter untouched
        dev.refresh_from_db()
        self.assertEqual(dev.otp_attempts, StudentDevice.OTP_MAX_ATTEMPTS)

    def test_quota_is_per_user_not_per_device(self):
        """Clearing cookies (= new device) must not grant a fresh quota."""
        for name in ("dev-P1", "dev-P2", "dev-P3", "dev-P4"):
            self._set_device_cookie(name)
            self.client.get(reverse("accounts:verify_device"), secure=True)
        self.assertEqual(len(mail.outbox), 3)

    def test_quota_does_not_affect_other_students(self):
        self._set_device_cookie("dev-P")
        for _ in range(4):
            self._resend()
        other = User.objects.create_user(
            email="other_otp@example.com", nom="O", prenom="Tp",
            password="pass1234", role=User.Role.ETUDIANT,
        )
        self._make_device("other-A", StudentDevice.Status.APPROVED, user=other)
        self.client.login(email="other_otp@example.com", password="pass1234")
        self._set_device_cookie("other-P")
        mail.outbox.clear()
        self.client.get(reverse("accounts:verify_device"), secure=True)
        self.assertEqual(len(mail.outbox), 1)

    @patch("apps.accounts.views_devices.OTP_SEND_RATES", ("100/h", "10/d"))
    def test_daily_cap(self):
        self._set_device_cookie("dev-P")
        for _ in range(11):
            self._resend()
        self.assertEqual(len(mail.outbox), 10)


class OTPVerifyRateLimitTest(BaseDeviceTestCase):
    def test_eleventh_verification_in_an_hour_is_refused_even_with_right_code(self):
        self._make_device("dev-A", StudentDevice.Status.APPROVED)
        dev = self._make_device("dev-P", StudentDevice.Status.PENDING)
        self._login()
        self._set_device_cookie("dev-P")
        url = reverse("accounts:verify_device")
        # 10 wrong guesses over two codes (5 per code).
        for _ in range(2):
            code = dev.set_otp()
            wrong = "000000" if code != "000000" else "111111"
            for _ in range(5):
                self.client.post(url, {"code": wrong}, secure=True)
        code = dev.set_otp()
        resp = self.client.post(url, {"code": code}, secure=True, follow=True)
        dev.refresh_from_db()
        self.assertEqual(dev.status, StudentDevice.Status.PENDING)
        self.assertContains(resp, "Trop de tentatives")


class OTPAttemptsAtomicityTest(BaseDeviceTestCase):
    def test_attempts_capped_even_with_stale_instance(self):
        """A concurrent request holding a stale counter cannot get an extra guess."""
        dev = self._make_device("dev-P", StudentDevice.Status.PENDING)
        code = dev.set_otp()
        stale = StudentDevice.objects.get(pk=dev.pk)  # sees otp_attempts == 0
        StudentDevice.objects.filter(pk=dev.pk).update(otp_attempts=StudentDevice.OTP_MAX_ATTEMPTS)
        self.assertFalse(stale.verify_otp(code))
        dev.refresh_from_db()
        self.assertEqual(dev.otp_attempts, StudentDevice.OTP_MAX_ATTEMPTS)

    def test_superseded_code_rejected(self):
        dev = self._make_device("dev-P", StudentDevice.Status.PENDING)
        old_code = dev.set_otp()
        stale = StudentDevice.objects.get(pk=dev.pk)
        new_code = dev.set_otp()  # resend from another request
        if old_code != new_code:
            self.assertFalse(stale.verify_otp(old_code))

    def test_every_check_consumes_one_attempt(self):
        dev = self._make_device("dev-P", StudentDevice.Status.PENDING)
        code = dev.set_otp()
        wrong = "000000" if code != "000000" else "111111"
        for _ in range(StudentDevice.OTP_MAX_ATTEMPTS):
            self.assertFalse(dev.verify_otp(wrong))
        self.assertFalse(dev.verify_otp(code))  # budget exhausted
        self.assertEqual(dev.otp_attempts, StudentDevice.OTP_MAX_ATTEMPTS)


class DeviceSecurityEmailsTest(BaseDeviceTestCase):
    """OTP e-mail carries an anti-sharing warning + device details; every
    approval/revocation notifies the student."""

    def setUp(self):
        super().setUp()
        self.secretary = User.objects.create_user(
            email="sec_mail@example.com", nom="Sec", prenom="Mail",
            password="pass1234", role=User.Role.SECRETAIRE,
        )
        mail.outbox.clear()

    def _status_mails(self):
        return [m for m in mail.outbox if "Vérification" not in m.subject]

    def test_otp_email_has_sharing_warning_and_device_details(self):
        self._make_device("dev-A", StudentDevice.Status.APPROVED)
        self._login()
        self._set_device_cookie("dev-P")
        self.client.get(
            reverse("accounts:verify_device"), secure=True,
            HTTP_USER_AGENT="Mozilla/5.0 (Linux; Android 14)",
        )
        msg = mail.outbox[-1]
        html = msg.alternatives[0][0]
        for content in (msg.body, html):
            self.assertIn("Ne communiquez jamais ce code", content)
            self.assertIn("constitue une fraude", content)
            self.assertIn("Appareil Android", content)
            self.assertIn("127.0.0.1", content)

    def test_otp_approval_notifies_student(self):
        self._make_device("dev-A", StudentDevice.Status.APPROVED)
        dev = self._make_device("dev-P", StudentDevice.Status.PENDING)
        code = dev.set_otp()
        self._login()
        self._set_device_cookie("dev-P")
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse("accounts:verify_device"), {"code": code}, secure=True)
        mails = self._status_mails()
        self.assertEqual(len(mails), 1)
        self.assertIn("Nouvel appareil approuvé", mails[0].subject)
        self.assertEqual(mails[0].to, [self.student.email])

    def test_student_revocation_notifies_student(self):
        self._make_device("dev-A", StudentDevice.Status.APPROVED)
        other = self._make_device("dev-B", StudentDevice.Status.APPROVED)
        self._login()
        self._set_device_cookie("dev-A")
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(
                reverse("accounts:my_devices"),
                {"action": "revoke", "device_pk": other.pk}, secure=True,
            )
        mails = self._status_mails()
        self.assertEqual(len(mails), 1)
        self.assertIn("Appareil révoqué", mails[0].subject)

    def test_refused_revocation_sends_nothing(self):
        approved = self._make_device("dev-A", StudentDevice.Status.APPROVED)
        self._login()
        self._set_device_cookie("dev-NEW")
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(
                reverse("accounts:my_devices"),
                {"action": "revoke", "device_pk": approved.pk}, secure=True,
            )
        self.assertEqual(self._status_mails(), [])

    def test_secretariat_actions_notify_student(self):
        dev = self._make_device("dev-P", StudentDevice.Status.PENDING)
        self.client.login(email="sec_mail@example.com", password="pass1234")
        url = reverse("accounts:secretariat_device_action", kwargs={"device_pk": dev.pk})
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(url, {"action": "approve"}, secure=True)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(url, {"action": "revoke"}, secure=True)
        subjects = [m.subject for m in self._status_mails()]
        self.assertEqual(len(subjects), 2)
        self.assertIn("approuvé par le secrétariat", subjects[0])
        self.assertIn("révoqué par le secrétariat", subjects[1])
        self.assertTrue(all(m.to == [self.student.email] for m in self._status_mails()))


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


class StudentRevocationRulesTest(BaseDeviceTestCase):
    """Only an APPROVED device may revoke an APPROVED one (password alone is not enough)."""

    def _revoke(self, target):
        return self.client.post(
            reverse("accounts:my_devices"),
            {"action": "revoke", "device_pk": target.pk}, secure=True, follow=True,
        )

    def test_pending_device_cannot_revoke_approved_device(self):
        approved = self._make_device("dev-A", StudentDevice.Status.APPROVED)
        self._login()
        self._set_device_cookie("dev-NEW")  # unknown browser → PENDING
        resp = self._revoke(approved)
        approved.refresh_from_db()
        self.assertEqual(approved.status, StudentDevice.Status.APPROVED)
        self.assertContains(resp, "contactez le secr")

    def test_pending_device_cannot_free_a_slot(self):
        """Both approved devices survive → the limit still blocks the new one."""
        a = self._make_device("dev-A", StudentDevice.Status.APPROVED)
        b = self._make_device("dev-B", StudentDevice.Status.APPROVED)
        self._login()
        self._set_device_cookie("dev-NEW")
        self._revoke(a)
        self._revoke(b)
        a.refresh_from_db()
        b.refresh_from_db()
        self.assertEqual({a.status, b.status}, {StudentDevice.Status.APPROVED})

    def test_revoked_device_cannot_revoke_approved_device(self):
        approved = self._make_device("dev-A", StudentDevice.Status.APPROVED)
        self._make_device("dev-R", StudentDevice.Status.REVOKED)
        self._login()
        self._set_device_cookie("dev-R")
        self._revoke(approved)
        approved.refresh_from_db()
        self.assertEqual(approved.status, StudentDevice.Status.APPROVED)

    def test_approved_device_can_revoke_other_approved_device(self):
        self._make_device("dev-A", StudentDevice.Status.APPROVED)
        other = self._make_device("dev-B", StudentDevice.Status.APPROVED)
        self._login()
        self._set_device_cookie("dev-A")
        self._revoke(other)
        other.refresh_from_db()
        self.assertEqual(other.status, StudentDevice.Status.REVOKED)

    def test_pending_device_can_revoke_pending_device(self):
        self._make_device("dev-A", StudentDevice.Status.APPROVED)
        pending = self._make_device("dev-P", StudentDevice.Status.PENDING)
        self._login()
        self._set_device_cookie("dev-NEW")
        self._revoke(pending)
        pending.refresh_from_db()
        self.assertEqual(pending.status, StudentDevice.Status.REVOKED)

    def test_revoke_button_hidden_for_approved_devices_on_pending_browser(self):
        self._make_device("dev-A", StudentDevice.Status.APPROVED)
        self._login()
        self._set_device_cookie("dev-NEW")
        resp = self.client.get(reverse("accounts:my_devices"), secure=True)
        self.assertContains(resp, "ne peut pas révoquer vos appareils approuvés")
        # Only the current PENDING device offers a revoke button.
        self.assertContains(resp, 'name="action" value="revoke"', count=1)


class SecretariatRevokedDeviceRecoveryTest(BaseDeviceTestCase):
    """A revoked device must be visible to — and reactivatable by — the secretariat."""

    def setUp(self):
        super().setUp()
        self.secretary = User.objects.create_user(
            email="sec_dev@example.com", nom="Sec", prenom="Dev",
            password="pass1234", role=User.Role.SECRETAIRE,
        )

    def test_revoked_device_listed_and_reactivatable(self):
        dev = self._make_device("dev-R", StudentDevice.Status.REVOKED)
        self.client.login(email="sec_dev@example.com", password="pass1234")

        # It shows up in the secretariat screen (previously only PENDING did).
        resp = self.client.get(reverse("accounts:secretariat_devices"), secure=True)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Révoqué")
        self.assertContains(resp, "Réactiver")

        # Reactivation (action=approve) restores it to APPROVED.
        resp = self.client.post(
            reverse("accounts:secretariat_device_action", kwargs={"device_pk": dev.pk}),
            {"action": "approve"}, secure=True, follow=True,
        )
        dev.refresh_from_db()
        self.assertEqual(dev.status, StudentDevice.Status.APPROVED)
