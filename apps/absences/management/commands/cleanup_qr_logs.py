"""
Management command to purge old QRScanLog entries.
Intended for cron / scheduled execution to prevent unbounded table growth.
"""

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.absences.models import QRScanLog


class Command(BaseCommand):
    help = "Delete QRScanLog entries older than N days (default 90)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--days",
            type=int,
            default=90,
            help="Delete logs older than this many days (default: 90).",
        )

    def handle(self, *args, **options):
        days = options["days"]
        cutoff = timezone.now() - timedelta(days=days)
        deleted, _ = QRScanLog.objects.filter(timestamp__lt=cutoff).delete()
        self.stdout.write(self.style.SUCCESS(f"Deleted {deleted} QRScanLog entries older than {days} days."))
