"""
FICHIER : apps/absences/services.py
RESPONSABILITE : Logique metier centrale de la gestion des absences
FONCTIONNALITES PRINCIPALES :
  - Calcul de statistiques d'absences (taux, heures, periodes)
  - Calcul du pourcentage d'absence base sur les heures reelles
  - Detection des etudiants en alerte (depassement seuil)
  - Recalcul automatique de l'eligibilite examen (coeur du systeme)
  - Calcul de risque centralise pour les dashboards
  - Detection predictive d'absences (projection fin de semestre)
DEPENDANCES CLES : absences.models, enrollments.Inscription, notifications.email
"""

import datetime
import logging

from django.db import transaction
from django.db.models import DurationField, ExpressionWrapper, F, Sum
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

logger = logging.getLogger(__name__)

# Nombre de jours apres la date d'absence pour soumettre une justification
JUSTIFICATION_DEADLINE_DAYS = 3


# ========================================================================== #
#                     DELAIS DE JUSTIFICATION                                #
# ========================================================================== #


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


# ========================================================================== #
#                     STATISTIQUES D'ABSENCES                                #
# ========================================================================== #


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
    # Seules les absences NON_JUSTIFIEE pour des séances passées comptent.
    # EN_ATTENTE = justificatif soumis, ne doit pas pénaliser l'étudiant.
    # Séances futures exclues pour ne pas fausser le taux.
    today = timezone.localdate()
    total_absence = float(
        Absence.objects.filter(
            id_inscription=inscription,
            statut=Absence.Statut.NON_JUSTIFIEE,
            id_seance__date_seance__lte=today,
        ).aggregate(total=Sum("duree_absence"))["total"]
        or 0
    )

    total_periodes = inscription.id_cours.nombre_total_periodes or 0
    taux = min((total_absence / total_periodes) * 100, 100) if total_periodes else 0

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


# ========================================================================== #
#              POURCENTAGE D'ABSENCE (HEURES REELLES)                        #
# ========================================================================== #


def calculer_pourcentage_absence(etudiant, cours):
    """
    Calcule le pourcentage d'absence d'un étudiant pour un cours donné,
    basé sur les heures réelles (somme des durées de séances passées et durées d'absence).

    Design :
    - Pas de record Absence = étudiant PRÉSENT (absence inexistante = présence)
    - ABSENT = absence complète (durée = durée séance)
    - PARTIEL = toute absence non complète (retard, départ anticipé, etc.)
    - Seules les séances passées (date <= aujourd'hui) sont comptabilisées

    Args:
        etudiant: Instance User (role=ETUDIANT)
        cours: Instance Cours

    Returns:
        dict: {
            'total_heures_cours': float,   # Somme durées des séances passées du cours
            'total_heures_absence': float, # Somme duree_absence (non justifiées uniquement)
            'pourcentage_absence': float,  # (heures_absence / heures_cours) * 100
            'pourcentage_presence': float, # 100 - pourcentage_absence
        }
    """
    from apps.academic_sessions.models import Seance
    from apps.enrollments.models import Inscription

    today = timezone.localdate()

    # Total des heures de cours = somme des durées des séances PASSÉES (une seule requête SQL)
    # DurationField car PostgreSQL renvoie un interval (timedelta) pour TimeField - TimeField.
    raw = Seance.objects.filter(
        id_cours=cours, date_seance__lte=today
    ).aggregate(
        total=Sum(
            ExpressionWrapper(
                F("heure_fin") - F("heure_debut"),
                output_field=DurationField(),
            )
        )
    )["total"]
    if raw is None:
        total_heures_cours = 0.0
    else:
        total_heures_cours = round(raw.total_seconds() / 3600.0, 2)

    # Protection division par zéro : aucune séance passée → 0%
    if total_heures_cours == 0:
        return {
            "total_heures_cours": 0.0,
            "total_heures_absence": 0.0,
            "pourcentage_absence": 0.0,
            "pourcentage_presence": 0.0,
        }

    # Trouver l'inscription active de l'étudiant pour ce cours
    inscription = Inscription.objects.filter(
        id_etudiant=etudiant,
        id_cours=cours,
        status=Inscription.Status.EN_COURS,
    ).first()

    if not inscription:
        return {
            "total_heures_cours": round(total_heures_cours, 2),
            "total_heures_absence": 0.0,
            "pourcentage_absence": 0.0,
            "pourcentage_presence": 100.0,
        }

    # Somme des durées d'absence NON_JUSTIFIEE uniquement
    # EN_ATTENTE ne pénalise pas l'étudiant (justificatif soumis)
    total_heures_absence = float(
        Absence.objects.filter(
            id_inscription=inscription,
            statut=Absence.Statut.NON_JUSTIFIEE,
            id_seance__date_seance__lte=today,
        ).aggregate(total=Sum("duree_absence"))["total"]
        or 0
    )

    pourcentage_absence = min(round((total_heures_absence / total_heures_cours) * 100, 2), 100)
    pourcentage_presence = round(100 - pourcentage_absence, 2)

    return {
        "total_heures_cours": round(total_heures_cours, 2),
        "total_heures_absence": round(total_heures_absence, 2),
        "pourcentage_absence": pourcentage_absence,
        "pourcentage_presence": pourcentage_presence,
    }


