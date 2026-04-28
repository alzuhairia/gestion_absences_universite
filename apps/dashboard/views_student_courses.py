"""
Cours et détail de cours de l'étudiant.

Fonctionnalités :
  - Liste de tous les cours inscrits avec taux d'absence et statut
  - Détail d'un cours : onglets Séances (présent/absent/excusé) et Absences
  - Logique `can_submit` : resoumission autorisée pour justificatifs refusés
"""

from django.contrib.auth.decorators import login_required
from django.db.models import Count, Sum
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.http import require_GET

from apps.absences.models import Absence, Justification
from apps.absences.services import get_system_threshold, is_justification_expired
from apps.academic_sessions.models import AnneeAcademique, Seance
from apps.dashboard.decorators import student_required
from apps.enrollments.models import Inscription


@login_required
@student_required
@require_GET
def student_course_detail(request, inscription_id):
    """
    Détail d'un cours pour l'étudiant — onglets Séances et Absences.
    STRICT : lecture seule + soumission de justificatifs uniquement.
    """
    inscription = get_object_or_404(
        Inscription, id_inscription=inscription_id, id_etudiant=request.user
    )
    course = inscription.id_cours

    academic_year = AnneeAcademique.objects.filter(active=True).first()
    if not academic_year:
        academic_year = AnneeAcademique.objects.order_by("-id_annee").first()

    active_tab = request.GET.get("tab", "sessions")

    # ── Onglet Séances ────────────────────────────────────────────────────────

    if academic_year:
        sessions = Seance.objects.filter(
            id_cours=course, id_annee=academic_year
        ).order_by("-date_seance", "-heure_debut")
    else:
        sessions = Seance.objects.filter(id_cours=course).order_by("-date_seance", "-heure_debut")

    session_ids = list(sessions.values_list("id_seance", flat=True))
    absences_by_session = {
        a.id_seance_id: a
        for a in Absence.objects.filter(
            id_inscription=inscription, id_seance_id__in=session_ids
        )
    }

    sessions_data = []
    for session in sessions:
        absence = absences_by_session.get(session.id_seance)
        if absence:
            if absence.statut == Absence.Statut.JUSTIFIEE:
                status, status_color = "Excused", "success"
            else:
                status, status_color = "Absent", "danger"
        else:
            status, status_color = "Present", "success"

        sessions_data.append(
            {"session": session, "status": status, "status_color": status_color, "absence": absence}
        )

    # ── Onglet Absences ───────────────────────────────────────────────────────

    absences = (
        Absence.objects.filter(id_inscription=inscription)
        .select_related("id_seance", "justification")
        .order_by("-id_seance__date_seance")
    )

    absences_data = []
    for absence in absences:
        justification = getattr(absence, "justification", None)

        if justification:
            if justification.state == Justification.State.ACCEPTEE:
                abs_status, abs_status_color = "JUSTIFIÉE", "success"
            elif justification.state == Justification.State.REFUSEE:
                abs_status, abs_status_color = "NON JUSTIFIÉE", "danger"
            else:
                abs_status, abs_status_color = "EN ATTENTE", "warning"
        else:
            if absence.statut == Absence.Statut.JUSTIFIEE:
                abs_status, abs_status_color = "JUSTIFIÉE", "success"
            else:
                abs_status, abs_status_color = "NON JUSTIFIÉE", "danger"

        # CORRECTION BUG CRITIQUE #2b — resoumission autorisée si justificatif refusé
        is_refused = justification is not None and justification.state == Justification.State.REFUSEE
        is_not_yet_submitted = justification is None and absence.statut not in (
            Absence.Statut.JUSTIFIEE,
            Absence.Statut.EN_ATTENTE,
        )
        can_submit = (is_not_yet_submitted or is_refused) and not is_justification_expired(absence)

        absences_data.append(
            {
                "absence": absence,
                "status": abs_status,
                "status_color": abs_status_color,
                "justification": justification,
                "can_submit": can_submit,
            }
        )

    # ── Statistiques du cours ─────────────────────────────────────────────────

    today = timezone.localdate()
    total_abs_hours = float(
        Absence.objects.filter(
            id_inscription=inscription,
            statut=Absence.Statut.NON_JUSTIFIEE,
            id_seance__date_seance__lte=today,
        ).aggregate(total=Sum("duree_absence"))["total"]
        or 0
    )

    absence_rate = (
        (total_abs_hours / course.nombre_total_periodes) * 100
        if course.nombre_total_periodes > 0
        else 0
    )
    seuil = course.get_seuil_absence()
    seuil_effectif = min(seuil + inscription.exemption_margin, 100) if inscription.exemption_40 else seuil
    is_blocked = absence_rate >= seuil_effectif
    is_under_exemption = inscription.exemption_40 and absence_rate >= seuil and not is_blocked

    return render(
        request,
        "dashboard/student_course_detail.html",
        {
            "inscription": inscription,
            "course": course,
            "academic_year": academic_year,
            "active_tab": active_tab,
            "sessions_data": sessions_data,
            "absences_data": absences_data,
            "absence_rate": round(absence_rate, 1),
            "is_blocked": is_blocked,
            "is_exempted": inscription.exemption_40,
            "is_under_exemption": is_under_exemption,
            "seuil_effectif": seuil_effectif,
        },
    )


