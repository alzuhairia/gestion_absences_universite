import datetime

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

from .models import Absence

# Number of days after the absence date during which a student can submit a justification
JUSTIFICATION_DEADLINE_DAYS = 3


def get_justification_deadline(absence):
    """
    Returns the deadline (date) by which the student must submit a justification.
    deadline = absence_date + JUSTIFICATION_DEADLINE_DAYS days (end of that day).
    """
    return absence.id_seance.date_seance + datetime.timedelta(
        days=JUSTIFICATION_DEADLINE_DAYS
    )


def is_justification_expired(absence):
    """
    Returns True if the justification deadline has passed for this absence.
    The student has until the end of the deadline day (inclusive).
    """
    deadline = get_justification_deadline(absence)
    today = timezone.localdate()
    return today > deadline


def calculer_absence_stats(inscription):
    """
    Calcule les statistiques d'absence pour une inscription.

    Retourne:
        dict: {
            'total_absence': float,
            'taux': float,
            'total_periodes': int,
        }
    """
    # CORRECTION BUG CRITIQUE #3 — EN_ATTENTE compte comme NON_JUSTIFIEE
    # Un étudiant soumettant un justificatif non validé ne doit pas voir son taux
    # d'absence baisser. L'absence est décomptée UNIQUEMENT après acceptation
    # (state=ACCEPTEE → statut=JUSTIFIEE). Jusqu'alors, EN_ATTENTE = non justifiée.
    total_absence = float(
        Absence.objects.filter(
            id_inscription=inscription, statut__in=[Absence.Statut.NON_JUSTIFIEE, Absence.Statut.EN_ATTENTE]
        ).aggregate(total=Sum("duree_absence"))["total"]
        or 0
    )

    total_periodes = inscription.id_cours.nombre_total_periodes or 0
    taux = (total_absence / total_periodes) * 100 if total_periodes else 0

    return {
        "total_absence": total_absence,
        "taux": taux,
        "total_periodes": total_periodes,
    }


def get_absences_queryset(inscription):
    """
    Retourne un queryset optimisé pour afficher les absences d'une inscription.
    Évite les N+1 via select_related/prefetch_related.
    """
    return (
        Absence.objects.filter(id_inscription=inscription)
        .select_related("id_seance", "id_seance__id_cours", "justification")
        .order_by("-id_seance__date_seance")
    )


def recalculer_eligibilite(inscription):
    """
    Recalcule l'éligibilité d'un étudiant à l'examen basé sur ses absences non justifiées.

    IMPORTANT POUR LA SOUTENANCE :
    Cette fonction implémente la règle métier du seuil d'absence :
    - Un étudiant est bloqué (non éligible) si son taux d'absence >= seuil (40% par défaut)
    - Exception : si l'étudiant a une exemption (exemption_40 = True)
    - Le calcul se base UNIQUEMENT sur les absences NON JUSTIFIÉES

    Logique métier :
    1. Calculer le total des heures d'absences NON JUSTIFIÉES
    2. Calculer le taux : (heures absences / total périodes) * 100
    3. Comparer avec le seuil (personnalisé par cours ou défaut système)
    4. Si taux >= seuil ET pas d'exemption :
       - Bloquer l'étudiant (eligible_examen = False)
       - Envoyer une notification
       - Logger dans l'audit
    5. Sinon :
       - Débloquer l'étudiant si nécessaire (eligible_examen = True)
       - Envoyer une notification de déblocage

    Appel automatique :
    - Cette fonction est appelée automatiquement via un signal Django
    - Signal : post_save sur le modèle Absence
    - Garantit la cohérence des données après chaque modification d'absence

    Args:
        inscription: Instance de Inscription à recalculer

    Returns:
        None (modifie directement l'objet inscription)
    """
    stats = calculer_absence_stats(inscription)
    total_absence = stats["total_absence"]
    taux = stats["taux"]
    total_periodes = stats["total_periodes"]

    cours = inscription.id_cours

    # Vérifier que le cours a des périodes
    if total_periodes == 0:
        # Si pas de périodes, l'étudiant est éligible
        if not inscription.eligible_examen:
            inscription.eligible_examen = True
            inscription.save(update_fields=["eligible_examen"])
        return

    # Utiliser le seuil du cours (ou le seuil par défaut)
    seuil = cours.get_seuil_absence()

    # 2. Logique de blocage / déblocage
    if taux >= seuil and not inscription.exemption_40:
        # Étudiant dépasse le seuil et n'a pas d'exemption
        if inscription.eligible_examen:
            with transaction.atomic():
                inscription.eligible_examen = False
                inscription.save(update_fields=["eligible_examen"])

                # Notification à l'étudiant
                Notification.objects.create(
                    id_utilisateur=inscription.id_etudiant,
                    message=f"ALERTE : Seuil de {seuil}% dépassé pour {cours.nom_cours}. Examen bloqué.",
                    type="ALERTE",
                )

                # Email to student + professor (deferred after commit)
                student = inscription.id_etudiant
                professor = cours.professeur
                course_name = cours.nom_cours
                transaction.on_commit(lambda: _send_threshold_emails(
                    student, professor, course_name, taux, seuil
                ))

                # Log d'Audit
                LogAudit.objects.create(
                    id_utilisateur=inscription.id_etudiant,
                    action=f"CRITIQUE: Blocage automatique examen - {cours.nom_cours} (Taux: {taux:.1f}%, Seuil: {seuil}%)",
                    # CORRECTION BUG CRITIQUE #5 — IP système (action automatique, pas d'utilisateur connecté)
                    # "0.0.0.0" est la convention pour les actions système automatiques dans ce projet.
                    adresse_ip="0.0.0.0",  # nosec B104
                    niveau="CRITIQUE",
                    objet_type="INSCRIPTION",
                    objet_id=inscription.id_inscription,
                )
    else:
        # Étudiant est sous le seuil ou a une exemption
        if not inscription.eligible_examen:
            with transaction.atomic():
                inscription.eligible_examen = True
                inscription.save(update_fields=["eligible_examen"])

                # Notification de déblocage
                Notification.objects.create(
                    id_utilisateur=inscription.id_etudiant,
                    message=f"Information : Vous êtes à nouveau éligible à l'examen pour {cours.nom_cours}.",
                    type="INFO",
                )

                # Email to student (deferred after commit)
                student = inscription.id_etudiant
                course_name = cours.nom_cours
                transaction.on_commit(lambda: send_notification_email(
                    student, *build_eligibility_restored_email(student, course_name)
                ))


