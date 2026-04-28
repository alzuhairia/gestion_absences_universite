"""
Absences et rapports de l'étudiant.

Fonctionnalités :
  - Liste paginée de toutes les absences avec statut et bouton de justification
  - Page de téléchargement des rapports PDF
  - Logique `can_submit` : resoumission autorisée pour justificatifs refusés
"""

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Sum
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_GET

from apps.utils import safe_get_page
from apps.absences.models import Absence, Justification
from apps.absences.services import is_justification_expired
from apps.academic_sessions.models import AnneeAcademique
from apps.dashboard.decorators import student_required
from apps.enrollments.models import Inscription


@login_required
@student_required
@require_GET
def student_absences(request):
    """
    Page "Mes Absences" — liste paginée de toutes les absences de l'étudiant.
    """
    academic_year = AnneeAcademique.objects.filter(active=True).first()
    if not academic_year:
        academic_year = AnneeAcademique.objects.order_by("-id_annee").first()

    if academic_year:
        inscriptions = Inscription.objects.filter(
            id_etudiant=request.user,
            id_annee=academic_year,
            status=Inscription.Status.EN_COURS,
        )
    else:
        inscriptions = Inscription.objects.filter(
            id_etudiant=request.user, status=Inscription.Status.EN_COURS
        )

    absences = (
        Absence.objects.filter(id_inscription__in=inscriptions)
        .select_related("id_seance", "id_seance__id_cours", "id_inscription", "justification")
        .order_by("-id_seance__date_seance", "-id_seance__heure_debut")
    )

    absences_data = []
    for absence in absences:
        justification = getattr(absence, "justification", None)

        if justification:
            if justification.state == Justification.State.ACCEPTEE:
                status, status_color = "JUSTIFIÉE", "success"
            elif justification.state == Justification.State.REFUSEE:
                status, status_color = "NON JUSTIFIÉE", "danger"
            else:
                status, status_color = "EN ATTENTE", "warning"
        else:
            if absence.statut == Absence.Statut.JUSTIFIEE:
                status, status_color = "JUSTIFIÉE", "success"
            else:
                status, status_color = "NON JUSTIFIÉE", "danger"

        # CORRECTION BUG CRITIQUE #2c — resoumission autorisée si justificatif refusé
        is_refused = justification is not None and justification.state == Justification.State.REFUSEE
        is_not_yet_submitted = justification is None and absence.statut not in (
            Absence.Statut.JUSTIFIEE,
            Absence.Statut.EN_ATTENTE,
        )
        can_submit = (is_not_yet_submitted or is_refused) and not is_justification_expired(absence)

        absences_data.append(
            {
                "absence": absence,
                "status": status,
                "status_color": status_color,
                "justification": justification,
                "can_submit": can_submit,
            }
        )

    paginator = Paginator(absences_data, 25)
    page_obj = safe_get_page(paginator, request.GET.get("page"))

    return render(
        request,
        "dashboard/student_absences.html",
        {
            "academic_year": academic_year,
            "absences_data": page_obj,
            "page_obj": page_obj,
        },
    )


@login_required
@student_required
@require_GET
def student_reports(request):
    """
    Page "Rapports" — statistiques pour le téléchargement des rapports PDF.
    """
    academic_year = AnneeAcademique.objects.filter(active=True).first()
    if not academic_year:
        academic_year = AnneeAcademique.objects.order_by("-id_annee").first()

    if academic_year:
        inscriptions = list(
            Inscription.objects.filter(
                id_etudiant=request.user,
                id_annee=academic_year,
                status=Inscription.Status.EN_COURS,
            ).select_related("id_cours")
        )
    else:
        inscriptions = list(
            Inscription.objects.filter(id_etudiant=request.user).select_related("id_cours")
        )

    inscription_ids = [ins.id_inscription for ins in inscriptions]
    total_courses = len(inscriptions)
    total_absences = Absence.objects.filter(id_inscription__in=inscription_ids).count()

    total_abs_hours = 0
    total_periods = 0
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
    for ins in inscriptions:
        cours = ins.id_cours
        total_periods += cours.nombre_total_periodes
        total_abs_hours += float(absence_sums.get(ins.id_inscription, 0) or 0)

    overall_rate = (total_abs_hours / total_periods * 100) if total_periods > 0 else 0

    return render(
        request,
        "dashboard/student_reports.html",
        {
            "academic_year": academic_year,
            "total_courses": total_courses,
            "total_absences": total_absences,
            "overall_rate": round(overall_rate, 1),
        },
    )
