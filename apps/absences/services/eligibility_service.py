"""
Service : Éligibilité à l'examen et calcul de risque centralisé.

Responsabilité :
  - recalculer_eligibilite  : décide si un étudiant est bloqué (cœur du système)
  - calculer_risque_inscription : source unique de vérité pour le statut de risque
  - get_at_risk_count_for_queryset : comptage optimisé pour les dashboards

RÈGLE MÉTIER CENTRALE :
  Un étudiant est bloqué si son taux d'absence NON JUSTIFIÉE >= seuil effectif.
  Le seuil effectif = seuil du cours + marge d'exemption (si exemption accordée).
"""
import logging

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.audits.models import LogAudit
from apps.notifications.email import (
    build_eligibility_restored_email,
    build_threshold_exceeded_email,
    build_threshold_exceeded_professor_email,
    send_notification_email,
)
from apps.notifications.models import Notification

from ..models import Absence
from .absence_service import calculer_absence_stats

logger = logging.getLogger(__name__)


def get_system_threshold():
    """Récupère le seuil d'absence par défaut du système en une seule requête."""
    from apps.dashboard.models import SystemSettings

    return SystemSettings.get_settings().default_absence_threshold


def recalculer_eligibilite(inscription):
    """
    Recalcule l'éligibilité d'un étudiant à l'examen.

    IMPORTANT POUR LA SOUTENANCE :
    Règle métier du seuil d'absence :
    - Bloqué si taux d'absence NON JUSTIFIÉE >= seuil effectif
    - Seuil effectif = seuil cours + marge exemption si exemption accordée
    - Déclenché automatiquement via signal post_save sur Absence

    Args:
        inscription: Instance de Inscription à recalculer
    """
    stats = calculer_absence_stats(inscription)
    taux = stats["taux"]
    total_periodes = stats["total_periodes"]
    cours = inscription.id_cours

    if total_periodes == 0:
        if not inscription.eligible_examen:
            inscription.eligible_examen = True
            inscription.save(update_fields=["eligible_examen"])
        return

    seuil = cours.get_seuil_absence()
    seuil_effectif = min(seuil + inscription.exemption_margin, 100) if inscription.exemption_40 else seuil
    doit_bloquer = taux >= seuil_effectif

    if doit_bloquer:
        if inscription.eligible_examen:
            with transaction.atomic():
                inscription.eligible_examen = False
                inscription.save(update_fields=["eligible_examen"])

                msg = (
                    f"ALERTE : Seuil d'exemption de {seuil_effectif}% dépassé pour {cours.nom_cours}. "
                    f"Examen bloqué malgré l'exemption."
                    if inscription.exemption_40
                    else f"ALERTE : Seuil de {seuil}% dépassé pour {cours.nom_cours}. Examen bloqué."
                )
                try:
                    Notification.objects.create(
                        id_utilisateur=inscription.id_etudiant,
                        message=msg,
                        type="ALERTE",
                    )
                except Exception:
                    logger.exception("Failed to create blocking notification for %s", cours.nom_cours)

                student = inscription.id_etudiant
                professor = cours.professeur
                course_name = cours.nom_cours
                transaction.on_commit(
                    lambda: _send_threshold_emails(student, professor, course_name, taux, seuil_effectif)
                )

                try:
                    LogAudit.objects.create(
                        id_utilisateur=inscription.id_etudiant,
                        action=(
                            f"CRITIQUE: Blocage automatique examen - {cours.nom_cours} "
                            f"(Taux: {taux:.1f}%, Seuil effectif: {seuil_effectif}%"
                            f"{', exempté' if inscription.exemption_40 else ''})"
                        ),
                        adresse_ip="0.0.0.0",  # nosec B104
                        niveau="CRITIQUE",
                        objet_type="INSCRIPTION",
                        objet_id=inscription.id_inscription,
                    )
                except Exception:
                    logger.exception("Failed to create audit log for blocking %s", cours.nom_cours)
    else:
        if not inscription.eligible_examen:
            with transaction.atomic():
                inscription.eligible_examen = True
                inscription.save(update_fields=["eligible_examen"])

                try:
                    Notification.objects.create(
                        id_utilisateur=inscription.id_etudiant,
                        message=f"Information : Vous êtes à nouveau éligible à l'examen pour {cours.nom_cours}.",
                        type="INFO",
                    )
                except Exception:
                    logger.exception("Failed to create unblocking notification for %s", cours.nom_cours)

                student = inscription.id_etudiant
                course_name = cours.nom_cours

                def _send_restored():
                    subj, body, html_body = build_eligibility_restored_email(student, course_name)
                    send_notification_email(student, subj, body, html_body)

                transaction.on_commit(_send_restored)