def _send_threshold_emails(student, professor, course_name, taux, seuil):
    """Send threshold-exceeded emails to student and professor. Never raises."""
    subj, body = build_threshold_exceeded_email(student, course_name, taux, seuil)
    send_notification_email(student, subj, body)
    if professor:
        subj, body = build_threshold_exceeded_professor_email(
            professor, student, course_name, taux, seuil
        )
        send_notification_email(professor, subj, body)


def get_system_threshold():
    """
    FIX VERT #15 — Récupère le seuil d'absence par défaut du système en une seule requête.
    Centralisé ici pour éviter de répéter l'import et l'appel dans chaque vue.
    """
    from apps.dashboard.models import SystemSettings

    return SystemSettings.get_settings().default_absence_threshold


def calculer_risque_inscription(inscription, system_threshold=None):
    """
    FIX VERT #15 — Calcul centralisé du statut de risque d'une inscription.

    Avant : logique dupliquée dans 8+ vues (student_dashboard, secretary_rules_40,
    instructor_courses, etc.), chacune réimplémentant le même calcul parfois de façon
    incohérente (seuil hardcodé 40% avant les corrections critiques).

    Après : source unique de vérité pour le calcul de risque.

    Args:
        inscription: Instance d'Inscription (doit avoir id_cours chargé)
        system_threshold: Seuil système pré-chargé (optionnel, évite N appels DB en boucle)

    Returns:
        dict: {
            'is_at_risk': bool,
            'is_blocked': bool,      # Bloqué = à risque ET pas exempté
            'taux': float,           # Taux d'absence en %
            'seuil': int,            # Seuil applicable (cours ou système)
            'total_absence': float,  # Heures d'absence comptabilisées
            'total_periodes': int,   # Total périodes du cours
        }
    """
    if system_threshold is None:
        system_threshold = get_system_threshold()

    cours = inscription.id_cours
    # Seuil personnalisé du cours, ou seuil système par défaut
    seuil = cours.seuil_absence if cours.seuil_absence is not None else system_threshold

    stats = calculer_absence_stats(inscription)
    taux = stats["taux"]
    is_at_risk = taux >= seuil
    is_blocked = is_at_risk and not inscription.exemption_40

    return {
        "is_at_risk": is_at_risk,
        "is_blocked": is_blocked,
        "taux": round(taux, 1),
        "seuil": seuil,
        "total_absence": stats["total_absence"],
        "total_periodes": stats["total_periodes"],
    }


