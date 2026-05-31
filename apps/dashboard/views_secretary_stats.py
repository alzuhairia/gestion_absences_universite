"""
Vues de statistiques et d'export du secrétaire pour le tableau de bord UniAbsences.

Vues
-----
``secretary_enrollments``
    Liste paginée de toutes les inscriptions actives avec taux d'absences, statut
    d'éligibilité et liens d'actions rapides pour le secrétariat.

``secretary_seuils_absence``
    Tableau d'ensemble des seuils d'absence par cours en regard de la valeur par
    défaut du système, afin que le secrétariat puisse identifier les cours aux paramètres personnalisés.

``secretary_exports``
    Page d'accueil pour les exports en masse : déclenche les vues de téléchargement PDF et Excel.

Fait partie du tableau de bord UniAbsences.
"""
from collections import defaultdict

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q, Sum
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_GET

from apps.utils import safe_get_page
from apps.absences.models import Absence
from apps.absences.services import get_system_threshold
from apps.academic_sessions.models import AnneeAcademique
from apps.academics.models import Cours, Departement, Faculte
from apps.dashboard.decorators import secretary_required
from apps.enrollments.models import Inscription


@login_required
@secretary_required
@require_GET
def secretary_enrollments(request):
    """
    Page "Inscriptions" — liste paginée des inscriptions avec filtres.
    """
    academic_year = AnneeAcademique.objects.filter(active=True).first()
    if not academic_year:
        academic_year = AnneeAcademique.objects.order_by("-id_annee").first()

    if academic_year:
        inscriptions = Inscription.objects.filter(
            id_annee=academic_year, status=Inscription.Status.EN_COURS
        ).select_related(
            "id_etudiant", "id_cours",
            "id_cours__id_departement", "id_cours__id_departement__id_faculte",
        )
    else:
        inscriptions = Inscription.objects.filter(status=Inscription.Status.EN_COURS).select_related(
            "id_etudiant", "id_cours",
            "id_cours__id_departement", "id_cours__id_departement__id_faculte",
        )

    faculty_filter = request.GET.get("faculty", "")
    department_filter = request.GET.get("department", "")
    course_filter = request.GET.get("course", "")
    search_query = request.GET.get("q", "")

    if faculty_filter:
        inscriptions = inscriptions.filter(id_cours__id_departement__id_faculte_id=faculty_filter)
    if department_filter:
        inscriptions = inscriptions.filter(id_cours__id_departement_id=department_filter)
    if course_filter:
        inscriptions = inscriptions.filter(id_cours_id=course_filter)
    if search_query:
        inscriptions = inscriptions.filter(
            Q(id_etudiant__nom__icontains=search_query)
            | Q(id_etudiant__prenom__icontains=search_query)
            | Q(id_etudiant__email__icontains=search_query)
            | Q(id_cours__code_cours__icontains=search_query)
            | Q(id_cours__nom_cours__icontains=search_query)
        )

    students_enrollments = defaultdict(list)
    for inscription in inscriptions.order_by(
        "id_etudiant__nom", "id_etudiant__prenom", "id_cours__code_cours"
    ):
        students_enrollments[inscription.id_etudiant].append(inscription)

    students_list = list(students_enrollments.items())
    paginator = Paginator(students_list, 25)
    page_obj = safe_get_page(paginator, request.GET.get("page"))

    faculties = Faculte.objects.filter(actif=True).order_by("nom_faculte")
    departments = Departement.objects.filter(actif=True).order_by("nom_departement")
    if faculty_filter:
        departments = departments.filter(id_faculte_id=faculty_filter)
    courses = Cours.objects.filter(actif=True).order_by("code_cours")
    if department_filter:
        courses = courses.filter(id_departement_id=department_filter)

    return render(
        request,
        "dashboard/secretary_enrollments.html",
        {
            "academic_year": academic_year,
            "page_obj": page_obj,
            "faculties": faculties,
            "departments": departments,
            "courses": courses,
            "faculty_filter": faculty_filter,
            "department_filter": department_filter,
            "course_filter": course_filter,
            "search_query": search_query,
        },
    )


