import json

from django.contrib.auth.decorators import login_required
from django.db.models import Count, Sum
from django.db.models.functions import TruncMonth
from django.shortcuts import get_object_or_404, render
from django.utils.safestring import mark_safe

from apps.absences.models import Absence
from apps.absences.services import get_system_threshold
from apps.academic_sessions.models import AnneeAcademique, Seance
from apps.dashboard.decorators import student_required
from apps.enrollments.models import Inscription
from apps.notifications.models import Notification


@login_required
@student_required
def student_dashboard(request):
    """
    Dashboard étudiant - Informatif et pédagogique, AUCUN pouvoir décisionnel.
    STRICT: L'étudiant peut uniquement consulter ses données, soumettre des justificatifs, télécharger des rapports.
    """

    # Get current academic year
    academic_year = AnneeAcademique.objects.filter(active=True).first()
    if not academic_year:
        academic_year = AnneeAcademique.objects.order_by("-id_annee").first()

    # Get student's inscriptions for current academic year
    if academic_year:
        inscriptions = Inscription.objects.filter(
            id_etudiant=request.user, id_annee=academic_year, status="EN_COURS"
        ).select_related("id_cours", "id_cours__professeur", "id_cours__id_departement")
    else:
        inscriptions = Inscription.objects.filter(
            id_etudiant=request.user
        ).select_related("id_cours", "id_cours__professeur", "id_cours__id_departement")

    # --- KPI 1: Total Courses Enrolled (current academic year)
    total_courses = inscriptions.count()

    # --- KPI 2: Total Sessions (all sessions for student's courses in current year)
    if academic_year:
        course_ids = inscriptions.values_list("id_cours", flat=True)
        total_sessions = Seance.objects.filter(
            id_cours__in=course_ids, id_annee=academic_year
        ).count()
    else:
        total_sessions = 0

    # --- KPI 3: Number of Absences (all absences, regardless of status)
    total_absences = Absence.objects.filter(id_inscription__in=inscriptions).count()

    # --- KPI 4: Overall Absence Rate (%) - based on NON_JUSTIFIED absences only
    total_abs_hours = 0
    total_periods = 0
    overall_rate = 0

    inscription_ids = list(inscriptions.values_list("id_inscription", flat=True))
    absence_sums = dict(
        Absence.objects.filter(
            id_inscription__in=inscription_ids,
            # CORRECTION BUG CRITIQUE #3b — EN_ATTENTE compte comme NON_JUSTIFIEE (loophole fermé)
            statut__in=["NON_JUSTIFIEE", "EN_ATTENTE"],
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

    for ins in inscriptions:
        cours = ins.id_cours
        total_periods += cours.nombre_total_periodes
        abs_hours = absence_sums.get(ins.id_inscription, 0) or 0
        total_abs_hours += abs_hours

    if total_periods > 0:
        overall_rate = (total_abs_hours / total_periods) * 100

    # --- KPI 5: Academic Status (OK / At Risk / Blocked)
    # Status is BLOCKED if ANY course exceeds 40%
    academic_status = "OK"
    status_color = "success"
    is_blocked = False
    is_at_risk = False

    for ins in inscriptions:
        cours = ins.id_cours
        if cours.nombre_total_periodes > 0:
            abs_hours = absence_sums.get(ins.id_inscription, 0) or 0
            rate = (abs_hours / cours.nombre_total_periodes) * 100

            # CORRECTION BUG CRITIQUE #4b — seuil configuré par cours
            seuil = cours.get_seuil_absence()
            if rate >= seuil and not ins.exemption_40:
                is_blocked = True
                academic_status = "BLOQUÉ"
                status_color = "danger"
                break
            elif rate >= (seuil * 0.75):  # Alerte à 75% du seuil
                is_at_risk = True

    if not is_blocked and is_at_risk:
        academic_status = "À RISQUE"
        status_color = "warning"

    # --- Prepare Course Data for "My Courses" Section
    cours_data = []

    sessions_count_map = {}
    if academic_year:
        sessions_count_map = dict(
            Seance.objects.filter(
                id_cours__in=inscriptions.values_list("id_cours", flat=True),
                id_annee=academic_year,
            )
            .values("id_cours")
            .annotate(total=Count("id_seance"))
            .values_list("id_cours", "total")
        )
    else:
        sessions_count_map = dict(
            Seance.objects.filter(
                id_cours__in=inscriptions.values_list("id_cours", flat=True)
            )
            .values("id_cours")
            .annotate(total=Count("id_seance"))
            .values_list("id_cours", "total")
        )

    for ins in inscriptions:
        cours = ins.id_cours

        # Calculate NON_JUSTIFIED absences only
        total_abs = absence_sums.get(ins.id_inscription, 0) or 0

        # Calculate absence rate
        absence_rate = (
            (total_abs / cours.nombre_total_periodes) * 100
            if cours.nombre_total_periodes > 0
            else 0
        )

        # Determine course status
        course_status = "OK"
        course_status_color = "success"
        # CORRECTION BUG CRITIQUE #4c — seuil configuré par cours
        seuil_cours = cours.get_seuil_absence()
        if absence_rate >= seuil_cours and not ins.exemption_40:
            course_status = "BLOQUÉ"
            course_status_color = "danger"
        elif absence_rate >= (seuil_cours * 0.75):
            course_status = "À RISQUE"
            course_status_color = "warning"

        # Count sessions for this course
        sessions_count = sessions_count_map.get(cours.id_cours, 0)

        # Count absences for this course
        absences_count = absence_counts.get(ins.id_inscription, 0)

        # Get professor name
        prof_name = "Non assigné"
        if cours.professeur:
            prof_name = cours.professeur.get_full_name()

        cours_data.append(
            {
                "inscription": ins,
                "course": cours,
                "code": cours.code_cours,
                "nom": cours.nom_cours,
                "professeur": prof_name,
                "sessions_count": sessions_count,
                "absences_count": absences_count,
                "total_abs": total_abs,
                "total_periods": cours.nombre_total_periodes,
                "absence_rate": round(absence_rate, 1),
                "status": course_status,
                "status_color": course_status_color,
                "is_exempted": ins.exemption_40,
            }
        )

    # Get notifications
    notifications = Notification.objects.filter(id_utilisateur=request.user).order_by(
        "-date_envoi"
    )[:5]

    return render(
        request,
        "dashboard/student_index.html",
        {
            "academic_year": academic_year,
            "total_courses": total_courses,
            "total_sessions": total_sessions,
            "total_absences": total_absences,
            "overall_rate": round(overall_rate, 1),
            "academic_status": academic_status,
            "status_color": status_color,
            "is_blocked": is_blocked,
            "notifications": notifications,
        },
    )


@login_required
@student_required
def student_statistics(request):
    """
    Page de statistiques détaillées pour l'étudiant.
    """
    # Get current academic year
    academic_year = AnneeAcademique.objects.filter(active=True).first()
    if not academic_year:
        academic_year = AnneeAcademique.objects.order_by("-id_annee").first()

    user = request.user
    inscriptions = Inscription.objects.filter(
        id_etudiant=user, status="EN_COURS"
    ).select_related("id_cours")

    # Filter by academic year if available
    if academic_year:
        inscriptions = inscriptions.filter(id_annee=academic_year)

    # --- 1. Data for Bar Chart (Absences per Course) ---
    course_labels = []
    absence_percentages = []

    total_hours_missed = 0
    courses_at_risk = 0

    inscription_ids = list(inscriptions.values_list("id_inscription", flat=True))

    # --- Compteurs globaux (tous statuts) ---
    total_absences = Absence.objects.filter(
        id_inscription__in=inscription_ids
    ).count()
    total_justified = Absence.objects.filter(
        id_inscription__in=inscription_ids, statut="JUSTIFIEE"
    ).count()

    absence_sums = dict(
        Absence.objects.filter(
            id_inscription__in=inscription_ids,
            # CORRECTION BUG CRITIQUE #3b — EN_ATTENTE compte comme NON_JUSTIFIEE (loophole fermé)
            statut__in=["NON_JUSTIFIEE", "EN_ATTENTE"],
        )
        .values("id_inscription")
        .annotate(total=Sum("duree_absence"))
        .values_list("id_inscription", "total")
    )

    system_threshold = get_system_threshold()

    for ins in inscriptions:
        cours = ins.id_cours
        total_periods = cours.nombre_total_periodes

        # Calculate Unjustified Absences
        total_abs = absence_sums.get(ins.id_inscription, 0) or 0

        rate = (total_abs / total_periods * 100) if total_periods > 0 else 0

        course_labels.append(cours.code_cours)
        absence_percentages.append(round(rate, 1))

        total_hours_missed += total_abs
        # CORRECTION BUG CRITIQUE #4g — seuil configuré par cours
        seuil = cours.get_seuil_absence()
        if rate >= seuil:
            courses_at_risk += 1

    # --- 2. Data for Line Chart (Trend over time) ---
    # Group ALL student absences by Month
    trend_labels = []
    trend_data = []

    # Get absences for this student across all courses
    absences_by_month = (
        Absence.objects.filter(id_inscription__in=inscriptions)
        .annotate(month=TruncMonth("id_seance__date_seance"))
        .values("month")
        .annotate(total_hours=Sum("duree_absence"))
        .order_by("month")
    )

    # French month names
    month_names_fr = {
        1: "Janvier",
        2: "Février",
        3: "Mars",
        4: "Avril",
        5: "Mai",
        6: "Juin",
        7: "Juillet",
        8: "Août",
        9: "Septembre",
        10: "Octobre",
        11: "Novembre",
        12: "Décembre",
    }

    for entry in absences_by_month:
        if entry["month"]:
            month_num = entry["month"].month
            trend_labels.append(
                month_names_fr.get(month_num, entry["month"].strftime("%B"))
            )
            trend_data.append(float(entry["total_hours"] or 0))

    # CORRECTION BUG CRITIQUE #7 — Suppression des données fictives
    # Avant : des données inventées (0, 2, 5, 8, 4) étaient présentées à un
    # nouvel étudiant comme si c'étaient ses vraies données d'absence.
    # C'est académiquement inacceptable : un graphique vide est plus honnête.
    # Le template doit afficher un message "Aucune donnée disponible pour cette période."
    # (aucun changement nécessaire côté template car trend_data=[] est géré correctement)

    context = {
        "academic_year": academic_year,
        "total_hours_missed": round(total_hours_missed, 1),
        "courses_at_risk": courses_at_risk,
        "total_absences": total_absences,
        "total_justified": total_justified,
        "system_threshold": system_threshold,
        "course_labels_json": mark_safe(json.dumps(course_labels)),
        "absence_percentages_json": mark_safe(json.dumps(absence_percentages)),
        "trend_labels_json": mark_safe(json.dumps(trend_labels)),
        "trend_data_json": mark_safe(json.dumps(trend_data)),
        "system_threshold_json": mark_safe(json.dumps(system_threshold)),
        "has_inscriptions": bool(course_labels),
        "has_trend_data": bool(trend_data),
    }

    return render(request, "dashboard/student_statistics.html", context)


@login_required
@student_required
def student_course_detail(request, inscription_id):
    """
    Page de détails du cours pour l'étudiant - Lecture seule, avec onglets pour Séances et Absences.
    STRICT: Aucune capacité d'édition, uniquement consultation et soumission de justificatifs.
    """
    # Get inscription and verify it belongs to the student
    inscription = get_object_or_404(
        Inscription, id_inscription=inscription_id, id_etudiant=request.user
    )
    course = inscription.id_cours

    # Get current academic year
    academic_year = AnneeAcademique.objects.filter(active=True).first()
    if not academic_year:
        academic_year = AnneeAcademique.objects.order_by("-id_annee").first()

    # Get active tab
    active_tab = request.GET.get("tab", "sessions")

    # Tab 1: Sessions - Chronological list with Present/Absent/Excused status
    if academic_year:
        sessions = Seance.objects.filter(
            id_cours=course, id_annee=academic_year
        ).order_by("-date_seance", "-heure_debut")
    else:
        sessions = Seance.objects.filter(id_cours=course).order_by(
            "-date_seance", "-heure_debut"
        )

    session_ids = list(sessions.values_list("id_seance", flat=True))
    absences_by_session = {
        a.id_seance_id: a
        for a in Absence.objects.filter(
            id_inscription=inscription, id_seance_id__in=session_ids
        )
    }

    sessions_data = []
    for session in sessions:
        # Check if student has absence for this session
        absence = absences_by_session.get(session.id_seance)

        if absence:
            if absence.statut == "JUSTIFIEE":
                status = "Excused"
                status_color = "success"
            else:
                status = "Absent"
                status_color = "danger"
        else:
            status = "Present"
            status_color = "success"

        sessions_data.append(
            {
                "session": session,
                "status": status,
                "status_color": status_color,
                "absence": absence,
            }
        )

    # Tab 2: Absences - List with status (JUSTIFIED, UNJUSTIFIED, PENDING)
    absences = (
        Absence.objects.filter(id_inscription=inscription)
        .select_related("id_seance", "justification")
        .order_by("-id_seance__date_seance")
    )

    absences_data = []
    for absence in absences:
        # Check if justification exists and its state
        justification = getattr(absence, "justification", None)

        if justification:
            if justification.state == "ACCEPTEE":
                abs_status = "JUSTIFIÉE"
                abs_status_color = "success"
            elif justification.state == "REFUSEE":
                abs_status = "NON JUSTIFIÉE"
                abs_status_color = "danger"
            else:  # EN_ATTENTE
                abs_status = "EN ATTENTE"
                abs_status_color = "warning"
        else:
            if absence.statut == "JUSTIFIEE":
                abs_status = "JUSTIFIÉE"
                abs_status_color = "success"
            else:
                abs_status = "NON JUSTIFIÉE"
                abs_status_color = "danger"

        # CORRECTION BUG CRITIQUE #2b — Logique can_submit corrigée (student_course_detail)
        # AVANT : "and not justification" masquait le bouton pour justificatifs refusés
        # APRÈS : resoumission autorisée si justificatif refusé, sinon non soumis
        is_refused = justification is not None and justification.state == "REFUSEE"
        is_not_yet_submitted = justification is None and absence.statut not in (
            "JUSTIFIEE",
            "EN_ATTENTE",
        )
        can_submit = is_not_yet_submitted or is_refused

        absences_data.append(
            {
                "absence": absence,
                "status": abs_status,
                "status_color": abs_status_color,
                "justification": justification,
                "can_submit": can_submit,
            }
        )

    # Calculate course statistics
    total_abs_hours = (
        Absence.objects.filter(
            id_inscription=inscription,
            # CORRECTION BUG CRITIQUE #3b — EN_ATTENTE compte comme NON_JUSTIFIEE
            statut__in=["NON_JUSTIFIEE", "EN_ATTENTE"],
        ).aggregate(total=Sum("duree_absence"))["total"]
        or 0
    )

    absence_rate = (
        (total_abs_hours / course.nombre_total_periodes) * 100
        if course.nombre_total_periodes > 0
        else 0
    )
    # CORRECTION BUG CRITIQUE #4l — seuil configuré par cours
    seuil = course.get_seuil_absence()
    is_blocked = absence_rate >= seuil and not inscription.exemption_40

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
        },
    )