def get_at_risk_count_for_queryset(inscriptions_qs, system_threshold=None):
    """
    FIX VERT #15 — Compte les inscriptions à risque dans un queryset.

    Optimisé pour les vues dashboard : pré-charge le seuil système une seule fois,
    et effectue la sommation des absences en une seule requête SQL agrégée.

    Args:
        inscriptions_qs: QuerySet d'Inscription filtré (doit inclure select_related id_cours)
        system_threshold: Seuil système pré-chargé (optionnel)

    Returns:
        tuple: (at_risk_count: int, absence_sums: dict {id_inscription: total_heures})
    """
    if system_threshold is None:
        system_threshold = get_system_threshold()

    inscription_ids = list(inscriptions_qs.values_list("id_inscription", flat=True))
    if not inscription_ids:
        return 0, {}

    # Agrégation SQL unique pour toutes les absences (EN_ATTENTE + NON_JUSTIFIEE)
    absence_sums = dict(
        Absence.objects.filter(
            id_inscription__in=inscription_ids,
            statut__in=[
                Absence.Statut.NON_JUSTIFIEE,
                Absence.Statut.EN_ATTENTE,
            ],  # EN_ATTENTE compte (loophole fermé)
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
        seuil = (
            cours.seuil_absence if cours.seuil_absence is not None else system_threshold
        )
        total_abs = absence_sums.get(ins.id_inscription, 0) or 0
        taux = (total_abs / cours.nombre_total_periodes) * 100
        if taux >= seuil and not ins.exemption_40:
            at_risk_count += 1

    return at_risk_count, absence_sums


# ========== PREDICTIVE ABSENCE DETECTION ==========

# Risk levels
RISK_HIGH = "HIGH"
RISK_MEDIUM = "MEDIUM"
RISK_LOW = "LOW"
RISK_NONE = "NONE"


def predict_absence_risk(inscriptions, academic_year=None, system_threshold=None):
    """
    Predictive absence detection — flags students trending toward the threshold
    BEFORE they actually reach it.

    Algorithm:
    1. For each inscription, compute:
       a) Current overall absence rate (total non-justified hours / total periods)
       b) Recent 30-day absence rate (hours in last 30 days / sessions in last 30 days)
       c) Course average absence rate (mean across all students in the course)
    2. Project end-of-term rate using linear extrapolation:
       - sessions_remaining = total_periods - sessions_elapsed_hours
       - projected_rate = current_hours + (recent_daily_rate * days_remaining) / total_periods
    3. Classify risk:
       - HIGH:   projected_rate >= threshold OR current_rate >= 75% of threshold
       - MEDIUM: projected_rate >= 75% of threshold OR recent_rate > 2x course_average
       - LOW:    projected_rate >= 50% of threshold AND recent_rate > course_average
       - NONE:   otherwise

    Args:
        inscriptions: list of Inscription objects (must have id_cours loaded)
        academic_year: AnneeAcademique instance (for session date range)
        system_threshold: pre-loaded system threshold (avoids repeated DB calls)

    Returns:
        list of dicts: [{
            'inscription': Inscription,
            'risk_level': 'HIGH'|'MEDIUM'|'LOW'|'NONE',
            'current_rate': float,
            'recent_rate': float,        # 30-day absence rate
            'projected_rate': float,     # end-of-term projection
            'course_avg_rate': float,
            'seuil': int,
            'total_abs': float,
            'recent_abs': float,         # hours in last 30 days
            'days_remaining': int,       # estimated days left in term
        }]
    """
    if system_threshold is None:
        system_threshold = get_system_threshold()

    if not inscriptions:
        return []

    today = timezone.localdate()
    thirty_days_ago = today - datetime.timedelta(days=30)
    sixty_days_ago = today - datetime.timedelta(days=60)

    inscription_ids = [ins.id_inscription for ins in inscriptions]

    _non_justified = [Absence.Statut.NON_JUSTIFIEE, Absence.Statut.EN_ATTENTE]

    # 1. Total non-justified absences per inscription (single SQL query)
    total_abs_map = dict(
        Absence.objects.filter(
            id_inscription__in=inscription_ids,
            statut__in=_non_justified,
        )
        .values("id_inscription")
        .annotate(total=Sum("duree_absence"))
        .values_list("id_inscription", "total")
    )

    # 2. Recent 30-day absences per inscription (single SQL query)
    recent_abs_map = dict(
        Absence.objects.filter(
            id_inscription__in=inscription_ids,
            statut__in=_non_justified,
            id_seance__date_seance__gte=thirty_days_ago,
        )
        .values("id_inscription")
        .annotate(total=Sum("duree_absence"))
        .values_list("id_inscription", "total")
    )

    # 3. Previous 30-day absences (days 31–60) for trend comparison
    prev_abs_map = dict(
        Absence.objects.filter(
            id_inscription__in=inscription_ids,
            statut__in=_non_justified,
            id_seance__date_seance__gte=sixty_days_ago,
            id_seance__date_seance__lt=thirty_days_ago,
        )
        .values("id_inscription")
        .annotate(total=Sum("duree_absence"))
        .values_list("id_inscription", "total")
    )

    # 3. Compute course-level averages (group inscriptions by course)
    from collections import defaultdict
    course_inscriptions = defaultdict(list)
    for ins in inscriptions:
        course_inscriptions[ins.id_cours_id].append(ins)

    course_avg_map = {}  # course_id -> average rate
    for course_id, course_ins_list in course_inscriptions.items():
        cours = course_ins_list[0].id_cours
        if not cours.nombre_total_periodes:
            course_avg_map[course_id] = 0.0
            continue
        rates = []
        for ins in course_ins_list:
            t = float(total_abs_map.get(ins.id_inscription, 0) or 0)
            rates.append((t / cours.nombre_total_periodes) * 100)
        course_avg_map[course_id] = sum(rates) / len(rates) if rates else 0.0

    # 4. Estimate days remaining in the academic year
    from apps.academic_sessions.models import Seance
    if academic_year:
        # Use the latest session date as a proxy for term end
        last_session = (
            Seance.objects.filter(id_annee=academic_year)
            .order_by("-date_seance")
            .values_list("date_seance", flat=True)
            .first()
        )
        first_session = (
            Seance.objects.filter(id_annee=academic_year)
            .order_by("date_seance")
            .values_list("date_seance", flat=True)
            .first()
        )
        if last_session and last_session > today:
            days_remaining = (last_session - today).days
        else:
            # If all sessions are in the past, no projection needed
            days_remaining = 0
        term_days = (last_session - first_session).days if (last_session and first_session) else 1
    else:
        days_remaining = 0
        term_days = 1

    # 5. Build predictions
    results = []
    for ins in inscriptions:
        cours = ins.id_cours
        total_periodes = cours.nombre_total_periodes or 0
        if total_periodes == 0:
            results.append({
                "inscription": ins,
                "risk_level": RISK_NONE,
                "current_rate": 0.0,
                "recent_rate": 0.0,
                "projected_rate": 0.0,
                "course_avg_rate": 0.0,
                "seuil": system_threshold,
                "total_abs": 0.0,
                "recent_abs": 0.0,
                "days_remaining": days_remaining,
            })
            continue

        seuil = (
            cours.seuil_absence if cours.seuil_absence is not None else system_threshold
        )

        total_abs = float(total_abs_map.get(ins.id_inscription, 0) or 0)
        recent_abs = float(recent_abs_map.get(ins.id_inscription, 0) or 0)
        prev_abs = float(prev_abs_map.get(ins.id_inscription, 0) or 0)
        course_avg = course_avg_map.get(ins.id_cours_id, 0.0)

        current_rate = (total_abs / total_periodes) * 100

        # Recent rate: hours per day over last 30 days
        window_days = min(30, max((today - first_session).days, 1)) if first_session else 30
        recent_daily_rate = recent_abs / window_days if window_days > 0 else 0

        # Project: current hours + (daily rate * remaining days)
        projected_hours = total_abs + (recent_daily_rate * days_remaining)
        projected_rate = (projected_hours / total_periodes) * 100 if days_remaining > 0 else current_rate

        # Recent 30-day rate as percentage (for comparison with course average)
        # Normalize to: what % of total_periodes did they miss in 30 days, annualized
        recent_rate = (recent_abs / total_periodes) * 100

        # Trend: compare recent 30 days vs previous 30 days
        # "up" = getting worse, "down" = improving, "stable" = ±10% tolerance
        if prev_abs > 0:
            change_ratio = (recent_abs - prev_abs) / prev_abs
            if change_ratio > 0.10:
                trend = "up"
            elif change_ratio < -0.10:
                trend = "down"
            else:
                trend = "stable"
        elif recent_abs > 0:
            trend = "up"  # went from 0 to something
        else:
            trend = "stable"

        # Already blocked — skip prediction
        if current_rate >= seuil and not ins.exemption_40:
            risk_level = RISK_HIGH
        elif ins.exemption_40:
            risk_level = RISK_NONE
        # Classification
        elif projected_rate >= seuil or current_rate >= seuil * 0.75:
            risk_level = RISK_HIGH
        elif projected_rate >= seuil * 0.75 or (
            course_avg > 0 and recent_rate > course_avg * 2
        ):
            risk_level = RISK_MEDIUM
        elif projected_rate >= seuil * 0.50 and (
            course_avg > 0 and recent_rate > course_avg
        ):
            risk_level = RISK_LOW
        else:
            risk_level = RISK_NONE

        results.append({
            "inscription": ins,
            "risk_level": risk_level,
            "current_rate": round(current_rate, 1),
            "recent_rate": round(recent_rate, 1),
            "projected_rate": round(min(projected_rate, 100.0), 1),
            "course_avg_rate": round(course_avg, 1),
            "seuil": seuil,
            "total_abs": total_abs,
            "recent_abs": recent_abs,
            "days_remaining": days_remaining,
            "trend": trend,
        })

    return results