# ========================================================================== #
#                    ETUDIANTS EN ALERTE                                     #
# ========================================================================== #


def etudiants_en_alerte(cours, seuil=None):
    """
    Retourne la liste des étudiants dont le pourcentage d'absence
    dépasse le seuil pour un cours donné.

    Args:
        cours: Instance Cours
        seuil: Seuil en % (par défaut: seuil du cours ou 20%)

    Returns:
        list of dict: [{
            'etudiant': User,
            'inscription': Inscription,
            'pourcentage_absence': float,
            'total_heures_absence': float,
            'total_heures_cours': float,
            'depasse_seuil': bool,
        }]
    """
    from apps.academic_sessions.models import Seance
    from apps.enrollments.models import Inscription

    if seuil is None:
        seuil = cours.get_seuil_absence() if hasattr(cours, 'get_seuil_absence') else 20

    today = timezone.localdate()

    # Total des heures de cours (somme des séances PASSÉES — une seule requête SQL)
    raw = Seance.objects.filter(
        id_cours=cours, date_seance__lte=today
    ).aggregate(
        total=Sum(
            ExpressionWrapper(
                F("heure_fin") - F("heure_debut"),
                output_field=DurationField(),
            )
        )
    )["total"]
    if raw is None:
        total_heures_cours = 0.0
    else:
        total_heures_cours = round(raw.total_seconds() / 3600.0, 2)

    # Protection division par zéro : aucune séance passée → pas d'alerte
    if total_heures_cours == 0:
        return []

    # Inscriptions actives pour ce cours
    inscriptions = Inscription.objects.filter(
        id_cours=cours,
        status=Inscription.Status.EN_COURS,
    ).select_related("id_etudiant")

    # Agrégation des heures d'absence par inscription (séances passées, une seule requête SQL)
    absence_sums = dict(
        Absence.objects.filter(
            id_inscription__in=inscriptions,
            statut=Absence.Statut.NON_JUSTIFIEE,
            id_seance__date_seance__lte=today,
        )
        .values("id_inscription")
        .annotate(total=Sum("duree_absence"))
        .values_list("id_inscription", "total")
    )

    alertes = []
    for ins in inscriptions:
        total_abs = float(absence_sums.get(ins.id_inscription, 0) or 0)
        pourcentage = min(round((total_abs / total_heures_cours) * 100, 2), 100)

        if pourcentage >= seuil:
            alertes.append({
                "etudiant": ins.id_etudiant,
                "inscription": ins,
                "pourcentage_absence": pourcentage,
                "total_heures_absence": round(total_abs, 2),
                "total_heures_cours": round(total_heures_cours, 2),
                "depasse_seuil": True,
            })

    # Trier par pourcentage décroissant
    alertes.sort(key=lambda x: x["pourcentage_absence"], reverse=True)
    return alertes


# ========================================================================== #
#           RECALCUL D'ELIGIBILITE (FONCTION CRITIQUE)                       #
# ========================================================================== #


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

    # 2. Calcul du seuil effectif (avec marge d'exemption)
    #    - Sans exemption : seuil_effectif = seuil (ex: 40%)
    #    - Avec exemption : seuil_effectif = seuil + marge (ex: 40% + 10% = 50%)
    #    - Plafonné à 100%
    if inscription.exemption_40:
        seuil_effectif = min(seuil + inscription.exemption_margin, 100)
    else:
        seuil_effectif = seuil

    # 3. Logique de blocage / déblocage
    doit_bloquer = taux >= seuil_effectif

    if doit_bloquer:
        # Étudiant dépasse le seuil effectif → bloqué (même si exempté)
        if inscription.eligible_examen:
            with transaction.atomic():
                inscription.eligible_examen = False
                inscription.save(update_fields=["eligible_examen"])

                if inscription.exemption_40:
                    msg = (
                        f"ALERTE : Seuil d'exemption de {seuil_effectif}% dépassé pour {cours.nom_cours}. "
                        f"Examen bloqué malgré l'exemption."
                    )
                else:
                    msg = f"ALERTE : Seuil de {seuil}% dépassé pour {cours.nom_cours}. Examen bloqué."

                try:
                    Notification.objects.create(
                        id_utilisateur=inscription.id_etudiant,
                        message=msg,
                        type="ALERTE",
                    )
                except Exception:
                    logger.exception("Failed to create blocking notification for %s", cours.nom_cours)

                # Email to student + professor (deferred after commit)
                student = inscription.id_etudiant
                professor = cours.professeur
                course_name = cours.nom_cours
                transaction.on_commit(lambda: _send_threshold_emails(
                    student, professor, course_name, taux, seuil_effectif
                ))

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
        # Étudiant est sous le seuil effectif → éligible
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
    """Send threshold-exceeded emails to student and professor. Never raises."""
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


