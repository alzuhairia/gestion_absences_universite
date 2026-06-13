"""
Service prédictif de détection des risques — apps/absences/services/prediction_service.py

Fait partie du système universitaire de gestion des présences UniAbsences.

Ce module projette le taux d'absence de fin de semestre d'un étudiant à
l'aide d'une extrapolation linéaire à partir des données d'absence courantes
et classe le résultat dans l'un des quatre niveaux de risque
(HIGH / MEDIUM / LOW / NONE).

Algorithme
----------
1. Calcule le taux d'absence courant à partir des séances passées (NON_JUSTIFIEE uniquement).
2. Calcule le taux de tendance récente des 30 derniers jours.
3. Extrapole jusqu'à la fin du semestre via une interpolation linéaire en
   utilisant le ratio heures écoulées / heures totales de séances.
4. Compare le taux projeté à 75 % et 50 % du seuil effectif (seuil du cours +
   marge d'exemption le cas échéant) pour attribuer un risque HIGH, MEDIUM,
   LOW ou NONE.
"""
import datetime
import logging
from collections import defaultdict

from django.db.models import Sum
from django.utils import timezone

from ..models import Absence
from .eligibility_service import get_system_threshold

logger = logging.getLogger(__name__)

# Constantes de niveau de risque prédictif — retournées dans chaque dict de résultat.
# Les appelants doivent comparer à ces constantes, pas à des chaînes brutes.
RISK_HIGH = "HIGH"
RISK_MEDIUM = "MEDIUM"
RISK_LOW = "LOW"
RISK_NONE = "NONE"


