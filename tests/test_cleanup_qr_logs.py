"""
Tests de la commande ``cleanup_qr_logs`` (purge des logs de scans QR au-delà de la rétention).
"""
from datetime import timedelta

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from apps.absences.models import QRScanLog
from apps.accounts.models import User


class CleanupQRLogsCommandTest(TestCase):
    """Vérifie que la commande ``cleanup_qr_logs`` purge bien les vieux logs sans toucher aux récents."""

    def setUp(self):
        """Crée un étudiant utilisé comme propriétaire des logs de test."""
        self.student = User.objects.create_user(
            email="stu@example.com",
            password="testpass123",
            nom="Test",
            prenom="Student",
            role=User.Role.ETUDIANT,
        )

    def _create_log(self, days_ago):
        """Crée un ``QRScanLog`` antidaté de ``days_ago`` jours (contourne ``auto_now_add``)."""
        log = QRScanLog.objects.create(
            etudiant=self.student,
            gps_status=QRScanLog.GPSStatus.NOT_REQUIRED,
            scan_result=QRScanLog.ScanResult.VALIDATED,
        )
        # Forçage du timestamp ``auto_now_add`` pour simuler l'ancienneté
        QRScanLog.objects.filter(pk=log.pk).update(
            timestamp=timezone.now() - timedelta(days=days_ago)
        )
        return log

    def test_deletes_old_logs(self):
        """Les logs de plus de 90 jours sont supprimés ; les récents sont conservés."""
        old_log = self._create_log(days_ago=100)
        recent_log = self._create_log(days_ago=10)

        call_command("cleanup_qr_logs")

        remaining_ids = list(QRScanLog.objects.values_list("pk", flat=True))
        self.assertNotIn(old_log.pk, remaining_ids)
        self.assertIn(recent_log.pk, remaining_ids)

    def test_custom_days_argument(self):
        """L'option ``--days`` permet de paramétrer la fenêtre de rétention."""
        log_50_days = self._create_log(days_ago=50)
        log_10_days = self._create_log(days_ago=10)

        call_command("cleanup_qr_logs", "--days=30")

        remaining_ids = list(QRScanLog.objects.values_list("pk", flat=True))
        self.assertNotIn(log_50_days.pk, remaining_ids)
        self.assertIn(log_10_days.pk, remaining_ids)

    def test_no_old_logs_deletes_nothing(self):
        """Si tous les logs sont récents, la commande ne supprime rien."""
        recent = self._create_log(days_ago=5)

        call_command("cleanup_qr_logs")

        self.assertEqual(QRScanLog.objects.count(), 1)
        self.assertTrue(QRScanLog.objects.filter(pk=recent.pk).exists())
