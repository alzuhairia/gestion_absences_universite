"""
Management Command: cleanup_qr_logs — apps/absences/management/commands/cleanup_qr_logs.py

Part of the UniAbsences university attendance management system.

This command purges stale ``QRScanLog`` records from the database to prevent
unbounded table growth over time.  It is intended to be executed periodically
via a cron job or a task scheduler (e.g. Celery Beat, systemd timer).

Usage::

    # Delete all QR scan logs older than 90 days (default):
    python manage.py cleanup_qr_logs

    # Delete logs older than 30 days:
    python manage.py cleanup_qr_logs --days 30
"""

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.absences.models import QRScanLog


class Command(BaseCommand):
    """
    Django management command that deletes old ``QRScanLog`` entries.

    Attributes:
        help (str): Short description shown by ``manage.py help cleanup_qr_logs``.
    """

    help = "Delete QRScanLog entries older than N days (default 90)."

    def add_arguments(self, parser):
        """
        Register command-line arguments for this command.

        Args:
            parser (argparse.ArgumentParser): the argument parser provided by
                Django's management framework.
        """
        parser.add_argument(
            "--days",
            type=int,
            default=90,
            help="Delete logs older than this many days (default: 90).",
        )

    def handle(self, *args, **options):
        """
        Execute the cleanup: delete all ``QRScanLog`` rows whose ``timestamp``
        is older than the specified number of days.

        The deletion is performed in a single bulk SQL ``DELETE`` statement via
        Django's ORM, so no per-row Python overhead is incurred.

        Args:
            *args: positional arguments (unused; required by the base class).
            **options (dict): parsed command options.  Expected keys:

                - ``days`` (int): records older than this many days are deleted.

        Side effects:
            Writes a success message (including the number of deleted rows) to
            ``self.stdout`` using Django's styled output.
        """
        days = options["days"]
        # Calculate the cutoff timestamp: records before this moment are stale.
        cutoff = timezone.now() - timedelta(days=days)
        deleted, _ = QRScanLog.objects.filter(timestamp__lt=cutoff).delete()
        self.stdout.write(self.style.SUCCESS(f"Deleted {deleted} QRScanLog entries older than {days} days."))
