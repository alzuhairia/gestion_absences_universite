"""
Vue principale du tableau de bord administrateur pour UniAbsences.

Ce module affiche la page d'accueil principale de l'administrateur avec des cartes KPI
agrégées et le nombre d'étudiants à risque.

Fonctions
---------
``is_admin``
    Aide en ligne de vérification du rôle utilisée par les décorateurs ``user_passes_test`` dans
    ce module.

``_get_at_risk_count_cached``
    Calcule le nombre d'inscriptions à risque avec un cache Redis de 5 minutes afin
    que le chargement de la page du tableau de bord n'exécute pas une requête lourde à
    chaque requête.

``admin_dashboard_main``
    Affiche le template du tableau de bord administrateur avec huit valeurs KPI : étudiants
    actifs, professeurs, secrétaires, cours, inscriptions, absences,
    étudiants à risque et justifications en attente.

Fait partie du tableau de bord UniAbsences.
"""

import logging
from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.db.models import Sum
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_GET

from apps.absences.models import Absence
from apps.academic_sessions.models import AnneeAcademique
from apps.academics.models import Cours
from apps.accounts.models import User
from apps.audits.models import LogAudit
from apps.dashboard.decorators import admin_required
from apps.dashboard.models import SystemSettings
from apps.enrollments.models import Inscription

logger = logging.getLogger(__name__)


def is_admin(user):
    """
    Retourne ``True`` si l'utilisateur est authentifié et détient le rôle ADMIN.

    Cette aide est volontairement maintenue séparée de tout équivalent ``is_secretary()``
    pour rendre la séparation des rôles explicite et éviter une confusion accidentelle
    des deux rôles.

    Paramètres
    ----------
    user : User
        L'objet utilisateur à tester (peut être un ``AnonymousUser``).

    Retourne
    -------
    bool
        ``True`` uniquement lorsque l'utilisateur est authentifié avec ``role == ADMIN``.
    """
    return user.is_authenticated and user.role == User.Role.ADMIN


CACHE_KEY_AT_RISK = "admin_dashboard:at_risk_count"
CACHE_TTL_AT_RISK = 300  # 5 minutes


def _get_at_risk_count_cached(academic_year):
    """
    Calcule le nombre d'inscriptions à risque, en utilisant un cache de 5 minutes.

    Une inscription est considérée « à risque » lorsque le taux d'absences non
    justifiées de l'étudiant (``duree_absence / nombre_total_periodes * 100``) atteint ou
    dépasse le seuil effectif pour cette inscription. Le seuil effectif
    prend en compte les surcharges par cours et la marge d'exemption de 40 %
    (``ins.exemption_40 + ins.exemption_margin``).

    En cas de hit du cache, l'entier stocké est retourné immédiatement, évitant entièrement
    la requête d'agrégation lourde. En cas de miss, le compte est calculé en
    deux requêtes de base de données (toutes les inscriptions actuelles + totaux d'absences agrégés)
    puis mis en cache pendant ``CACHE_TTL_AT_RISK`` secondes.

    Paramètres
    ----------
    academic_year : AnneeAcademique ou None
        Lorsqu'il est fourni, le calcul est restreint à cette année. Lorsque
        ``None`` (aucune année active configurée), toutes les inscriptions actuelles sont
        considérées.

    Retourne
    -------
    int
        Nombre d'inscriptions dont le taux d'absences est égal ou supérieur à leur
        seuil effectif.
    """
    cached = cache.get(CACHE_KEY_AT_RISK)
    if cached is not None:
        return cached

    at_risk_count = 0
    all_inscriptions = Inscription.objects.filter(
        status=Inscription.Status.EN_COURS
    ).select_related("id_cours", "id_etudiant")
    if academic_year:
        all_inscriptions = all_inscriptions.filter(id_annee=academic_year)
    inscription_ids = list(all_inscriptions.values_list("id_inscription", flat=True))
    today = timezone.localdate()

    # Agréger les heures d'absences non justifiées par inscription en une seule requête.
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
    from apps.absences.services import get_system_threshold

    system_threshold = get_system_threshold()
    for ins in all_inscriptions:
        cours = ins.id_cours
        if cours.nombre_total_periodes > 0:
            total_abs = float(absence_sums.get(ins.id_inscription, 0) or 0)
            rate = (total_abs / cours.nombre_total_periodes) * 100
            # Utiliser le seuil spécifique au cours s'il est défini, sinon la valeur globale par défaut.
            seuil = (
                cours.seuil_absence
                if cours.seuil_absence is not None
                else system_threshold
            )
            # Appliquer la marge d'exemption pour les étudiants ayant une exemption accordée.
            seuil_effectif = (
                min(seuil + ins.exemption_margin, 100) if ins.exemption_40 else seuil
            )
            if rate >= seuil_effectif:
                at_risk_count += 1

    cache.set(CACHE_KEY_AT_RISK, at_risk_count, CACHE_TTL_AT_RISK)
    return at_risk_count


@login_required
@admin_required
@require_GET
def admin_dashboard_main(request):
    """
    Tableau de bord principal de l'administrateur avec KPIs et vue d'ensemble.
    IMPORTANT: L'administrateur configure et audite, il ne gère PAS les opérations quotidiennes.
    """
    academic_year = AnneeAcademique.objects.filter(active=True).first()

    total_students = User.objects.filter(role=User.Role.ETUDIANT, actif=True).count()
    total_professors = User.objects.filter(role=User.Role.PROFESSEUR, actif=True).count()
    total_secretaries = User.objects.filter(role=User.Role.SECRETAIRE, actif=True).count()

    active_courses = Cours.objects.filter(actif=True).count()

    at_risk_count = _get_at_risk_count_cached(academic_year)

    seven_days_ago = timezone.now() - timedelta(days=7)
    critical_actions = LogAudit.objects.filter(
        date_action__gte=seven_days_ago, niveau="CRITIQUE"
    ).count()

    if academic_year:
        total_inscriptions = Inscription.objects.filter(
            id_annee=academic_year, status=Inscription.Status.EN_COURS
        ).count()
        total_absences = Absence.objects.filter(
            id_inscription__id_annee=academic_year
        ).count()
    else:
        total_inscriptions = 0
        total_absences = 0

    recent_audits = LogAudit.objects.select_related("id_utilisateur").order_by(
        "-date_action"
    )[:10]

    settings = SystemSettings.get_settings()

    context = {
        "total_students": total_students,
        "total_professors": total_professors,
        "total_secretaries": total_secretaries,
        "active_courses": active_courses,
        "system_alerts": at_risk_count,
        "critical_actions": critical_actions,
        "total_inscriptions": total_inscriptions,
        "total_absences": total_absences,
        "recent_audits": recent_audits,
        "academic_year": academic_year,
        "settings": settings,
    }

    return render(request, "dashboard/admin_dashboard.html", context)
