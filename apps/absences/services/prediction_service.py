"""
Service : Détection prédictive des absences à risque.

Responsabilité : projeter le taux d'absence en fin de semestre et
classifier chaque étudiant selon son niveau de risque (HIGH/MEDIUM/LOW/NONE).

Algorithme :
  1. Calculer le taux d'absence actuel et récent (30 jours)
  2. Projeter le taux en fin de semestre via extrapolation linéaire
  3. Comparer à 75%/50% du seuil effectif pour classifier le risque
"""
import datetime
import logging
from collections import defaultdict

from django.db.models import Sum
from django.utils import timezone

from ..models import Absence
from .eligibility_service import get_system_threshold

logger = logging.getLogger(__name__)

# Niveaux de risque prédictif
RISK_HIGH = "HIGH"
RISK_MEDIUM = "MEDIUM"
RISK_LOW = "LOW"
RISK_NONE = "NONE"


def predict_absence_risk(inscriptions, academic_year=None, system_threshold=None):
    """
    Détection prédictive — signale les étudiants qui tendent vers le seuil
    AVANT de l'atteindre.

    Args:
        inscriptions: liste d'Inscription (id_cours doit être chargé)
        academic_year: AnneeAcademique pour la plage de dates du semestre
        system_threshold: seuil système pré-chargé

    Returns:
        list of dicts: [{
            'inscription', 'risk_level', 'current_rate', 'recent_rate',
            'projected_rate', 'course_avg_rate', 'seuil', 'total_abs',
            'recent_abs', 'days_remaining', 'trend'
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

    # Moyenne d'absence par cours
    course_inscriptions = defaultdict(list)
    for ins in inscriptions:
        course_inscriptions[ins.id_cours_id].append(ins)

    course_avg_map = {}
    for course_id, course_ins_list in course_inscriptions.items():
        cours = course_ins_list[0].id_cours
        if not cours.nombre_total_periodes:
            course_avg_map[course_id] = 0.0
            continue
        rates = [
            min((float(total_abs_map.get(ins.id_inscription, 0) or 0) / cours.nombre_total_periodes) * 100, 100)
            for ins in course_ins_list
        ]
        course_avg_map[course_id] = sum(rates) / len(rates) if rates else 0.0

    # Estimation des jours restants dans l'année académique
    from apps.academic_sessions.models import Seance
    if academic_year:
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
        days_remaining = (last_session - today).days if last_session and last_session > today else 0
    else:
        last_session = first_session = None
        days_remaining = 0

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

        seuil = cours.seuil_absence if cours.seuil_absence is not None else system_threshold
        seuil_effectif = min(seuil + ins.exemption_margin, 100) if ins.exemption_40 else seuil

        total_abs = float(total_abs_map.get(ins.id_inscription, 0) or 0)
        recent_abs = float(recent_abs_map.get(ins.id_inscription, 0) or 0)
        prev_abs = float(prev_abs_map.get(ins.id_inscription, 0) or 0)
        course_avg = course_avg_map.get(ins.id_cours_id, 0.0)

        current_rate = min((total_abs / total_periodes) * 100, 100)

        window_days = min(30, max((today - first_session).days, 1)) if first_session else 30
        recent_daily_rate = recent_abs / window_days if window_days > 0 else 0

        projected_hours = total_abs + (recent_daily_rate * days_remaining)
        projected_rate = (projected_hours / total_periodes) * 100 if days_remaining > 0 else current_rate
        recent_rate = min((recent_abs / total_periodes) * 100, 100)

        if prev_abs > 0:
            change_ratio = (recent_abs - prev_abs) / prev_abs
            trend = "up" if change_ratio > 0.10 else ("down" if change_ratio < -0.10 else "stable")
        elif recent_abs > 0:
            trend = "up"
        else:
            trend = "stable"

        # Classification du risque
        if current_rate >= seuil_effectif:
            risk_level = RISK_HIGH
        elif projected_rate >= seuil_effectif or current_rate >= seuil_effectif * 0.75:
            risk_level = RISK_HIGH
        elif projected_rate >= seuil_effectif * 0.75 or (course_avg > 0 and recent_rate > course_avg * 2):
            risk_level = RISK_MEDIUM
        elif projected_rate >= seuil_effectif * 0.50 and (course_avg > 0 and recent_rate > course_avg):
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
