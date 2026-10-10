"""
Service de statistiques d'absences — apps/absences/services/absence_service.py

Fait partie du système universitaire de gestion des présences UniAbsences.

Ce module fournit la couche de calcul centrale pour les statistiques
d'absences. Il est la source unique de vérité pour calculer les heures
d'absence, les taux et la détection d'alerte pour une inscription à un cours.

Principales responsabilités :
  - ``calculer_absence_stats``      : calcule les stats brutes d'absence pour une inscription
  - ``get_absences_queryset``       : retourne un queryset anti-N+1 pour l'affichage des absences
  - ``calculer_pourcentage_absence``: calcule les pourcentages réels d'absence/présence basés sur les heures
  - ``etudiants_en_alerte``         : liste les étudiants dont le taux d'absence dépasse le seuil du cours

Règles métier appliquées ici :
  - Seules les absences NON_JUSTIFIEE comptent contre l'étudiant.
    EN_ATTENTE (justificatif soumis mais pas encore examiné) NE pénalise PAS.
  - Seules les séances passées (date <= aujourd'hui) sont comptées ; les séances futures sont exclues.
  - Taux d'absence = heures d'absence non justifiée / total des heures de cours planifiées.
"""
import logging
from typing import cast

from django.db.models import DurationField, ExpressionWrapper, F, Sum
from django.utils import timezone

from ..models import Absence

logger = logging.getLogger(__name__)


def calculer_absence_stats(inscription):
    """
    Calcule les statistiques d'absence pour une seule inscription à un cours.

    Seules les absences NON_JUSTIFIEE des séances passées (date <= aujourd'hui)
    sont incluses, afin qu'un justificatif en attente (EN_ATTENTE) ne pénalise
    pas l'étudiant avant que le secrétariat ne l'ait examiné.

    Args :
        inscription : instance ``apps.enrollments.models.Inscription`` dont le
            ``id_cours`` relié doit déjà être accessible.

    Retour :
        dict avec les clés suivantes :

        - ``total_absence`` (float) : total des heures d'absence non justifiée.
        - ``taux`` (float) : taux d'absence en pourcentage (0–100), plafonné à 100.
        - ``total_periodes`` (int) : total des heures de cours prévues (dénominateur).
    """
    # Seules les absences NON_JUSTIFIEE des séances PASSÉES comptent.
    # EN_ATTENTE = justificatif soumis, ne doit pas pénaliser l'étudiant
    # jusqu'à ce que le secrétariat prenne une décision.
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
    # Plafonné à 100 % pour éviter d'afficher des taux supérieurs à 100 dans les cas limites.
    taux = min((total_absence / total_periodes) * 100, 100) if total_periodes else 0

    return {
        "total_absence": total_absence,
        "taux": taux,
        "total_periodes": total_periodes,
    }


def get_absences_queryset(inscription):
    """
    Retourne un queryset optimisé de toutes les absences pour une inscription donnée.

    Utilise ``select_related`` pour éviter les requêtes N+1 lors de l'accès aux
    données de séance et de justification dans la couche template. Les résultats
    sont triés par séance la plus récente en premier.

    Args :
        inscription : instance ``apps.enrollments.models.Inscription``.

    Retour :
        ``QuerySet[Absence]`` : enregistrements d'absences triés par
        ``-id_seance__date_seance``.
    """
    return (
        Absence.objects.filter(id_inscription=inscription)
        .select_related("id_seance", "id_seance__id_cours", "justification")
        .order_by("-id_seance__date_seance")
    )


