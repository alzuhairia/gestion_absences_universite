"""
Service : Calcul de statistiques d'absences.

Responsabilité : calculer les taux d'absence, construire les requêtes
optimisées et détecter les étudiants en alerte pour un cours donné.
"""
import logging

from django.db.models import DurationField, ExpressionWrapper, F, Sum
from django.utils import timezone

from ..models import Absence

logger = logging.getLogger(__name__)


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


def calculer_pourcentage_absence(etudiant, cours):
    """
    Calcule le pourcentage d'absence d'un étudiant pour un cours donné,
    basé sur les heures réelles (somme des durées de séances passées).

    Design :
    - Pas de record Absence = étudiant PRÉSENT
    - Seules les absences NON_JUSTIFIEE comptent (EN_ATTENTE ne pénalise pas)
    - Seules les séances passées (date <= aujourd'hui) sont comptabilisées

    Returns:
        dict: {
            'total_heures_cours': float,
            'total_heures_absence': float,
            'pourcentage_absence': float,
            'pourcentage_presence': float,
        }
    """
    from apps.academic_sessions.models import Seance
    from apps.enrollments.models import Inscription

    today = timezone.localdate()

    # Total des heures de cours = somme des durées des séances PASSÉES
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
    total_heures_cours = round(raw.total_seconds() / 3600.0, 2) if raw else 0.0

    if total_heures_cours == 0:
        return {
            "total_heures_cours": 0.0,
            "total_heures_absence": 0.0,
            "pourcentage_absence": 0.0,
            "pourcentage_presence": 0.0,
        }

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


def etudiants_en_alerte(cours, seuil=None):
    """
    Retourne la liste des étudiants dont le pourcentage d'absence
    dépasse le seuil pour un cours donné.

    Returns:
        list of dict: [{
            'etudiant', 'inscription', 'pourcentage_absence',
            'total_heures_absence', 'total_heures_cours', 'depasse_seuil'
        }]
    """
    from apps.academic_sessions.models import Seance
    from apps.enrollments.models import Inscription

    if seuil is None:
        seuil = cours.get_seuil_absence() if hasattr(cours, "get_seuil_absence") else 20

    today = timezone.localdate()

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
    total_heures_cours = round(raw.total_seconds() / 3600.0, 2) if raw else 0.0

    if total_heures_cours == 0:
        return []

    inscriptions = Inscription.objects.filter(
        id_cours=cours,
        status=Inscription.Status.EN_COURS,
    ).select_related("id_etudiant")

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

    alertes.sort(key=lambda x: x["pourcentage_absence"], reverse=True)
    return alertes
