"""
Management command to purge old EmailEnvoi rows (e-mail send history).
Intended for cron: the history holds e-mail addresses, so it is kept only
as long as it is useful as proof of sending (default: 1 year).
"""

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.notifications.models import EmailEnvoi


class Command(BaseCommand):
    help = "Delete EmailEnvoi entries older than N days (default 365)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--days",
            type=int,
            default=365,
            help="Delete history older than this many days (default: 365).",
        )

    def handle(self, *args, **options):
        days = options["days"]
        cutoff = timezone.now() - timedelta(days=days)
        deleted, _ = EmailEnvoi.objects.filter(date_envoi__lt=cutoff).delete()
        self.stdout.write(
            self.style.SUCCESS(
                f"Deleted {deleted} EmailEnvoi entries older than {days} days."
            )
        )
