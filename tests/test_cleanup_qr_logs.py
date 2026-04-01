from datetime import timedelta

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from apps.absences.models import QRScanLog
from apps.accounts.models import User


class CleanupQRLogsCommandTest(TestCase):
    def setUp(self):
        self.student = User.objects.create_user(
            email="stu@example.com",
            password="testpass123",
            nom="Test",
            prenom="Student",
            role=User.Role.ETUDIANT,
        )

    def _create_log(self, days_ago):
        log = QRScanLog.objects.create(
            etudiant=self.student,
            gps_status=QRScanLog.GPSStatus.NOT_REQUIRED,
            scan_result=QRScanLog.ScanResult.VALIDATED,
        )
        # Override auto_now_add timestamp
        QRScanLog.objects.filter(pk=log.pk).update(
            timestamp=timezone.now() - timedelta(days=days_ago)
        )
        return log

    def test_deletes_old_logs(self):
        """Logs older than 90 days are deleted."""
        old_log = self._create_log(days_ago=100)
        recent_log = self._create_log(days_ago=10)

        call_command("cleanup_qr_logs")

        remaining_ids = list(QRScanLog.objects.values_list("pk", flat=True))
        self.assertNotIn(old_log.pk, remaining_ids)
        self.assertIn(recent_log.pk, remaining_ids)

    def test_custom_days_argument(self):
        """--days flag controls the retention window."""
        log_50_days = self._create_log(days_ago=50)
        log_10_days = self._create_log(days_ago=10)

        call_command("cleanup_qr_logs", "--days=30")

        remaining_ids = list(QRScanLog.objects.values_list("pk", flat=True))
        self.assertNotIn(log_50_days.pk, remaining_ids)
        self.assertIn(log_10_days.pk, remaining_ids)

    def test_no_old_logs_deletes_nothing(self):
        """If all logs are recent, nothing is deleted."""
        recent = self._create_log(days_ago=5)

        call_command("cleanup_qr_logs")

        self.assertEqual(QRScanLog.objects.count(), 1)
        self.assertTrue(QRScanLog.objects.filter(pk=recent.pk).exists())