@login_required
@secretary_required
@require_GET
def secretary_seuils_absence(request):
    """
    Liste des étudiants qui violent le seuil d'absence (par cours ou système).
    """
    active_year = AnneeAcademique.objects.filter(active=True).first()
    system_threshold = get_system_threshold()

    inscriptions_qs = Inscription.objects.filter(
        status=Inscription.Status.EN_COURS
    ).select_related("id_cours", "id_etudiant")
    if active_year:
        inscriptions_qs = inscriptions_qs.filter(id_annee=active_year)

    inscription_ids = list(inscriptions_qs.values_list("id_inscription", flat=True))
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

    at_risk_list = []
    for ins in inscriptions_qs:
        cours = ins.id_cours
        if cours.nombre_total_periodes > 0:
            total_abs = float(absence_sums.get(ins.id_inscription, 0) or 0)
            rate = (total_abs / cours.nombre_total_periodes) * 100
            seuil = cours.seuil_absence if cours.seuil_absence is not None else system_threshold
            seuil_effectif = min(seuil + ins.exemption_margin, 100) if ins.exemption_40 else seuil
            if rate >= seuil:
                is_blocked = rate >= seuil_effectif
                is_under_exemption = ins.exemption_40 and not is_blocked
                at_risk_list.append(
                    {
                        "inscription": ins,
                        "etudiant": ins.id_etudiant,
                        "cours": cours,
                        "total_abs": total_abs,
                        "rate": round(rate, 1),
                        "seuil": seuil,
                        "seuil_effectif": seuil_effectif,
                        "is_blocked": is_blocked,
                        "is_under_exemption": is_under_exemption,
                        "exemption": ins.exemption_40,
                        "exemption_margin": ins.exemption_margin,
                    }
                )

    blocked_count = sum(1 for item in at_risk_list if item["is_blocked"])
    exempted_count = sum(1 for item in at_risk_list if item["is_under_exemption"])

    paginator = Paginator(at_risk_list, 25)
    page_obj = safe_get_page(paginator, request.GET.get("page"))

    return render(
        request,
        "dashboard/secretary_seuils_absence.html",
        {
            "at_risk_list": page_obj,
            "page_obj": page_obj,
            "blocked_count": blocked_count,
            "exempted_count": exempted_count,
        },
    )


@login_required
@secretary_required
@require_GET
def secretary_exports(request):
    """
    Page "Exports" — statistiques pour le téléchargement des rapports Excel/PDF.
    """
    academic_year = AnneeAcademique.objects.filter(active=True).first()
    if not academic_year:
        academic_year = AnneeAcademique.objects.order_by("-id_annee").first()

    if academic_year:
        active_inscriptions = Inscription.objects.filter(
            id_annee=academic_year, status=Inscription.Status.EN_COURS
        ).select_related("id_cours")
    else:
        active_inscriptions = Inscription.objects.filter(
            status=Inscription.Status.EN_COURS
        ).select_related("id_cours")

    active_inscriptions_list = list(active_inscriptions)
    inscription_ids = [ins.id_inscription for ins in active_inscriptions_list]
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
    for ins in active_inscriptions_list:
        cours = ins.id_cours
        if cours.nombre_total_periodes > 0:
            total_abs = float(absence_sums.get(ins.id_inscription, 0) or 0)
            rate = (total_abs / cours.nombre_total_periodes) * 100
            seuil = ins.id_cours.get_seuil_absence()
            seuil_effectif = min(seuil + ins.exemption_margin, 100) if ins.exemption_40 else seuil
            if rate >= seuil_effectif:
                at_risk_count += 1

    return render(
        request,
        "dashboard/secretary_exports.html",
        {
            "academic_year": academic_year,
            "active_inscriptions_count": len(active_inscriptions_list),
            "at_risk_count": at_risk_count,
        },
    )