# ========================================================================== #
#                    SEUIL SYSTEME PAR DEFAUT                                #
# ========================================================================== #


def get_system_threshold():
    """
    FIX VERT #15 — Récupère le seuil d'absence par défaut du système en une seule requête.
    Centralisé ici pour éviter de répéter l'import et l'appel dans chaque vue.
    """
    from apps.dashboard.models import SystemSettings

    return SystemSettings.get_settings().default_absence_threshold


# ========================================================================== #
#              CALCUL DE RISQUE CENTRALISE                                   #
# ========================================================================== #


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

    # Seuil effectif avec marge d'exemption
    if inscription.exemption_40:
        seuil_effectif = min(seuil + inscription.exemption_margin, 100)
    else:
        seuil_effectif = seuil

    stats = calculer_absence_stats(inscription)
    taux = stats["taux"]

    is_at_risk = taux >= seuil  # dépasse le seuil normal
    is_blocked = taux >= seuil_effectif  # dépasse le seuil effectif (bloqué)
    is_under_exemption = inscription.exemption_40 and is_at_risk and not is_blocked

    return {
        "is_at_risk": is_at_risk,
        "is_blocked": is_blocked,
        "is_under_exemption": is_under_exemption,  # exempté, entre seuil et seuil+marge
        "taux": round(taux, 1),
        "seuil": seuil,
        "seuil_effectif": seuil_effectif,
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

    today = timezone.localdate()

    # Agrégation SQL unique — seules les NON_JUSTIFIEE pour séances passées comptent
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
        seuil = (
            cours.seuil_absence if cours.seuil_absence is not None else system_threshold
        )
        total_abs = absence_sums.get(ins.id_inscription, 0) or 0
        taux = min((total_abs / cours.nombre_total_periodes) * 100, 100)
        seuil_effectif = min(seuil + ins.exemption_margin, 100) if ins.exemption_40 else seuil
        if taux >= seuil_effectif:
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

    _non_justified = [Absence.Statut.NON_JUSTIFIEE]

    # 1. Total non-justified absences per inscription — past seances only
    total_abs_map = dict(
        Absence.objects.filter(
            id_inscription__in=inscription_ids,
            statut__in=_non_justified,
            id_seance__date_seance__lte=today,
        )
        .values("id_inscription")
        .annotate(total=Sum("duree_absence"))
        .values_list("id_inscription", "total")
    )

    # 2. Recent 30-day absences per inscription — past seances only
    recent_abs_map = dict(
        Absence.objects.filter(
            id_inscription__in=inscription_ids,
            statut__in=_non_justified,
            id_seance__date_seance__gte=thirty_days_ago,
            id_seance__date_seance__lte=today,
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
            rates.append(min((t / cours.nombre_total_periodes) * 100, 100))
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
        first_session = None

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

        current_rate = min((total_abs / total_periodes) * 100, 100)

        # Recent rate: hours per day over last 30 days
        window_days = min(30, max((today - first_session).days, 1)) if first_session else 30
        recent_daily_rate = recent_abs / window_days if window_days > 0 else 0

        # Project: current hours + (daily rate * remaining days)
        projected_hours = total_abs + (recent_daily_rate * days_remaining)
        projected_rate = (projected_hours / total_periodes) * 100 if days_remaining > 0 else current_rate

        # Recent 30-day rate as percentage (for comparison with course average)
        # Normalize to: what % of total_periodes did they miss in 30 days, annualized
        recent_rate = min((recent_abs / total_periodes) * 100, 100)

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
        seuil_effectif = min(seuil + ins.exemption_margin, 100) if ins.exemption_40 else seuil
        if current_rate >= seuil_effectif:
            risk_level = RISK_HIGH
        # Classification
        elif projected_rate >= seuil_effectif or current_rate >= seuil_effectif * 0.75:
            risk_level = RISK_HIGH
        elif projected_rate >= seuil_effectif * 0.75 or (
            course_avg > 0 and recent_rate > course_avg * 2
        ):
            risk_level = RISK_MEDIUM
        elif projected_rate >= seuil_effectif * 0.50 and (
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
