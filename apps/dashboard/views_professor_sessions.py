"""
Vues des séances et des statistiques côté professeur pour le système UniAbsences.

Ce module implémente deux vues en lecture seule pour le tableau de bord professeur :

``instructor_sessions``
    Liste paginée de toutes les séances (passées et futures) tenues par le
    professeur dans l'année académique active, classées de la plus récente à
    la plus ancienne et groupées par cours à des fins d'affichage.

``instructor_statistics``
    Statistiques agrégées par cours pour tous les cours actifs assignés au
    professeur : nombre d'étudiants inscrits, étudiants au niveau ou au-dessus
    de leur seuil effectif, total d'événements d'absence et taux d'absence
    moyen. Calcule également les totaux globaux et le pourcentage d'étudiants
    à risque sur l'ensemble des cours.

Fait partie du système de tableau de bord UniAbsences.
"""

from collections import defaultdict
from typing import Any

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, Sum
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_GET

from apps.utils import safe_get_page
from apps.absences.models import Absence
from apps.academic_sessions.models import AnneeAcademique, Seance
from apps.academics.models import Cours
from apps.dashboard.decorators import professor_required
from apps.enrollments.models import Inscription


@login_required
@professor_required
@require_GET
def instructor_sessions(request):
    """
    Rend la liste paginée des séances pour le professeur authentifié.

    Les séances sont filtrées sur l'année académique active et classées de la
    plus récente à la plus ancienne (par date, puis heure de début). Elles
    sont également groupées par cours pour prendre en charge un rendu groupé
    dans le template, bien que la pagination soit appliquée au queryset à plat.

    Parameters
    ----------
    request : HttpRequest
        Doit être une requête GET émise par un professeur authentifié.

    Returns
    -------
    HttpResponse
        Rend ``dashboard/instructor_sessions.html`` avec :

        ``academic_year`` : AnneeAcademique or None
        ``sessions`` : Page
            Page paginée d'objets ``Seance`` (25 par page).
        ``page_obj`` : Page
            Même objet que ``sessions`` (fourni pour compatibilité avec le template).
        ``sessions_by_course`` : dict[Cours, list[Seance]]
            Séances de la page courante groupées par leur cours parent.
    """
    academic_year = AnneeAcademique.objects.filter(active=True).first()
    if not academic_year:
        academic_year = AnneeAcademique.objects.order_by("-id_annee").first()

    if academic_year:
        sessions = (
            Seance.objects.filter(
                id_cours__professeur=request.user, id_annee=academic_year
            )
            .select_related("id_cours", "id_cours__id_departement")
            .order_by("-date_seance", "-heure_debut")
        )
    else:
        sessions = (
            Seance.objects.filter(id_cours__professeur=request.user)
            .select_related("id_cours", "id_cours__id_departement")
            .order_by("-date_seance", "-heure_debut")
        )

    paginator = Paginator(sessions, 25)
    # ``safe_get_page`` borne le numéro de page à la plage valide afin que les
    # valeurs ``?page=`` invalides ou hors plage ne lèvent pas un 404.
    page_obj = safe_get_page(paginator, request.GET.get("page"))

    # Regroupe les séances de la page courante par l'objet cours parent.
    sessions_by_course = defaultdict(list)
    for session in page_obj:
        sessions_by_course[session.id_cours].append(session)

    return render(
        request,
        "dashboard/instructor_sessions.html",
        {
            "academic_year": academic_year,
            "sessions": page_obj,
            "page_obj": page_obj,
            "sessions_by_course": dict(sessions_by_course),
        },
    )


