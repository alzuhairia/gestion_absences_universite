"""
Management command: send weekly absence summary to all active secretaries.

Usage:
    python manage.py send_weekly_summary          # current week
    python manage.py send_weekly_summary --dry-run # preview without sending

Schedule with cron (e.g. every Monday at 08:00):
    0 8 * * 1 cd /app && python manage.py send_weekly_summary
"""

import datetime

from django.core.management.base import BaseCommand
from django.db.models import Count, Q, Sum
from django.utils import timezone

from apps.absences.models import Absence
from apps.absences.services import get_system_threshold
from apps.academic_sessions.models import AnneeAcademique
from apps.accounts.models import User
from apps.enrollments.models import Inscription
from apps.notifications.email import (
    build_weekly_summary_email,
    send_notification_email,
)


class Command(BaseCommand):
    help = "Send weekly absence summary email to all active secretaries."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print summary data without sending emails.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        today = timezone.localdate()

        # Week = Monday to Sunday ending yesterday (or today if run on Monday)
        week_end = today - datetime.timedelta(days=1)
        week_start = week_end - datetime.timedelta(days=6)

        active_year = AnneeAcademique.objects.filter(active=True).first()
        if not active_year:
            self.stderr.write("No active academic year found. Aborting.")
            return

        # 1. Total absences recorded this week
        total_absences = Absence.objects.filter(
            id_seance__date_seance__gte=week_start,
            id_seance__date_seance__lte=week_end,
        ).count()

        # 2. New blocks this week (inscriptions that became ineligible)
        #    We approximate by counting inscriptions where eligible_examen=False
        #    and have an absence recorded this week.
        blocked_inscriptions = Inscription.objects.filter(
            id_annee=active_year,
            status=Inscription.Status.EN_COURS,
            eligible_examen=False,
        )
        new_blocked = blocked_inscriptions.filter(
            absences__id_seance__date_seance__gte=week_start,
            absences__id_seance__date_seance__lte=week_end,
        ).distinct().count()

        # 3. Pending justifications
        pending_justifications = Absence.objects.filter(
            statut=Absence.Statut.EN_ATTENTE,
            id_inscription__id_annee=active_year,
        ).count()

        # 4. Courses with at-risk students
        system_threshold = get_system_threshold()
        active_inscriptions = (
            Inscription.objects.filter(
                id_annee=active_year,
                status=Inscription.Status.EN_COURS,
            )
            .select_related("id_cours")
        )

        # Aggregate non-justified absences per inscription
        abs_sums = dict(
            Absence.objects.filter(
                id_inscription__id_annee=active_year,
                id_inscription__status=Inscription.Status.EN_COURS,
                statut__in=[Absence.Statut.NON_JUSTIFIEE, Absence.Statut.EN_ATTENTE],
            )
            .values("id_inscription")
            .annotate(total=Sum("duree_absence"))
            .values_list("id_inscription", "total")
        )

        # Group by course
        course_risk = {}  # course_name -> count
        for ins in active_inscriptions:
            cours = ins.id_cours
            if not cours.nombre_total_periodes:
                continue
            seuil = cours.seuil_absence if cours.seuil_absence is not None else system_threshold
            total_abs = float(abs_sums.get(ins.id_inscription, 0) or 0)
            taux = (total_abs / cours.nombre_total_periodes) * 100
            if taux >= seuil and not ins.exemption_40:
                course_risk[cours.nom_cours] = course_risk.get(cours.nom_cours, 0) + 1

        courses_at_risk = [
            {"course_name": name, "at_risk_count": count}
            for name, count in sorted(course_risk.items(), key=lambda x: -x[1])
        ]

        summary_data = {
            "week_start": week_start.strftime("%d/%m/%Y"),
            "week_end": week_end.strftime("%d/%m/%Y"),
            "total_absences": total_absences,
            "new_blocked": new_blocked,
            "pending_justifications": pending_justifications,
            "courses_at_risk": courses_at_risk,
        }

        if dry_run:
            self.stdout.write(self.style.SUCCESS("=== DRY RUN — Weekly Summary ==="))
            for key, val in summary_data.items():
                self.stdout.write(f"  {key}: {val}")
            return

        # Send to all active secretaries
        secretaries = User.objects.filter(
            role=User.Role.SECRETAIRE,
            actif=True,
        )

        sent = 0
        for secretary in secretaries:
            subj, body, html_body = build_weekly_summary_email(secretary, summary_data)
            if send_notification_email(secretary, subj, body, html_body):
                sent += 1

        self.stdout.write(
            self.style.SUCCESS(f"Weekly summary sent to {sent}/{secretaries.count()} secretaries.")
        )