@login_required
@student_required
def student_courses(request):
    """
    Page "Mes Cours" - Liste de tous les cours de l'étudiant.
    """
    # Get current academic year
    academic_year = AnneeAcademique.objects.filter(active=True).first()
    if not academic_year:
        academic_year = AnneeAcademique.objects.order_by("-id_annee").first()

    # Get student's inscriptions
    if academic_year:
        inscriptions = Inscription.objects.filter(
            id_etudiant=request.user, id_annee=academic_year, status="EN_COURS"
        ).select_related(
            "id_cours",
            "id_cours__professeur",
            "id_cours__id_departement",
            "id_cours__id_departement__id_faculte",
        )
    else:
        inscriptions = Inscription.objects.filter(
            id_etudiant=request.user
        ).select_related(
            "id_cours",
            "id_cours__professeur",
            "id_cours__id_departement",
            "id_cours__id_departement__id_faculte",
        )

    # Prepare course data with statistics
    courses_data = []
    inscription_ids = list(inscriptions.values_list("id_inscription", flat=True))
    course_ids = list(inscriptions.values_list("id_cours", flat=True))
    absence_sums = dict(
        Absence.objects.filter(
            id_inscription__in=inscription_ids,
            # CORRECTION BUG CRITIQUE #3b — EN_ATTENTE compte comme NON_JUSTIFIEE (loophole fermé)
            statut__in=["NON_JUSTIFIEE", "EN_ATTENTE"],
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

    for ins in inscriptions:
        cours = ins.id_cours

        # Calculate NON_JUSTIFIED absences only
        total_abs = absence_sums.get(ins.id_inscription, 0) or 0

        # Calculate absence rate
        absence_rate = (
            (total_abs / cours.nombre_total_periodes) * 100
            if cours.nombre_total_periodes > 0
            else 0
        )

        # Determine course status
        course_status = "OK"
        course_status_color = "success"
        # CORRECTION BUG CRITIQUE #4m — seuil configuré par cours
        seuil_cours = (
            cours.seuil_absence if cours.seuil_absence is not None else system_threshold
        )
        if absence_rate >= seuil_cours and not ins.exemption_40:
            course_status = "BLOQUÉ"
            course_status_color = "danger"
        elif absence_rate >= (seuil_cours * 0.75):
            course_status = "À RISQUE"
            course_status_color = "warning"
        # Count sessions and absences
        sessions_count = sessions_count_map.get(cours.id_cours, 0)

        absences_count = absence_counts.get(ins.id_inscription, 0)

        # Get professor name
        prof_name = "Non assigné"
        if cours.professeur:
            prof_name = cours.professeur.get_full_name()

        courses_data.append(
            {
                "inscription": ins,
                "course": cours,
                "code": cours.code_cours,
                "nom": cours.nom_cours,
                "professeur": prof_name,
                "sessions_count": sessions_count,
                "absences_count": absences_count,
                "total_abs": total_abs,
                "total_periods": cours.nombre_total_periodes,
                "absence_rate": round(absence_rate, 1),
                "status": course_status,
                "status_color": course_status_color,
                "is_exempted": ins.exemption_40,
            }
        )

    return render(
        request,
        "dashboard/student_courses.html",
        {
            "academic_year": academic_year,
            "courses_data": courses_data,
        },
    )


@login_required
@student_required
def student_absences(request):
    """
    Page "Mes Absences" - Liste de toutes les absences de l'étudiant.
    """
    # Get current academic year
    academic_year = AnneeAcademique.objects.filter(active=True).first()
    if not academic_year:
        academic_year = AnneeAcademique.objects.order_by("-id_annee").first()

    # Get all inscriptions
    if academic_year:
        inscriptions = Inscription.objects.filter(
            id_etudiant=request.user, id_annee=academic_year, status="EN_COURS"
        )
    else:
        inscriptions = Inscription.objects.filter(id_etudiant=request.user)

    # Get all absences
    absences = (
        Absence.objects.filter(id_inscription__in=inscriptions)
        .select_related(
            "id_seance", "id_seance__id_cours", "id_inscription", "justification"
        )
        .order_by("-id_seance__date_seance", "-id_seance__heure_debut")
    )

    # Prepare absence data with justification status
    absences_data = []
    for absence in absences:
        justification = getattr(absence, "justification", None)

        if justification:
            if justification.state == "ACCEPTEE":
                status = "JUSTIFIÉE"
                status_color = "success"
            elif justification.state == "REFUSEE":
                status = "NON JUSTIFIÉE"
                status_color = "danger"
            else:  # EN_ATTENTE
                status = "EN ATTENTE"
                status_color = "warning"
        else:
            if absence.statut == "JUSTIFIEE":
                status = "JUSTIFIÉE"
                status_color = "success"
            else:
                status = "NON JUSTIFIÉE"
                status_color = "danger"

        # CORRECTION BUG CRITIQUE #2c — Logique can_submit corrigée (student_absences)
        # AVANT : "and not justification" masquait le bouton pour justificatifs refusés
        # APRÈS : resoumission autorisée si justificatif refusé, sinon non soumis
        is_refused = justification is not None and justification.state == "REFUSEE"
        is_not_yet_submitted = justification is None and absence.statut not in (
            "JUSTIFIEE",
            "EN_ATTENTE",
        )
        can_submit = is_not_yet_submitted or is_refused

        absences_data.append(
            {
                "absence": absence,
                "status": status,
                "status_color": status_color,
                "justification": justification,
                "can_submit": can_submit,
            }
        )

    return render(
        request,
        "dashboard/student_absences.html",
        {
            "academic_year": academic_year,
            "absences_data": absences_data,
        },
    )


@login_required
@student_required
def student_reports(request):
    """
    Page "Rapports" - Téléchargement des rapports PDF.
    """
    # Get current academic year
    academic_year = AnneeAcademique.objects.filter(active=True).first()
    if not academic_year:
        academic_year = AnneeAcademique.objects.order_by("-id_annee").first()

    # Get student's inscriptions for statistics
    if academic_year:
        inscriptions = Inscription.objects.filter(
            id_etudiant=request.user, id_annee=academic_year, status="EN_COURS"
        ).select_related("id_cours")
    else:
        inscriptions = Inscription.objects.filter(
            id_etudiant=request.user
        ).select_related("id_cours")

    # Calculate overall statistics
    total_courses = inscriptions.count()
    total_absences = Absence.objects.filter(id_inscription__in=inscriptions).count()

    total_abs_hours = 0
    total_periods = 0
    absence_sums = dict(
        Absence.objects.filter(
            id_inscription__in=inscriptions.values_list("id_inscription", flat=True),
            # CORRECTION BUG CRITIQUE #3b — EN_ATTENTE compte comme NON_JUSTIFIEE (loophole fermé)
            statut__in=["NON_JUSTIFIEE", "EN_ATTENTE"],
        )
        .values("id_inscription")
        .annotate(total=Sum("duree_absence"))
        .values_list("id_inscription", "total")
    )
    for ins in inscriptions:
        cours = ins.id_cours
        total_periods += cours.nombre_total_periodes
        abs_hours = absence_sums.get(ins.id_inscription, 0) or 0
        total_abs_hours += abs_hours

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