@login_required
@professor_required
@require_GET
def instructor_statistics(request):
    """
    Rend la page de statistiques par cours pour le professeur authentifié.

    Pour chaque cours actif, la vue calcule :
        - Le nombre d'étudiants inscrits (EN_COURS, année active).
        - Le nombre d'étudiants au niveau ou au-dessus de leur seuil d'absence effectif.
        - Le nombre total d'événements d'absence (tous statuts).
        - Le taux moyen d'absences non justifiées parmi les étudiants inscrits.

    Les totaux globaux et un pourcentage transversal d'étudiants à risque
    sont également dérivés.

    Paramètres
    ----------
    request : HttpRequest
        Doit être une requête GET émise par un professeur authentifié.

    Retour
    ------
    HttpResponse
        Rend ``dashboard/instructor_statistics.html`` avec :

        ``academic_year`` : AnneeAcademique ou None
        ``course_stats`` : list[dict]
            Chaque dict comporte les clés : course, students_count,
            at_risk_count, absences_count, avg_rate.
        ``total_students`` : int
            Somme des étudiants inscrits sur tous les cours.
        ``total_at_risk`` : int
            Somme des étudiants à risque sur tous les cours.
        ``total_absences`` : int
            Somme des événements d'absence sur tous les cours.
        ``overall_at_risk_rate`` : float
            Pourcentage d'étudiants à risque sur le total (0 si aucun étudiant).
    """
    academic_year = AnneeAcademique.objects.filter(active=True).first()
    if not academic_year:
        academic_year = AnneeAcademique.objects.order_by("-id_annee").first()

    courses = Cours.objects.filter(professeur=request.user, actif=True)

    course_ids = list(courses.values_list("id_cours", flat=True))

    # Récupère toutes les inscriptions actives de tous les cours en une seule requête.
    if academic_year:
        all_inscriptions = list(
            Inscription.objects.filter(
                id_cours__in=course_ids, id_annee=academic_year, status=Inscription.Status.EN_COURS
            ).select_related("id_cours")
        )
    else:
        all_inscriptions = list(
            Inscription.objects.filter(
                id_cours__in=course_ids, status=Inscription.Status.EN_COURS
            ).select_related("id_cours")
        )

    inscription_ids = [ins.id_inscription for ins in all_inscriptions]
    today = timezone.localdate()

    # Agrège les heures non justifiées par inscription (séances passées uniquement).
    absence_sums: dict[int, Any] = dict(
        Absence.objects.filter(
            id_inscription__in=inscription_ids,
            statut=Absence.Statut.NON_JUSTIFIEE,
            id_seance__date_seance__lte=today,
        )
        .values("id_inscription")
        .annotate(total=Sum("duree_absence"))
        .values_list("id_inscription", "total")
    )

    # Agrège le nombre total d'événements d'absence par inscription (tous statuts).
    absence_counts: dict[int, Any] = dict(
        Absence.objects.filter(id_inscription__in=inscription_ids)
        .values("id_inscription")
        .annotate(total=Count("id_absence"))
        .values_list("id_inscription", "total")
    )

    # Regroupe les objets d'inscription par PK de cours pour une itération O(n) ci-dessous.
    inscriptions_by_course = defaultdict(list)
    for ins in all_inscriptions:
        inscriptions_by_course[ins.id_cours_id].append(ins)

    course_stats = []
    total_students = 0
    total_at_risk = 0
    total_absences = 0

    for course in courses:
        inscriptions = inscriptions_by_course.get(course.id_cours, [])
        course_at_risk = 0
        course_absences = 0
        rates = []  # Collecte les taux par étudiant pour calculer la moyenne du cours.

        for ins in inscriptions:
            total_abs = float(absence_sums.get(ins.id_inscription, 0) or 0)
            rate = (
                (total_abs / course.nombre_total_periodes) * 100
                if course.nombre_total_periodes > 0
                else 0.0
            )
            rates.append(rate)
            course_absences += absence_counts.get(ins.id_inscription, 0) or 0

            seuil = course.get_seuil_absence()
            # Le seuil effectif tient compte des marges d'exemption par étudiant.
            seuil_effectif = min(seuil + ins.exemption_margin, 100) if ins.exemption_40 else seuil
            if rate >= seuil_effectif:
                course_at_risk += 1

        # Taux d'absence moyen du cours ; 0 lorsqu'il n'y a aucune inscription.
        course_avg_rate = sum(rates) / len(rates) if rates else 0

        course_stats.append(
            {
                "course": course,
                "students_count": len(inscriptions),
                "at_risk_count": course_at_risk,
                "absences_count": course_absences,
                "avg_rate": round(course_avg_rate, 1),
            }
        )

        total_students += len(inscriptions)
        total_at_risk += course_at_risk
        total_absences += course_absences

    # Taux global d'étudiants à risque : pourcentage des étudiants inscrits qui sont à risque.
    overall_at_risk_rate = (total_at_risk / total_students * 100) if total_students > 0 else 0

    return render(
        request,
        "dashboard/instructor_statistics.html",
        {
            "academic_year": academic_year,
            "course_stats": course_stats,
            "total_students": total_students,
            "total_at_risk": total_at_risk,
            "total_absences": total_absences,
            "overall_at_risk_rate": round(overall_at_risk_rate, 1),
        },
    )