def predict_absence_risk(inscriptions, academic_year=None, system_threshold=None):
    """
    Effectue la détection prédictive de risque pour une collection d'inscriptions.

    Pour chaque inscription, cette fonction :
      1. Calcule le taux d'absence non justifiée courant de l'étudiant.
      2. Calcule un taux récent sur 30 jours et un taux des 30 jours précédents
         pour déterminer la tendance d'absence (en hausse / stable / en baisse).
      3. Extrapole linéairement le taux projeté à la fin du semestre en
         multipliant la cadence journalière récente d'absence par les jours
         restants.
      4. Classe l'inscription dans l'un des quatre niveaux de risque en
         comparant à la fois le taux courant et le taux projeté à des
         fractions du seuil effectif (75 % et 50 % déclenchent respectivement
         MEDIUM / LOW).

    Toutes les requêtes d'absence sont regroupées en trois requêtes
    d'agrégation en amont (total, 30 derniers jours, 30 jours précédents)
    pour éviter les motifs N+1.

    Args :
        inscriptions (list[Inscription]) : inscriptions à évaluer. Le champ
            ``id_cours`` relié doit déjà être chargé.
        academic_year (AnneeAcademique | None) : instance d'année académique
            utilisée pour déterminer la plage de dates du semestre (premières
            et dernières dates de séance). Si None, ``days_remaining`` est
            mis à 0 et le taux projeté est égal au taux courant.
        system_threshold (int | float | None) : seuil d'absence par défaut au
            niveau système pré-chargé. Si None, il est récupéré via
            ``get_system_threshold()``.

    Retour :
        list[dict] : un dict par inscription, ordonnés comme la liste d'entrée.
        Chaque dict contient :

        - ``inscription`` : l'instance ``Inscription``.
        - ``risk_level`` (str) : l'une des valeurs ``RISK_HIGH``, ``RISK_MEDIUM``,
          ``RISK_LOW`` ou ``RISK_NONE``.
        - ``current_rate`` (float) : taux courant d'absence non justifiée (0-100).
        - ``recent_rate`` (float) : taux d'absence cumulé sur les 30 derniers jours.
        - ``projected_rate`` (float) : taux projeté extrapolé linéairement en fin de semestre.
        - ``course_avg_rate`` (float) : taux d'absence moyen de tous les étudiants
          inscrits au même cours (utilisé comme référence de comparaison).
        - ``seuil`` (int | float) : seuil de base du cours (avant exemption).
        - ``total_abs`` (float) : total des heures d'absence non justifiée à ce jour.
        - ``recent_abs`` (float) : heures d'absence non justifiée des 30 derniers jours.
        - ``days_remaining`` (int) : jours calendaires jusqu'à la dernière séance.
        - ``trend`` (str) : ``"up"``, ``"down"`` ou ``"stable"`` selon le changement
          des heures d'absence entre la fenêtre précédente et la fenêtre courante de 30 jours.
    """
    if system_threshold is None:
        system_threshold = get_system_threshold()

    if not inscriptions:
        return []

    today = timezone.localdate()
    thirty_days_ago = today - datetime.timedelta(days=30)
    sixty_days_ago = today - datetime.timedelta(days=60)

    inscription_ids = [ins.id_inscription for ins in inscriptions]
    # Utilise une liste afin que le filtre emploie __in plutôt qu'une correspondance exacte.
    _non_justified = [Absence.Statut.NON_JUSTIFIEE]

    # --- Requête en lot 1 : total des heures d'absence non justifiée jusqu'à aujourd'hui ---
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

    # --- Requête en lot 2 : fenêtre récente (30 derniers jours) d'heures d'absence ---
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

    # --- Requête en lot 3 : fenêtre précédente (30 à 60 jours en arrière) pour le calcul de tendance ---
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

    # Calcule le taux moyen d'absence par cours pour servir de référence de comparaison.
    # Les étudiants dont le taux récent dépasse nettement la moyenne du cours sont
    # signalés en risque MEDIUM même si leur taux projeté est sous 75 % du seuil.
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

    # Détermine les bornes temporelles du semestre à partir des séances réellement enregistrées.
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
        # days_remaining vaut 0 quand la dernière séance est aujourd'hui ou dans le passé.
        days_remaining = (last_session - today).days if last_session and last_session > today else 0
    else:
        # Aucune année académique fournie — la projection est désactivée.
        last_session = first_session = None
        days_remaining = 0

    results = []
    for ins in inscriptions:
        cours = ins.id_cours
        total_periodes = cours.nombre_total_periodes or 0

        # Aucune heure planifiée — le risque ne peut pas être calculé ; émet un résultat NONE sûr.
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

        # Seuil effectif : ajoute la marge d'exemption pour les étudiants exemptés.
        seuil = cours.seuil_absence if cours.seuil_absence is not None else system_threshold
        seuil_effectif = min(seuil + ins.exemption_margin, 100) if ins.exemption_40 else seuil

        total_abs = float(total_abs_map.get(ins.id_inscription, 0) or 0)
        recent_abs = float(recent_abs_map.get(ins.id_inscription, 0) or 0)
        prev_abs = float(prev_abs_map.get(ins.id_inscription, 0) or 0)
        course_avg = course_avg_map.get(ins.id_cours_id, 0.0)

        current_rate = min((total_abs / total_periodes) * 100, 100)

        # Calcule combien de jours se sont écoulés depuis la première séance pour normaliser
        # la taille de la fenêtre récente (évite des taux artificiellement élevés en début de semestre).
        window_days = min(30, max((today - first_session).days, 1)) if first_session else 30
        recent_daily_rate = recent_abs / window_days if window_days > 0 else 0

        # Extrapolation linéaire : projette les heures d'absence jusqu'à la fin du semestre.
        projected_hours = total_abs + (recent_daily_rate * days_remaining)
        projected_rate = (projected_hours / total_periodes) * 100 if days_remaining > 0 else current_rate
        recent_rate = min((recent_abs / total_periodes) * 100, 100)

        # Tendance : compare la fenêtre récente de 30 jours à la fenêtre précédente de 30 jours.
        # Une hausse relative > 10 % est signalée comme "up" ; une baisse > 10 % comme "down".
        if prev_abs > 0:
            change_ratio = (recent_abs - prev_abs) / prev_abs
            trend = "up" if change_ratio > 0.10 else ("down" if change_ratio < -0.10 else "stable")
        elif recent_abs > 0:
            # Aucune donnée pour la fenêtre précédente mais les absences s'accumulent — tendance à la hausse.
            trend = "up"
        else:
            trend = "stable"

        # --- Classification du risque ---
        # HIGH :   déjà au seuil ou au-dessus, OU projection au-dessus du seuil,
        #          OU déjà à 75 % du seuil (dépassement imminent).
        # MEDIUM : projection à 75 % du seuil, OU taux récent plus que double
        #          de la moyenne du cours (comportement atypique).
        # LOW :    projection à 50 % du seuil ET taux supérieur à la moyenne du cours.
        # NONE :   aucune des conditions ci-dessus n'est remplie.
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