def _send_threshold_emails(student, professor, course_name, taux, seuil):
    """Envoie les emails de dépassement de seuil à l'étudiant et au professeur."""
    try:
        subj, body, html_body = build_threshold_exceeded_email(student, course_name, taux, seuil)
        send_notification_email(student, subj, body, html_body)
        if professor:
            subj, body, html_body = build_threshold_exceeded_professor_email(
                professor, student, course_name, taux, seuil
            )
            send_notification_email(professor, subj, body, html_body)
    except Exception:
        logger.exception("Failed to send threshold emails for %s", course_name)


def calculer_risque_inscription(inscription, system_threshold=None):
    """
    Calcul centralisé du statut de risque d'une inscription.
    Source unique de vérité — évite la duplication dans 8+ vues.

    Returns:
        dict: {
            'is_at_risk', 'is_blocked', 'is_under_exemption',
            'taux', 'seuil', 'seuil_effectif',
            'total_absence', 'total_periodes'
        }
    """
    if system_threshold is None:
        system_threshold = get_system_threshold()

    cours = inscription.id_cours
    seuil = cours.seuil_absence if cours.seuil_absence is not None else system_threshold
    seuil_effectif = min(seuil + inscription.exemption_margin, 100) if inscription.exemption_40 else seuil

    stats = calculer_absence_stats(inscription)
    taux = stats["taux"]

    is_at_risk = taux >= seuil
    is_blocked = taux >= seuil_effectif
    is_under_exemption = inscription.exemption_40 and is_at_risk and not is_blocked

    return {
        "is_at_risk": is_at_risk,
        "is_blocked": is_blocked,
        "is_under_exemption": is_under_exemption,
        "taux": round(taux, 1),
        "seuil": seuil,
        "seuil_effectif": seuil_effectif,
        "total_absence": stats["total_absence"],
        "total_periodes": stats["total_periodes"],
    }


def get_at_risk_count_for_queryset(inscriptions_qs, system_threshold=None):
    """
    Compte les inscriptions à risque dans un queryset.
    Optimisé pour les vues dashboard : une seule requête SQL agrégée.

    Returns:
        tuple: (at_risk_count: int, absence_sums: dict {id_inscription: total_heures})
    """
    if system_threshold is None:
        system_threshold = get_system_threshold()

    inscription_ids = list(inscriptions_qs.values_list("id_inscription", flat=True))
    if not inscription_ids:
        return 0, {}

    today = timezone.localdate()

    absence_sums = dict(
        Absence.objects.filter(
            id_inscription__in=inscription_ids,
            statut=Absence.Statut.NON_JUSTIFIEE,
            id_seance__date_seance__lte=today,
        )
        .values("id_inscription")
        .annotate(total=Sum("duree_absence"))
        .values_list("id_inscription", "total")
    )

    at_risk_count = 0
    for ins in inscriptions_qs:
        cours = ins.id_cours
        if not cours.nombre_total_periodes:
            continue
        seuil = cours.seuil_absence if cours.seuil_absence is not None else system_threshold
        total_abs = absence_sums.get(ins.id_inscription, 0) or 0
        taux = min((total_abs / cours.nombre_total_periodes) * 100, 100)
        seuil_effectif = min(seuil + ins.exemption_margin, 100) if ins.exemption_40 else seuil
        if taux >= seuil_effectif:
            at_risk_count += 1

    return at_risk_count, absence_sums
