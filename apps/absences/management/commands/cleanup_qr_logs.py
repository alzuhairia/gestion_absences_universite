"""
Commande de gestion : cleanup_qr_logs — apps/absences/management/commands/cleanup_qr_logs.py

Fait partie du système universitaire de gestion des présences UniAbsences.

Cette commande purge les enregistrements ``QRScanLog`` obsolètes de la base
de données afin d'éviter une croissance non bornée de la table dans le
temps. Elle est destinée à être exécutée périodiquement via une tâche cron
ou un planificateur de tâches (ex. Celery Beat, timer systemd).

Utilisation ::

    # Supprime tous les journaux de scan QR de plus de 90 jours (par défaut) :
    python manage.py cleanup_qr_logs

    # Supprime les journaux de plus de 30 jours :
    python manage.py cleanup_qr_logs --days 30
"""

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.absences.models import QRScanLog


class Command(BaseCommand):
    """
    Commande de gestion Django qui supprime les entrées ``QRScanLog`` anciennes.

    Attributs :
        help (str) : description courte affichée par ``manage.py help cleanup_qr_logs``.
    """

    help = "Supprime les entrées QRScanLog de plus de N jours (90 par défaut)."

    def add_arguments(self, parser):
        """
        Déclare les arguments en ligne de commande pour cette commande.

        Args :
            parser (argparse.ArgumentParser) : le parser d'arguments fourni
                par le framework de gestion de Django.
        """
        parser.add_argument(
            "--days",
            type=int,
            default=90,
            help="Supprime les journaux de plus de N jours (par défaut : 90).",
        )

    def handle(self, *args, **options):
        """
        Exécute le nettoyage : supprime toutes les lignes ``QRScanLog`` dont le
        ``timestamp`` est antérieur au nombre de jours spécifié.

        La suppression est effectuée en un seul ``DELETE`` SQL en lot via
        l'ORM de Django, donc aucun surcoût Python par ligne n'est encouru.

        Args :
            *args : arguments positionnels (inutilisés ; requis par la classe de base).
            **options (dict) : options de commande analysées. Clés attendues :

                - ``days`` (int) : les enregistrements de plus de N jours sont supprimés.

        Effets de bord :
            Écrit un message de succès (incluant le nombre de lignes supprimées) sur
            ``self.stdout`` en utilisant la sortie stylisée de Django.
        """
        days = options["days"]
        # Calcule l'horodatage de coupure : les enregistrements antérieurs à ce moment sont obsolètes.
        cutoff = timezone.now() - timedelta(days=days)
        deleted, _ = QRScanLog.objects.filter(timestamp__lt=cutoff).delete()
        self.stdout.write(self.style.SUCCESS(f"{deleted} entrées QRScanLog de plus de {days} jours supprimées."))
