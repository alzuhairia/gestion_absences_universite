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
    """Token QR expiré → présence REFUSÉE."""

    def test_expired_qr_rejected(self):
        """Un token dont ``expires_at`` est dépassé est rejeté et journalisé comme expiré."""
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
    """Vérification désactivée + scan OK → présence validée sans GPS."""

    def test_no_gps_required_validates(self):
        """Lorsque ``verify_location=False``, un scan réussit sans coordonnées GPS."""
        token = self._create_token(verify_location=False)
        self.client.login(email="stu_qr@example.com", password="pass1234")
        url = reverse("absences:qr_scan", kwargs={"token": token.token})
        resp = self.client.post(url, {"gps_status": "not_required"}, secure=True)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "avec succ")
        self.assertTrue(QRScanRecord.objects.filter(seance=self.seance).exists())


class ScanLogCreatedForEveryAttemptTest(BaseQRTestCase):
    """Un ``QRScanLog`` est créé pour chaque tentative, quelle qu'en soit l'issue."""

    def test_log_created_for_all_statuses(self):
        """Vérifie que les 4 scénarios (expiré, refus GPS, succès, doublon) sont tous journalisés."""
        self.client.login(email="stu_qr@example.com", password="pass1234")

        # 1) Token expiré
        t1 = self._create_token(expired=True)
        self.client.get(
            reverse("absences:qr_scan", kwargs={"token": t1.token}), secure=True
        )
        self.assertEqual(QRScanLog.objects.count(), 1)

        # 2) Token valide, GPS refusé
        t2 = self._create_token(verify_location=True)
        self.client.post(
            reverse("absences:qr_scan", kwargs={"token": t2.token}),
            {"gps_status": "refused"},
            secure=True,
        )
        self.assertEqual(QRScanLog.objects.count(), 2)

        # 3) Token valide, succès
        t3 = self._create_token(verify_location=False)
        self.client.post(
            reverse("absences:qr_scan", kwargs={"token": t3.token}),
            {"gps_status": "not_required"},
            secure=True,
        )
        self.assertEqual(QRScanLog.objects.count(), 3)

        # 4) Doublon (déjà scanné)
        self.client.post(
            reverse("absences:qr_scan", kwargs={"token": t3.token}),
            {"gps_status": "not_required"},
            secure=True,
        )
        self.assertEqual(QRScanLog.objects.count(), 4)


class DuplicateQRScanTest(BaseQRTestCase):
    """Tests que les doubles scans QR sont correctement rejetés."""

    def test_duplicate_qr_scan_rejected(self):
        """Le second scan du même étudiant sur la même séance est rejeté avec un message clair."""
        token = self._create_token(verify_location=False)
        self.client.login(email="stu_qr@example.com", password="pass1234")
        url = reverse("absences:qr_scan", kwargs={"token": token.token})

        # Premier scan — succès
        resp1 = self.client.post(url, {"gps_status": "not_required"}, secure=True)
        self.assertEqual(resp1.status_code, 200)
        self.assertContains(resp1, "succ")
        self.assertEqual(QRScanRecord.objects.filter(seance=self.seance).count(), 1)

        # Second scan — doublon rejeté
        resp2 = self.client.post(url, {"gps_status": "not_required"}, secure=True)
        self.assertEqual(resp2.status_code, 200)
        self.assertContains(resp2, "déjà été enregistrée")
        # Toujours un seul enregistrement
        self.assertEqual(QRScanRecord.objects.filter(seance=self.seance).count(), 1)
        # Le log d'audit enregistre la tentative en doublon
        log = QRScanLog.objects.filter(
            seance=self.seance, scan_result=QRScanLog.ScanResult.REJECTED_DUPLICATE,
        ).first()
        self.assertIsNotNone(log)

    def test_concurrent_duplicate_scan_handled_by_integrity_error(self):
        """
        Simule une race condition : le check ``select_for_update`` passe (aucune ligne)
        mais ``IntegrityError`` survient au ``create`` (insertion concurrente).
        """
        token = self._create_token(verify_location=False)
        self.client.login(email="stu_qr@example.com", password="pass1234")
        url = reverse("absences:qr_scan", kwargs={"token": token.token})

        # Patche ``create()`` pour lever ``IntegrityError`` — simule une insertion
        # concurrente entre le check ``select_for_update`` et le ``create``.
        with patch.object(
            type(QRScanRecord.objects), "create",
            side_effect=IntegrityError("UNIQUE constraint failed"),
        ):
            resp = self.client.post(url, {"gps_status": "not_required"}, secure=True)

        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "déjà été enregistrée")

    def test_unique_constraint_on_scan_record(self):
        """La contrainte SQL ``unique_together`` sur (seance, inscription) empêche les doublons."""
        self._create_token(verify_location=False)

        # Création directe du premier enregistrement
        QRScanRecord.objects.create(
            seance=self.seance,
            student=self.student,
            inscription=self.inscription,
        )

        # Une seconde création directe doit échouer au niveau base
        with self.assertRaises(IntegrityError):
            QRScanRecord.objects.create(
                seance=self.seance,
                student=self.student,
                inscription=self.inscription,
            )