@login_required
@student_required
@require_GET
def student_courses(request):
    """
    Page "Mes Cours" — liste de tous les cours de l'étudiant avec taux d'absence.
    """
    academic_year = AnneeAcademique.objects.filter(active=True).first()
    if not academic_year:
        academic_year = AnneeAcademique.objects.order_by("-id_annee").first()

    if academic_year:
        inscriptions = Inscription.objects.filter(
            id_etudiant=request.user,
            id_annee=academic_year,
            status=Inscription.Status.EN_COURS,
        ).select_related(
            "id_cours", "id_cours__professeur",
            "id_cours__id_departement", "id_cours__id_departement__id_faculte",
        )
    else:
        inscriptions = Inscription.objects.filter(
            id_etudiant=request.user, status=Inscription.Status.EN_COURS
        ).select_related(
            "id_cours", "id_cours__professeur",
            "id_cours__id_departement", "id_cours__id_departement__id_faculte",
        )

    inscriptions = list(inscriptions)
    inscription_ids = [ins.id_inscription for ins in inscriptions]
    course_ids = [ins.id_cours_id for ins in inscriptions]
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
    absence_counts = dict(
        Absence.objects.filter(id_inscription__in=inscription_ids)
        .values("id_inscription")
        .annotate(total=Count("id_absence"))
        .values_list("id_inscription", "total")
    )

    if academic_year:
        sessions_count_map = dict(
            Seance.objects.filter(id_cours__in=course_ids, id_annee=academic_year)
            .values("id_cours")
            .annotate(total=Count("id_seance"))
            .values_list("id_cours", "total")
        )
    else:
        sessions_count_map = dict(
            Seance.objects.filter(id_cours__in=course_ids)
            .values("id_cours")
            .annotate(total=Count("id_seance"))
            .values_list("id_cours", "total")
        )

    system_threshold = get_system_threshold()
    courses_data = []

    for ins in inscriptions:
        cours = ins.id_cours
        total_abs = float(absence_sums.get(ins.id_inscription, 0) or 0)
        absence_rate = (
            (total_abs / cours.nombre_total_periodes) * 100
            if cours.nombre_total_periodes > 0
            else 0
        )

        seuil_cours = cours.seuil_absence if cours.seuil_absence is not None else system_threshold
        seuil_effectif = min(seuil_cours + ins.exemption_margin, 100) if ins.exemption_40 else seuil_cours

        if absence_rate >= seuil_effectif:
            course_status, course_status_color = "BLOQUÉ", "danger"
        elif ins.exemption_40 and absence_rate >= seuil_cours:
            course_status, course_status_color = "SOUS EXEMPTION", "info"
        elif seuil_cours > 0 and absence_rate >= (seuil_cours * 0.75):
            course_status, course_status_color = "À RISQUE", "warning"
        else:
            course_status, course_status_color = "OK", "success"

        prof_name = cours.professeur.get_full_name() if cours.professeur else "Non assigné"

        courses_data.append(
            {
                "inscription": ins,
                "course": cours,
                "code": cours.code_cours,
                "nom": cours.nom_cours,
                "professeur": prof_name,
                "sessions_count": sessions_count_map.get(cours.id_cours, 0),
                "absences_count": absence_counts.get(ins.id_inscription, 0),
                "total_abs": total_abs,
                "total_periods": cours.nombre_total_periodes,
                "absence_rate": round(absence_rate, 1),
                "status": course_status,
                "status_color": course_status_color,
                "is_exempted": ins.exemption_40,
                "seuil_effectif": seuil_effectif,
            }
        )

    return render(
        request,
        "dashboard/student_courses.html",
        {"academic_year": academic_year, "courses_data": courses_data},
    )
