"""
Tests QR — expiration du token, logs d'audit et doublons.
  - QRExpiredTest                 : QR expiré → présence refusée
  - QRValidNoGPSRequiredTest      : sans GPS requis → présence validée
  - ScanLogCreatedForEveryAttemptTest: log créé pour chaque tentative
  - DuplicateQRScanTest           : double scan → rejet + IntegrityError race condition
"""
from unittest.mock import patch

from django.db import IntegrityError
from django.urls import reverse

from apps.absences.models import QRScanLog, QRScanRecord

from .test_qr_gps import BaseQRTestCase


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
        with patch.object(
            type(QRScanRecord.objects), "create",
            side_effect=IntegrityError("UNIQUE constraint failed"),
        ):
            resp = self.client.post(url, {"gps_status": "not_required"}, secure=True)

        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "déjà été enregistrée")

    def test_unique_constraint_on_scan_record(self):
        """DB-level unique_together on (seance, inscription) prevents duplicates."""
        self._create_token(verify_location=False)

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