def calculer_pourcentage_absence(etudiant, cours):
    """
    Calcule les pourcentages réels d'absence et de présence basés sur les heures pour un étudiant donné dans un cours donné.

    Décisions de conception :
      - L'absence d'un enregistrement ``Absence`` signifie que l'étudiant était PRÉSENT
        (modèle d'absence par exception).
      - Seules les absences NON_JUSTIFIEE comptent (EN_ATTENTE ne pénalise pas).
      - Seules les séances passées (date <= aujourd'hui) sont comptées.
      - Si l'étudiant n'est pas activement inscrit, le taux de présence est de 100 %.

    Args :
        etudiant : instance ``apps.accounts.models.User`` (étudiant).
        cours : instance ``apps.academics.models.Cours``.

    Retour :
        dict avec les clés suivantes :

        - ``total_heures_cours`` (float) : total des heures des séances passées.
        - ``total_heures_absence`` (float) : total des heures d'absence non justifiée.
        - ``pourcentage_absence`` (float) : taux d'absence 0–100, arrondi à 2 décimales.
        - ``pourcentage_presence`` (float) : taux de présence 0–100, arrondi à 2 décimales.

        Toutes les valeurs valent 0.0 / 100.0 quand aucune séance n'a encore eu lieu.
    """
    from apps.academic_sessions.models import Seance
    from apps.enrollments.models import Inscription

    today = timezone.localdate()

    # Total des heures de cours = somme de (heure_fin - heure_debut) pour toutes les séances PASSÉES.
    # ExpressionWrapper est nécessaire car Django ne peut pas additionner directement les valeurs
    # DurationField calculées à partir de différences d'heures.
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

    # Garde : aucune séance passée pour l'instant — retourne un dict à zéro.
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

    # L'étudiant n'est pas activement inscrit → considéré comme 100 % présent.
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

    # Plafonne le pourcentage d'absence à 100 % pour gérer proprement les incohérences de données.
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
    Retourne la liste de tous les étudiants inscrits dont le taux d'absence atteint ou dépasse le seuil du cours.

    La fonction utilise une seule requête d'agrégation en lot pour toutes les
    inscriptions (au lieu d'une requête par étudiant) afin de garder
    l'opération en O(1) en termes d'allers-retours vers la base de données,
    quelle que soit la taille de la classe.

    Args :
        cours : instance ``apps.academics.models.Cours``.
        seuil (int | float | None) : seuil d'absence en pourcentage (0–100).
            Par défaut ``cours.get_seuil_absence()`` si la méthode existe,
            sinon repli sur 20 %.

    Retour :
        list[dict] : un dict par étudiant à risque, triés par
        ``pourcentage_absence`` décroissant. Chaque dict contient :

        - ``etudiant`` : instance User.
        - ``inscription`` : instance Inscription.
        - ``pourcentage_absence`` (float) : taux actuel d'absence non justifiée.
        - ``total_heures_absence`` (float) : total des heures d'absence non justifiée.
        - ``total_heures_cours`` (float) : total des heures de séances passées du cours.
        - ``depasse_seuil`` (bool) : toujours True (seuls les étudiants à risque sont retournés).
    """
    from apps.academic_sessions.models import Seance
    from apps.enrollments.models import Inscription

    if seuil is None:
        # Privilégier la méthode de seuil propre au cours ; repli sur un défaut raisonnable.
        seuil = cours.get_seuil_absence() if hasattr(cours, "get_seuil_absence") else 20

    today = timezone.localdate()

    # Étape 1 : calcule le total des heures pour les séances passées de ce cours.
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

    # Aucune séance n'a encore eu lieu — personne ne peut être à risque pour l'instant.
    if total_heures_cours == 0:
        return []

    # Étape 2 : récupère toutes les inscriptions actives pour ce cours.
    inscriptions = Inscription.objects.filter(
        id_cours=cours,
        status=Inscription.Status.EN_COURS,
    ).select_related("id_etudiant")

    # Étape 3 : agrégation en lot des heures d'absence non justifiée par inscription.
    # Cela évite une boucle de requête par étudiant (prévention N+1).
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

    # Étape 4 : classifie chaque inscription comme à risque ou non.
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

    # Retourne d'abord les étudiants les plus à risque.
    alertes.sort(key=lambda x: cast(float, x["pourcentage_absence"]), reverse=True)
    return alertes
