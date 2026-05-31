"""
Commande de management — force N étudiants de démo au-dessus du seuil d'absence.

Permet de peupler les écrans « à risque / inéligible » avec un dataset cohérent
pour les démonstrations et tests de bout en bout.

Utilisation :
    python manage.py seed_at_risk              # défaut : 10 étudiants, 3 cours chacun
    python manage.py seed_at_risk --students 5 --courses 4
    python manage.py seed_at_risk --year-label 2025-2026

Pour chaque étudiant ciblé, la commande choisit ``--courses`` de ses inscriptions
actives et crée suffisamment d'absences ``NON_JUSTIFIEE`` (sur les séances existantes)
pour porter son taux d'absence strictement au-dessus du seuil du cours.
"""

from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.absences.models import Absence
from apps.academic_sessions.models import AnneeAcademique, Seance
from apps.accounts.models import User
from apps.enrollments.models import Inscription


class Command(BaseCommand):
    """Commande Django : marque ``--students`` étudiants démo comme « à risque » en dépassant le seuil."""

    help = "Marque N étudiants démo comme à risque en dépassant le seuil d'absences."

    def add_arguments(self, parser):
        """Déclare les options CLI : nombre d'étudiants, de cours et année académique cible."""
        parser.add_argument("--students", type=int, default=10)
        parser.add_argument(
            "--courses",
            type=int,
            default=3,
            help="Nombre de cours par étudiant à pousser au-dessus du seuil.",
        )
        parser.add_argument(
            "--year-label",
            type=str,
            default=None,
            help="Libellé de l'année académique à utiliser (ex. 2025-2026). "
            "Si omis, utilise l'année active.",
        )

    def handle(self, *args, **opts):
        """Point d'entrée : sélectionne les étudiants démo et leur crée des absences au-delà du seuil."""
        nb_students = opts["students"]
        nb_courses = opts["courses"]

        year = self._resolve_academic_year(opts.get("year_label"))
        if year is None:
            raise CommandError(
                "No active academic year found. Run 'python manage.py seed_demo' first."
            )

        encoder = User.objects.filter(role__in=["ADMIN", "SECRETAIRE"]).first()
        if encoder is None:
            raise CommandError(
                "No ADMIN/SECRETAIRE user to own encoded absences. "
                "Run 'python manage.py createsuperadmin' first."
            )

        students = list(
            User.objects.filter(
                role="ETUDIANT",
                email__startswith="demo_etu",
            ).order_by("email")[:nb_students]
        )
        if not students:
            raise CommandError("No demo students found. Run seed_demo first.")

        self.stdout.write(
            f"Targeting {len(students)} students, {nb_courses} courses each..."
        )

        total_absences_created = 0
        ineligible_courses = 0

        for student in students:
            inscriptions = list(
                Inscription.objects.filter(
                    id_etudiant=student,
                    id_annee=year,
                    status=Inscription.Status.EN_COURS,
                ).select_related("id_cours")[:nb_courses]
            )
            if not inscriptions:
                self.stdout.write(f"  {student.email}: no inscriptions, skipping")
                continue

            for insc in inscriptions:
                created = self._push_over_threshold(insc, encoder)
                total_absences_created += created
                insc.refresh_from_db()
                if not insc.eligible_examen:
                    ineligible_courses += 1

            self.stdout.write(
                f"  {student.email} (N{student.niveau}): processed "
                f"{len(inscriptions)} courses"
            )

        # Report
        at_risk_students = (
            User.objects.filter(
                role="ETUDIANT",
                email__startswith="demo_etu",
                inscriptions__eligible_examen=False,
                inscriptions__id_annee=year,
            )
            .distinct()
            .count()
        )

        self.stdout.write(
            self.style.SUCCESS(
                f"\nDone.\n"
                f"  Absences created : {total_absences_created}\n"
                f"  Inscriptions now ineligible: {ineligible_courses}\n"
                f"  Distinct at-risk demo students: {at_risk_students}\n"
            )
        )

    # -------------------------------------------------------- #
    def _resolve_academic_year(self, label=None):
        """Retourne l'``AnneeAcademique`` correspondante sans en créer de nouvelle."""
        if label:
            year = AnneeAcademique.objects.filter(libelle=label).first()
            if year:
                self.stdout.write(f"Academic year: using {year.libelle}")
            return year

        year = AnneeAcademique.objects.filter(active=True).first()
        if year:
            self.stdout.write(f"Academic year: using active {year.libelle}")
        return year

    # -------------------------------------------------------- #
    def _push_over_threshold(self, inscription, encoder):
        """
        Crée des absences ``NON_JUSTIFIEE`` sur les séances existantes jusqu'à
        ce que ``(heures_absent / total_periodes) * 100 > seuil``.
        """
        cours = inscription.id_cours
        seuil = cours.get_seuil_absence()
        total_periodes = cours.nombre_total_periodes

        # Target: rate strictly above seuil -> needed hours > seuil * total / 100.
        # Add small safety margin (+2%) to clearly cross the line.
        needed_hours = (Decimal(seuil + 2) * Decimal(total_periodes)) / Decimal(100)

        # Count current NON_JUSTIFIEE hours for this inscription
        current_hours = Decimal("0")
        for a in Absence.objects.filter(
            id_inscription=inscription,
            statut=Absence.Statut.NON_JUSTIFIEE,
        ).only("duree_absence"):
            current_hours += a.duree_absence

        if current_hours >= needed_hours:
            return 0  # already over

        # Walk seances in chronological order; create missing absences
        seances = Seance.objects.filter(
            id_cours=cours,
            id_annee=inscription.id_annee,
        ).order_by("date_seance", "heure_debut")

        created = 0
        with transaction.atomic():
            for seance in seances:
                if current_hours >= needed_hours:
                    break
                # Skip seances already having an absence for this inscription
                existing = Absence.objects.filter(
                    id_inscription=inscription,
                    id_seance=seance,
                ).first()
                if existing is not None:
                    if existing.statut != Absence.Statut.NON_JUSTIFIEE:
                        # Convert to NON_JUSTIFIEE full absence to count it
                        existing.statut = Absence.Statut.NON_JUSTIFIEE
                        existing.type_absence = Absence.TypeAbsence.ABSENT
                        existing.duree_absence = Decimal(str(seance.duree_heures()))
                        existing.save()
                        current_hours += existing.duree_absence
                    continue

                duree = Decimal(str(seance.duree_heures()))
                Absence.objects.create(
                    id_inscription=inscription,
                    id_seance=seance,
                    type_absence=Absence.TypeAbsence.ABSENT,
                    duree_absence=duree,
                    statut=Absence.Statut.NON_JUSTIFIEE,
                    encodee_par=encoder,
                )
                current_hours += duree
                created += 1

        return created
