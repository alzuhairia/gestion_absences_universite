from django.shortcuts import render, redirect, get_object_or_404
from django.db.models.functions import TruncMonth
from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.contrib import messages

from apps.enrollments.models import Inscription
from apps.absences.models import Absence, Justification
from apps.academics.models import Cours, Faculte, Departement
from apps.academic_sessions.models import Seance, AnneeAcademique
from django.db.models import Count, Q
from apps.notifications.models import Notification
from apps.accounts.models import User
from apps.audits.models import LogAudit
from apps.dashboard.decorators import professor_required, student_required, secretary_required
from collections import defaultdict

@login_required
def dashboard_redirect(request):
    """
    Redirige l'utilisateur vers le bon dashboard en fonction de son rôle.
    """
    user = request.user
    if user.role == User.Role.ETUDIANT:
        return student_dashboard(request)
    elif user.role == User.Role.PROFESSEUR:
        return instructor_dashboard(request)
    elif user.role == User.Role.ADMIN:
        return admin_dashboard(request)
    elif user.role == User.Role.SECRETAIRE:
        return secretary_dashboard(request)
    else:
        # Fallback ou message d'erreur
        messages.error(request, "Rôle non reconnu ou accès non autorisé.")
        return render(request, 'dashboard/error.html')

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
        academic_year = AnneeAcademique.objects.order_by('-id_annee').first()

    # Get student's inscriptions for current academic year
    if academic_year:
        inscriptions = Inscription.objects.filter(
            id_etudiant=request.user,
            id_annee=academic_year,
            status='EN_COURS'
        ).select_related('id_cours', 'id_cours__professeur', 'id_cours__id_departement')
    else:
        inscriptions = Inscription.objects.filter(
            id_etudiant=request.user
        ).select_related('id_cours', 'id_cours__professeur', 'id_cours__id_departement')
    
    # --- KPI 1: Total Courses Enrolled (current academic year)
    total_courses = inscriptions.count()
    
    # --- KPI 2: Total Sessions (all sessions for student's courses in current year)
    if academic_year:
        course_ids = inscriptions.values_list('id_cours', flat=True)
        total_sessions = Seance.objects.filter(
            id_cours__in=course_ids,
            id_annee=academic_year
        ).count()
    else:
        total_sessions = 0
    
    # --- KPI 3: Number of Absences (all absences, regardless of status)
    total_absences = Absence.objects.filter(
        id_inscription__in=inscriptions
    ).count()
    
    # --- KPI 4: Overall Absence Rate (%) - based on NON_JUSTIFIED absences only
    total_abs_hours = 0
    total_periods = 0
    overall_rate = 0
    
    for ins in inscriptions:
        cours = ins.id_cours
        total_periods += cours.nombre_total_periodes
        # Only count NON_JUSTIFIED absences
        abs_hours = Absence.objects.filter(
            id_inscription=ins,
            statut='NON_JUSTIFIEE'
        ).aggregate(total=Sum('duree_absence'))['total'] or 0
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
            abs_hours = Absence.objects.filter(
                id_inscription=ins,
                statut='NON_JUSTIFIEE'
            ).aggregate(total=Sum('duree_absence'))['total'] or 0
            rate = (abs_hours / cours.nombre_total_periodes) * 100
            
            if rate >= 40 and not ins.exemption_40:
                is_blocked = True
                academic_status = "BLOQUÉ"
                status_color = "danger"
                break
            elif rate >= 30:
                is_at_risk = True
    
    if not is_blocked and is_at_risk:
        academic_status = "À RISQUE"
        status_color = "warning"
    
    # --- Prepare Course Data for "My Courses" Section
    cours_data = []
    
    for ins in inscriptions:
        cours = ins.id_cours
        
        # Calculate NON_JUSTIFIED absences only
        total_abs = Absence.objects.filter(
            id_inscription=ins, 
            statut='NON_JUSTIFIEE'
        ).aggregate(total=Sum('duree_absence'))['total'] or 0
        
        # Calculate absence rate
        absence_rate = (total_abs / cours.nombre_total_periodes) * 100 if cours.nombre_total_periodes > 0 else 0
        
        # Determine course status
        course_status = "OK"
        course_status_color = "success"
        if absence_rate >= 40 and not ins.exemption_40:
            course_status = "BLOQUÉ"
            course_status_color = "danger"
        elif absence_rate >= 30:
            course_status = "À RISQUE"
            course_status_color = "warning"
        
        # Count sessions for this course
        if academic_year:
            sessions_count = Seance.objects.filter(
                id_cours=cours,
                id_annee=academic_year
            ).count()
        else:
            sessions_count = Seance.objects.filter(id_cours=cours).count()
        
        # Count absences for this course
        absences_count = Absence.objects.filter(id_inscription=ins).count()
        
        # Get professor name
        prof_name = "Non assigné"
        if cours.professeur:
            prof_name = cours.professeur.get_full_name()

        cours_data.append({
            'inscription': ins,
            'course': cours,
            'code': cours.code_cours,
            'nom': cours.nom_cours,
            'professeur': prof_name,
            'sessions_count': sessions_count,
            'absences_count': absences_count,
            'total_abs': total_abs,
            'total_periods': cours.nombre_total_periodes,
            'absence_rate': round(absence_rate, 1),
            'status': course_status,
            'status_color': course_status_color,
            'is_exempted': ins.exemption_40,
        })
    
    # Get notifications
    notifications = Notification.objects.filter(
        id_utilisateur=request.user
    ).order_by('-date_envoi')[:5]

    return render(request, 'dashboard/student_index.html', {
        'academic_year': academic_year,
        'total_courses': total_courses,
        'total_sessions': total_sessions,
        'total_absences': total_absences,
        'overall_rate': round(overall_rate, 1),
        'academic_status': academic_status,
        'status_color': status_color,
        'is_blocked': is_blocked,
        'notifications': notifications,
    })

from apps.dashboard.decorators import professor_required, student_required

@login_required
@professor_required
def instructor_dashboard(request):
    """
    Vue du tableau de bord professeur - Pédagogique uniquement
    Affiche les KPIs, cours actifs, et informations pédagogiques.
    STRICT: Aucune action administrative permise.
    """

    # Get current academic year
    academic_year = AnneeAcademique.objects.filter(active=True).first()
    if not academic_year:
        academic_year = AnneeAcademique.objects.order_by('-id_annee').first()

    from django.utils import timezone
    today = timezone.now().date()

    # --- KPI 1: Active Courses (current year, assigned to professor, with enrollments OR sessions)
    active_courses = Cours.objects.filter(professeur=request.user)
    if academic_year:
        # Courses with enrollments or sessions in current year
        courses_with_enrollments = Inscription.objects.filter(
            id_cours__professeur=request.user,
            id_annee=academic_year
        ).values_list('id_cours', flat=True).distinct()
        courses_with_sessions = Seance.objects.filter(
            id_cours__professeur=request.user,
            id_annee=academic_year
        ).values_list('id_cours', flat=True).distinct()
        active_course_ids = set(courses_with_enrollments) | set(courses_with_sessions)
        active_courses = active_courses.filter(id_cours__in=active_course_ids)
    active_courses_count = active_courses.count()

    # --- KPI 2: Sessions Given (current year, past sessions)
    if academic_year:
        sessions_given = Seance.objects.filter(
            id_cours__professeur=request.user,
            id_annee=academic_year,
            date_seance__lt=today
        ).count()
    else:
        sessions_given = 0

    # --- KPI 3: Upcoming Sessions (current year, future sessions)
    if academic_year:
        upcoming_sessions = Seance.objects.filter(
            id_cours__professeur=request.user,
            id_annee=academic_year,
            date_seance__gte=today
        ).count()
    else:
        upcoming_sessions = 0

    # --- KPI 4: Total Recorded Absences (all absences in professor's courses)
    total_absences = Absence.objects.filter(
        id_seance__id_cours__professeur=request.user
    ).count()

    # --- KPI 5: Students At Risk (>40%) - READ ONLY, INDICATIVE ONLY
    all_inscriptions = Inscription.objects.filter(
        id_cours__professeur=request.user
    ).select_related('id_cours', 'id_etudiant')
    
    at_risk_count = 0
    at_risk_list = []
    
    for ins in all_inscriptions:
        cours = ins.id_cours
        if cours.nombre_total_periodes > 0:
            # Calculate NON_JUSTIFIED absences only
            total_abs = Absence.objects.filter(
                id_inscription=ins, 
                statut='NON_JUSTIFIEE'
            ).aggregate(total=Sum('duree_absence'))['total'] or 0
            
            rate = (total_abs / cours.nombre_total_periodes) * 100
            
            if rate >= 40:
                at_risk_count += 1
                at_risk_list.append({
                    'etudiant': ins.id_etudiant,
                    'cours': cours,
                    'total_abs': total_abs,
                    'rate': round(rate, 1),
                    'inscription_id': ins.id_inscription,
                    'is_exempted': ins.exemption_40  # For display only
                })

    # --- Active Courses Data (for "My Active Courses" section)
    courses_data = []
    for course in active_courses.select_related('id_departement', 'id_departement__id_faculte'):
        # Count enrolled students
        if academic_year:
            enrolled_count = Inscription.objects.filter(
                id_cours=course,
                id_annee=academic_year,
                status='EN_COURS'
            ).count()
            sessions_count = Seance.objects.filter(
                id_cours=course,
                id_annee=academic_year
            ).count()
        else:
            enrolled_count = Inscription.objects.filter(id_cours=course).count()
            sessions_count = Seance.objects.filter(id_cours=course).count()

        courses_data.append({
            'course': course,
            'enrolled_count': enrolled_count,
            'sessions_count': sessions_count,
        })

    return render(request, 'dashboard/instructor_index.html', {
        'academic_year': academic_year,
        'active_courses_count': active_courses_count,
        'sessions_given': sessions_given,
        'upcoming_sessions': upcoming_sessions,
        'total_absences': total_absences,
        'at_risk_count': at_risk_count,
        'at_risk_list': at_risk_list[:5],  # Limit to 5 for dashboard display
    })

@login_required
def admin_dashboard(request):
    """
    Vue tableau de bord admin - Redirige vers le dashboard complet.
    IMPORTANT: L'ancien dashboard (admin_index.html) avec les justificatifs 
    n'est plus accessible aux administrateurs - c'est une tâche opérationnelle.
    """
    if request.user.role == User.Role.ADMIN:
        from .views_admin import admin_dashboard_main
        return admin_dashboard_main(request)
    elif request.user.role == User.Role.SECRETAIRE:
        # Le secrétariat peut voir les justificatifs en attente
        pending_justifications = Justification.objects.filter(
            state='EN_ATTENTE'
        ).select_related('id_absence__id_inscription__id_etudiant')
        return render(request, 'dashboard/secretary_index.html', {
            'pending_justifications': pending_justifications
        })
    else:
        messages.error(request, "Accès non autorisé.")
        return redirect('dashboard:index')

from apps.dashboard.decorators import secretary_required

@login_required
@secretary_required
def secretary_dashboard(request):
    """
    Vue tableau de bord secrétaire - KPIs uniquement
    """
    # Get current academic year
    academic_year = AnneeAcademique.objects.filter(active=True).first()
    if not academic_year:
        academic_year = AnneeAcademique.objects.order_by('-id_annee').first()

    # Get current academic year
    academic_year = AnneeAcademique.objects.filter(active=True).first()
    if not academic_year:
        academic_year = AnneeAcademique.objects.order_by('-id_annee').first()

    # 1. Pending Justifications Count
    global_pending_count = Justification.objects.filter(state='EN_ATTENTE').count()

    # 2. Global "At Risk" Calculation (> 40%)
    all_inscriptions = Inscription.objects.select_related('id_cours', 'id_etudiant').all()
    global_at_risk_count = 0
    
    for ins in all_inscriptions:
        cours = ins.id_cours
        if cours.nombre_total_periodes > 0:
            total_abs = Absence.objects.filter(
                id_inscription=ins, 
                statut='NON_JUSTIFIEE'
            ).aggregate(total=Sum('duree_absence'))['total'] or 0
            
            rate = (total_abs / cours.nombre_total_periodes) * 100
            
            if rate >= 40 and not ins.exemption_40:
                global_at_risk_count += 1

    # 5. KPI Calculations
    # Active Inscriptions (Inscriptions in the current academic year)
    active_inscriptions_count = 0
    if academic_year:
        active_inscriptions_count = Inscription.objects.filter(id_annee=academic_year, status='EN_COURS').count()
    
    # Active Courses: Use shared function to ensure consistency with active_courses view
    # Business Rule: Courses with assigned professor AND (sessions OR enrollments) in current year
    active_courses_queryset = get_active_courses_queryset(academic_year)
    active_courses_count = active_courses_queryset.count()

    return render(request, 'dashboard/secretary_index.html', {
        'global_pending_count': global_pending_count,
        'global_at_risk_count': global_at_risk_count,
        'academic_year': academic_year,
        'active_inscriptions_count': active_inscriptions_count,
        'active_courses_count': active_courses_count,
    })

@login_required
@secretary_required
def secretary_enrollments(request):
    """
    Page "Inscriptions" - Gestion des inscriptions étudiantes.
    """
    # Get current academic year
    academic_year = AnneeAcademique.objects.filter(active=True).first()
    if not academic_year:
        academic_year = AnneeAcademique.objects.order_by('-id_annee').first()

    # Get all inscriptions for current year
    if academic_year:
        inscriptions = Inscription.objects.filter(
            id_annee=academic_year,
            status='EN_COURS'
        ).select_related('id_etudiant', 'id_cours', 'id_cours__id_departement', 'id_cours__id_departement__id_faculte')
    else:
        inscriptions = Inscription.objects.filter(status='EN_COURS').select_related(
            'id_etudiant', 'id_cours', 'id_cours__id_departement', 'id_cours__id_departement__id_faculte'
        )

    # Get filter parameters
    faculty_filter = request.GET.get('faculty', '')
    department_filter = request.GET.get('department', '')
    course_filter = request.GET.get('course', '')
    search_query = request.GET.get('q', '')

    # Apply filters
    if faculty_filter:
        inscriptions = inscriptions.filter(id_cours__id_departement__id_faculte_id=faculty_filter)
    if department_filter:
        inscriptions = inscriptions.filter(id_cours__id_departement_id=department_filter)
    if course_filter:
        inscriptions = inscriptions.filter(id_cours_id=course_filter)
    if search_query:
        inscriptions = inscriptions.filter(
            Q(id_etudiant__nom__icontains=search_query) |
            Q(id_etudiant__prenom__icontains=search_query) |
            Q(id_etudiant__email__icontains=search_query) |
            Q(id_cours__code_cours__icontains=search_query) |
            Q(id_cours__nom_cours__icontains=search_query)
        )

    # Regrouper les inscriptions par étudiant
    students_enrollments = defaultdict(list)
    
    for inscription in inscriptions.order_by('id_etudiant__nom', 'id_etudiant__prenom', 'id_cours__code_cours'):
        students_enrollments[inscription.id_etudiant].append(inscription)
    
    # Créer une liste de tuples (étudiant, liste_des_inscriptions) pour la pagination
    students_list = list(students_enrollments.items())
    
    # Pagination
    from django.core.paginator import Paginator
    paginator = Paginator(students_list, 25)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    # Get filter options
    faculties = Faculte.objects.filter(actif=True).order_by('nom_faculte')
    departments = Departement.objects.filter(actif=True).order_by('nom_departement')
    if faculty_filter:
        departments = departments.filter(id_faculte_id=faculty_filter)
    courses = Cours.objects.filter(actif=True).order_by('code_cours')
    if department_filter:
        courses = courses.filter(id_departement_id=department_filter)

    return render(request, 'dashboard/secretary_enrollments.html', {
        'academic_year': academic_year,
        'page_obj': page_obj,
        'faculties': faculties,
        'departments': departments,
        'courses': courses,
        'faculty_filter': faculty_filter,
        'department_filter': department_filter,
        'course_filter': course_filter,
        'search_query': search_query,
    })

@login_required
@secretary_required
def secretary_rules_40(request):
    """
    Page "Règle des 40%" - Gestion des exemptions et étudiants à risque.
    """
    # Get all inscriptions
    all_inscriptions = Inscription.objects.select_related('id_cours', 'id_etudiant', 'id_cours__id_departement').all()
    at_risk_list = []
    
    for ins in all_inscriptions:
        cours = ins.id_cours
        if cours.nombre_total_periodes > 0:
            total_abs = Absence.objects.filter(
                id_inscription=ins, 
                statut='NON_JUSTIFIEE'
            ).aggregate(total=Sum('duree_absence'))['total'] or 0
            
            rate = (total_abs / cours.nombre_total_periodes) * 100
            
            # Show if rate >= 40 OR if they are exempted (so we can revoke if needed)
            if rate >= 40:
                at_risk_list.append({
                    'inscription': ins,
                    'etudiant': ins.id_etudiant,
                    'cours': cours,
                    'total_abs': total_abs,
                    'rate': round(rate, 1),
                    'is_blocked': not ins.exemption_40,
                    'exemption': ins.exemption_40,
                    'motif_exemption': ins.motif_exemption,
                })
    
    # Calculate statistics
    blocked_count = sum(1 for item in at_risk_list if item['is_blocked'])
    exempted_count = len(at_risk_list) - blocked_count

    # Get current academic year
    academic_year = AnneeAcademique.objects.filter(active=True).first()
    
    return render(request, 'dashboard/secretary_rules_40.html', {
        'academic_year': academic_year,
        'at_risk_list': at_risk_list,
        'blocked_count': blocked_count,
        'exempted_count': exempted_count,
    })

@login_required
@secretary_required
def secretary_exports(request):
    """
    Page "Exports" - Téléchargement des rapports Excel/PDF.
    """
    # Get current academic year
    academic_year = AnneeAcademique.objects.filter(active=True).first()
    if not academic_year:
        academic_year = AnneeAcademique.objects.order_by('-id_annee').first()

    # Calculate statistics for display
    if academic_year:
        active_inscriptions = Inscription.objects.filter(id_annee=academic_year, status='EN_COURS')
    else:
        active_inscriptions = Inscription.objects.filter(status='EN_COURS')

    # Count at-risk students
    at_risk_count = 0
    for ins in active_inscriptions:
        cours = ins.id_cours
        if cours.nombre_total_periodes > 0:
            total_abs = Absence.objects.filter(
                id_inscription=ins,
                statut='NON_JUSTIFIEE'
            ).aggregate(total=Sum('duree_absence'))['total'] or 0
            rate = (total_abs / cours.nombre_total_periodes) * 100
            if rate >= 40 and not ins.exemption_40:
                at_risk_count += 1

    return render(request, 'dashboard/secretary_exports.html', {
        'academic_year': academic_year,
        'active_inscriptions_count': active_inscriptions.count(),
        'at_risk_count': at_risk_count,
    })

def get_prof_name(cours):
    """
    Helper to get a professor name.
    """
    profs = User.objects.filter(role=User.Role.PROFESSEUR)
    if profs.exists():
        # Simple Logic: Assign based on Course ID parity or just first
        # Ideally we need a proper model relation
        return profs.first().get_full_name()
    return "Staff Académique"

def get_active_courses_queryset(academic_year):
    """
    Shared function to get active courses based on business rule.
    
    Business Rule: Active Courses = Courses that:
    1. Have an assigned professor (professeur__isnull=False)
    2. AND have sessions OR enrollments (or both) in the current academic year
    
    This ensures consistency between KPI calculation and the active courses list.
    
    Returns: QuerySet of Cours objects
    """
    # Base query: Courses with assigned professor
    courses = Cours.objects.filter(professeur__isnull=False)
    
    if not academic_year:
        return courses.none()  # No active year = no active courses
    
    # Get courses that have sessions OR enrollments in current year
    courses_with_sessions = Seance.objects.filter(
        id_annee=academic_year
    ).values_list('id_cours', flat=True).distinct()
    
    courses_with_enrollments = Inscription.objects.filter(
        id_annee=academic_year
    ).values_list('id_cours', flat=True).distinct()
    
    # Union: courses with sessions OR enrollments (or both)
    active_course_ids = set(courses_with_sessions) | set(courses_with_enrollments)
    
    # Filter to only courses with assigned professor that are in the active list
    return courses.filter(id_cours__in=active_course_ids)

@login_required
@student_required
def student_statistics(request):
    """
    Page de statistiques détaillées pour l'étudiant.
    """
    # Get current academic year
    academic_year = AnneeAcademique.objects.filter(active=True).first()
    if not academic_year:
        academic_year = AnneeAcademique.objects.order_by('-id_annee').first()

    user = request.user
    inscriptions = Inscription.objects.filter(id_etudiant=user)
    
    # Filter by academic year if available
    if academic_year:
        inscriptions = inscriptions.filter(id_annee=academic_year)
    
    # --- 1. Data for Bar Chart (Absences per Course) ---
    course_labels = []
    absence_percentages = []
    accumulated_absences = [] # For thresholds
    
    total_hours_missed = 0
    courses_at_risk = 0
    
    for ins in inscriptions:
        cours = ins.id_cours
        total_periods = cours.nombre_total_periodes
        
        # Calculate Unjustified Absences
        total_abs = Absence.objects.filter(
            id_inscription=ins, 
            statut='NON_JUSTIFIEE'
        ).aggregate(total=Sum('duree_absence'))['total'] or 0
        
        rate = (total_abs / total_periods * 100) if total_periods > 0 else 0
        
        course_labels.append(cours.code_cours)
        absence_percentages.append(round(rate, 1))
        
        total_hours_missed += total_abs
        if rate >= 40:
            courses_at_risk += 1

    # --- 2. Data for Line Chart (Trend over time) ---
    # Group ALL student absences by Month
    trend_labels = []
    trend_data = []

    # Get absences for this student across all courses
    absences_by_month = Absence.objects.filter(
        id_inscription__in=inscriptions
    ).annotate(
        month=TruncMonth('id_seance__date_seance')
    ).values('month').annotate(
        total_hours=Sum('duree_absence')
    ).order_by('month')
    
    # French month names
    month_names_fr = {
        1: 'Janvier', 2: 'Février', 3: 'Mars', 4: 'Avril',
        5: 'Mai', 6: 'Juin', 7: 'Juillet', 8: 'Août',
        9: 'Septembre', 10: 'Octobre', 11: 'Novembre', 12: 'Décembre'
    }
    
    for entry in absences_by_month:
        if entry['month']:
            month_num = entry['month'].month
            trend_labels.append(month_names_fr.get(month_num, entry['month'].strftime('%B')))
            trend_data.append(float(entry['total_hours']))

    # If no data, provide empty structure or mock for visualization
    if not trend_data:
        trend_labels = ["Septembre", "Octobre", "Novembre", "Décembre", "Janvier"]
        trend_data = [0, 2, 5, 8, 4] # Mock data for "New" student experience

    from django.utils.safestring import mark_safe
    import json
    
    context = {
        'academic_year': academic_year,
        'total_hours_missed': round(total_hours_missed, 1),
        'courses_at_risk': courses_at_risk,
        'course_labels': mark_safe(json.dumps(course_labels)),
        'absence_percentages': mark_safe(json.dumps(absence_percentages)),
        'trend_labels': mark_safe(json.dumps(trend_labels)),
        'trend_data': mark_safe(json.dumps(trend_data)),
    }
    
    return render(request, 'dashboard/student_statistics.html', context)

@login_required
def active_courses(request):
    """
    View to display active courses for the current academic year.
    Administrative view - read-only for secretary.
    """
    if request.user.role != User.Role.SECRETAIRE and request.user.role != User.Role.ADMIN:
        return redirect('dashboard:index')

    # Get current academic year
    academic_year = AnneeAcademique.objects.filter(active=True).first()
    if not academic_year:
        academic_year = AnneeAcademique.objects.order_by('-id_annee').first()

    # Get filter parameters
    faculty_filter = request.GET.get('faculty', '')
    department_filter = request.GET.get('department', '')
    professor_filter = request.GET.get('professor', '')
    search_query = request.GET.get('q', '')

    # Use shared function to get active courses (ensures consistency with KPI)
    # Business Rule: Courses with assigned professor AND (sessions OR enrollments) in current year
    courses = get_active_courses_queryset(academic_year).select_related(
        'professeur', 'id_departement', 'id_departement__id_faculte'
    )

    # Apply filters
    if faculty_filter:
        courses = courses.filter(id_departement__id_faculte_id=faculty_filter)
    
    if department_filter:
        courses = courses.filter(id_departement_id=department_filter)
    
    if professor_filter:
        courses = courses.filter(professeur_id=professor_filter)
    
    if search_query:
        courses = courses.filter(
            Q(code_cours__icontains=search_query) |
            Q(nom_cours__icontains=search_query)
        )

    # Order by course code
    courses = courses.order_by('code_cours')

    # Get filter options
    faculties = Faculte.objects.all().order_by('nom_faculte')
    departments = Departement.objects.all().order_by('nom_departement')
    if faculty_filter:
        departments = departments.filter(id_faculte_id=faculty_filter)
    professors = User.objects.filter(role=User.Role.PROFESSEUR).order_by('nom', 'prenom')

    # Prepare course data with additional info
    courses_data = []
    for course in courses:
        # Get all sessions for this course in current year to determine semester/period
        sessions = []
        if academic_year:
            sessions = Seance.objects.filter(id_cours=course, id_annee=academic_year).order_by('date_seance')
        
        # Calculate enrolled students count manually to avoid reverse relation issues
        enrolled_count = 0
        if academic_year:
            enrolled_count = Inscription.objects.filter(
                id_cours=course,
                id_annee=academic_year,
                status='EN_COURS'
            ).count()
        else:
            enrolled_count = Inscription.objects.filter(id_cours=course).count()
        
        # Determine semester/period from sessions (if available)
        semester_info = "N/A"
        if sessions.exists():
            first_session = sessions.first()
            last_session = sessions.last()
            # Simple heuristic: if sessions span multiple months, it's a full semester
            if first_session and last_session:
                months = (last_session.date_seance.year - first_session.date_seance.year) * 12 + \
                        (last_session.date_seance.month - first_session.date_seance.month)
                if months > 3:
                    semester_info = f"Semestre complet ({first_session.date_seance.strftime('%m/%Y')} - {last_session.date_seance.strftime('%m/%Y')})"
                else:
                    semester_info = f"{first_session.date_seance.strftime('%B %Y')}"

        courses_data.append({
            'course': course,
            'enrolled_count': enrolled_count,
            'semester_info': semester_info,
            'has_sessions': sessions.exists(),
        })

    return render(request, 'dashboard/active_courses.html', {
        'courses_data': courses_data,
        'academic_year': academic_year,
        'faculties': faculties,
        'departments': departments,
        'professors': professors,
        'current_faculty': faculty_filter,
        'current_department': department_filter,
        'current_professor': professor_filter,
        'search_query': search_query,
    })

@login_required
@professor_required
def instructor_course_detail(request, course_id):
    """
    Page de détails du cours pour le professeur - Lecture seule pour les étudiants, gestion des séances pour le professeur.
    STRICT: Aucune action administrative permise.
    """
    # Get course and verify it belongs to the instructor
    course = get_object_or_404(Cours, id_cours=course_id)
    if course.professeur != request.user:
        messages.error(request, "Accès non autorisé à ce cours.")
        return redirect('dashboard:instructor_dashboard')

    # Get current academic year
    academic_year = AnneeAcademique.objects.filter(active=True).first()
    if not academic_year:
        academic_year = AnneeAcademique.objects.order_by('-id_annee').first()

    # Get active tab
    active_tab = request.GET.get('tab', 'students')

    # Tab 1: Students (READ ONLY)
    students_data = []
    if academic_year:
        inscriptions = Inscription.objects.filter(
            id_cours=course,
            id_annee=academic_year,
            status='EN_COURS'
        ).select_related('id_etudiant')
    else:
        inscriptions = Inscription.objects.filter(id_cours=course).select_related('id_etudiant')

    for ins in inscriptions:
        # Calculate absence rate
        total_abs = Absence.objects.filter(
            id_inscription=ins,
            statut='NON_JUSTIFIEE'
        ).aggregate(total=Sum('duree_absence'))['total'] or 0
        
        rate = (total_abs / course.nombre_total_periodes) * 100 if course.nombre_total_periodes > 0 else 0
        is_at_risk = rate >= 40

        students_data.append({
            'inscription': ins,
            'etudiant': ins.id_etudiant,
            'total_abs': total_abs,
            'rate': round(rate, 1),
            'is_at_risk': is_at_risk,
            'is_exempted': ins.exemption_40,
        })

    # Tab 2: Sessions
    if academic_year:
        sessions = Seance.objects.filter(
            id_cours=course,
            id_annee=academic_year
        ).order_by('-date_seance', '-heure_debut')
    else:
        sessions = Seance.objects.filter(id_cours=course).order_by('-date_seance', '-heure_debut')

    # Tab 3: Statistics
    total_students = len(students_data)
    at_risk_students = sum(1 for s in students_data if s['is_at_risk'])
    total_absences_all = Absence.objects.filter(id_seance__id_cours=course).count()
    
    # Overall absence rate (average)
    if total_students > 0:
        overall_rate = sum(s['rate'] for s in students_data) / total_students
    else:
        overall_rate = 0

    return render(request, 'dashboard/instructor_course_detail.html', {
        'course': course,
        'academic_year': academic_year,
        'active_tab': active_tab,
        'students_data': students_data,
        'sessions': sessions,
        'total_students': total_students,
        'at_risk_students': at_risk_students,
        'total_absences_all': total_absences_all,
        'overall_rate': round(overall_rate, 1),
    })

@login_required
@professor_required
def instructor_courses(request):
    """
    Page "Mes Cours" - Liste de tous les cours assignés au professeur.
    """
    # Get current academic year
    academic_year = AnneeAcademique.objects.filter(active=True).first()
    if not academic_year:
        academic_year = AnneeAcademique.objects.order_by('-id_annee').first()

    # Get all courses assigned to professor
    courses = Cours.objects.filter(professeur=request.user).select_related(
        'id_departement', 'id_departement__id_faculte'
    ).order_by('code_cours')

    # Filter by academic year if available
    if academic_year:
        courses_with_activity = set(
            Inscription.objects.filter(
                id_cours__professeur=request.user,
                id_annee=academic_year
            ).values_list('id_cours', flat=True).distinct()
        ) | set(
            Seance.objects.filter(
                id_cours__professeur=request.user,
                id_annee=academic_year
            ).values_list('id_cours', flat=True).distinct()
        )
        courses = courses.filter(id_cours__in=courses_with_activity)

    # Prepare course data with statistics
    courses_data = []
    for course in courses:
        if academic_year:
            enrolled_count = Inscription.objects.filter(
                id_cours=course,
                id_annee=academic_year,
                status='EN_COURS'
            ).count()
            sessions_count = Seance.objects.filter(
                id_cours=course,
                id_annee=academic_year
            ).count()
        else:
            enrolled_count = Inscription.objects.filter(id_cours=course).count()
            sessions_count = Seance.objects.filter(id_cours=course).count()

        # Calculate at-risk students count
        inscriptions = Inscription.objects.filter(id_cours=course)
        at_risk = 0
        for ins in inscriptions:
            total_abs = Absence.objects.filter(
                id_inscription=ins,
                statut='NON_JUSTIFIEE'
            ).aggregate(total=Sum('duree_absence'))['total'] or 0
            rate = (total_abs / course.nombre_total_periodes) * 100 if course.nombre_total_periodes > 0 else 0
            if rate >= 40 and not ins.exemption_40:
                at_risk += 1

        courses_data.append({
            'course': course,
            'enrolled_count': enrolled_count,
            'sessions_count': sessions_count,
            'at_risk_count': at_risk,
        })

    return render(request, 'dashboard/instructor_courses.html', {
        'academic_year': academic_year,
        'courses_data': courses_data,
    })

@login_required
@professor_required
def instructor_sessions(request):
    """
    Page "Séances" - Liste de toutes les séances du professeur.
    """
    # Get current academic year
    academic_year = AnneeAcademique.objects.filter(active=True).first()
    if not academic_year:
        academic_year = AnneeAcademique.objects.order_by('-id_annee').first()

    # Get all sessions for professor's courses
    if academic_year:
        sessions = Seance.objects.filter(
            id_cours__professeur=request.user,
            id_annee=academic_year
        ).select_related('id_cours', 'id_cours__id_departement').order_by('-date_seance', '-heure_debut')
    else:
        sessions = Seance.objects.filter(
            id_cours__professeur=request.user
        ).select_related('id_cours', 'id_cours__id_departement').order_by('-date_seance', '-heure_debut')

    # Group sessions by course
    sessions_by_course = defaultdict(list)
    for session in sessions:
        sessions_by_course[session.id_cours].append(session)

    return render(request, 'dashboard/instructor_sessions.html', {
        'academic_year': academic_year,
        'sessions': sessions,
        'sessions_by_course': dict(sessions_by_course),
    })

@login_required
@professor_required
def instructor_statistics(request):
    """
    Page "Statistiques" - Statistiques globales pour le professeur.
    """
    # Get current academic year
    academic_year = AnneeAcademique.objects.filter(active=True).first()
    if not academic_year:
        academic_year = AnneeAcademique.objects.order_by('-id_annee').first()

    # Get all courses
    courses = Cours.objects.filter(professeur=request.user)
    if academic_year:
        courses_with_activity = set(
            Inscription.objects.filter(
                id_cours__professeur=request.user,
                id_annee=academic_year
            ).values_list('id_cours', flat=True).distinct()
        ) | set(
            Seance.objects.filter(
                id_cours__professeur=request.user,
                id_annee=academic_year
            ).values_list('id_cours', flat=True).distinct()
        )
        courses = courses.filter(id_cours__in=courses_with_activity)

    # Statistics by course
    course_stats = []
    total_students = 0
    total_at_risk = 0
    total_absences = 0

    for course in courses:
        if academic_year:
            inscriptions = Inscription.objects.filter(
                id_cours=course,
                id_annee=academic_year,
                status='EN_COURS'
            )
        else:
            inscriptions = Inscription.objects.filter(id_cours=course)

        course_at_risk = 0
        course_absences = 0
        course_avg_rate = 0

        rates = []
        for ins in inscriptions:
            total_abs = Absence.objects.filter(
                id_inscription=ins,
                statut='NON_JUSTIFIEE'
            ).aggregate(total=Sum('duree_absence'))['total'] or 0
            rate = (total_abs / course.nombre_total_periodes) * 100 if course.nombre_total_periodes > 0 else 0
            rates.append(rate)
            course_absences += Absence.objects.filter(id_inscription=ins).count()
            if rate >= 40 and not ins.exemption_40:
                course_at_risk += 1

        if rates:
            course_avg_rate = sum(rates) / len(rates)

        course_stats.append({
            'course': course,
            'students_count': inscriptions.count(),
            'at_risk_count': course_at_risk,
            'absences_count': course_absences,
            'avg_rate': round(course_avg_rate, 1),
        })

        total_students += inscriptions.count()
        total_at_risk += course_at_risk
        total_absences += course_absences

    # Overall statistics
    overall_at_risk_rate = (total_at_risk / total_students * 100) if total_students > 0 else 0

    return render(request, 'dashboard/instructor_statistics.html', {
        'academic_year': academic_year,
        'course_stats': course_stats,
        'total_students': total_students,
        'total_at_risk': total_at_risk,
        'total_absences': total_absences,
        'overall_at_risk_rate': round(overall_at_risk_rate, 1),
    })

@login_required
@student_required
def student_course_detail(request, inscription_id):
    """
    Page de détails du cours pour l'étudiant - Lecture seule, avec onglets pour Séances et Absences.
    STRICT: Aucune capacité d'édition, uniquement consultation et soumission de justificatifs.
    """
    # Get inscription and verify it belongs to the student
    inscription = get_object_or_404(Inscription, id_inscription=inscription_id, id_etudiant=request.user)
    course = inscription.id_cours
    
    # Get current academic year
    academic_year = AnneeAcademique.objects.filter(active=True).first()
    if not academic_year:
        academic_year = AnneeAcademique.objects.order_by('-id_annee').first()

    # Get active tab
    active_tab = request.GET.get('tab', 'sessions')

    # Tab 1: Sessions - Chronological list with Present/Absent/Excused status
    if academic_year:
        sessions = Seance.objects.filter(
            id_cours=course,
            id_annee=academic_year
        ).order_by('-date_seance', '-heure_debut')
    else:
        sessions = Seance.objects.filter(id_cours=course).order_by('-date_seance', '-heure_debut')

    sessions_data = []
    for session in sessions:
        # Check if student has absence for this session
        absence = Absence.objects.filter(
            id_inscription=inscription,
            id_seance=session
        ).first()
        
        if absence:
            if absence.statut == 'JUSTIFIEE':
                status = "Excused"
                status_color = "success"
            else:
                status = "Absent"
                status_color = "danger"
        else:
            status = "Present"
            status_color = "success"
        
        sessions_data.append({
            'session': session,
            'status': status,
            'status_color': status_color,
            'absence': absence,
        })

    # Tab 2: Absences - List with status (JUSTIFIED, UNJUSTIFIED, PENDING)
    absences = Absence.objects.filter(
        id_inscription=inscription
    ).select_related('id_seance').order_by('-id_seance__date_seance')

    absences_data = []
    for absence in absences:
        # Check if justification exists and its state
        justification = Justification.objects.filter(id_absence=absence).first()
        
        if justification:
            if justification.state == 'ACCEPTEE':
                abs_status = "JUSTIFIÉE"
                abs_status_color = "success"
            elif justification.state == 'REFUSEE':
                abs_status = "NON JUSTIFIÉE"
                abs_status_color = "danger"
            else:  # EN_ATTENTE
                abs_status = "EN ATTENTE"
                abs_status_color = "warning"
        else:
            if absence.statut == 'JUSTIFIEE':
                abs_status = "JUSTIFIÉE"
                abs_status_color = "success"
            else:
                abs_status = "NON JUSTIFIÉE"
                abs_status_color = "danger"
        
        # Can submit justification only if UNJUSTIFIED or PENDING (and no existing justification)
        can_submit = (abs_status == "NON JUSTIFIÉE" or abs_status == "EN ATTENTE") and not justification

        absences_data.append({
            'absence': absence,
            'status': abs_status,
            'status_color': abs_status_color,
            'justification': justification,
            'can_submit': can_submit,
        })

    # Calculate course statistics
    total_abs_hours = Absence.objects.filter(
        id_inscription=inscription,
        statut='NON_JUSTIFIEE'
    ).aggregate(total=Sum('duree_absence'))['total'] or 0
    
    absence_rate = (total_abs_hours / course.nombre_total_periodes) * 100 if course.nombre_total_periodes > 0 else 0
    is_blocked = absence_rate >= 40 and not inscription.exemption_40

    return render(request, 'dashboard/student_course_detail.html', {
        'inscription': inscription,
        'course': course,
        'academic_year': academic_year,
        'active_tab': active_tab,
        'sessions_data': sessions_data,
        'absences_data': absences_data,
        'absence_rate': round(absence_rate, 1),
        'is_blocked': is_blocked,
        'is_exempted': inscription.exemption_40,
    })

@login_required
@student_required
def student_courses(request):
    """
    Page "Mes Cours" - Liste de tous les cours de l'étudiant.
    """
    # Get current academic year
    academic_year = AnneeAcademique.objects.filter(active=True).first()
    if not academic_year:
        academic_year = AnneeAcademique.objects.order_by('-id_annee').first()

    # Get student's inscriptions
    if academic_year:
        inscriptions = Inscription.objects.filter(
            id_etudiant=request.user,
            id_annee=academic_year,
            status='EN_COURS'
        ).select_related('id_cours', 'id_cours__professeur', 'id_cours__id_departement', 'id_cours__id_departement__id_faculte')
    else:
        inscriptions = Inscription.objects.filter(
            id_etudiant=request.user
        ).select_related('id_cours', 'id_cours__professeur', 'id_cours__id_departement', 'id_cours__id_departement__id_faculte')

    # Prepare course data with statistics
    courses_data = []
    for ins in inscriptions:
        cours = ins.id_cours
        
        # Calculate NON_JUSTIFIED absences only
        total_abs = Absence.objects.filter(
            id_inscription=ins,
            statut='NON_JUSTIFIEE'
        ).aggregate(total=Sum('duree_absence'))['total'] or 0
        
        # Calculate absence rate
        absence_rate = (total_abs / cours.nombre_total_periodes) * 100 if cours.nombre_total_periodes > 0 else 0
        
        # Determine course status
        course_status = "OK"
        course_status_color = "success"
        if absence_rate >= 40 and not ins.exemption_40:
            course_status = "BLOQUÉ"
            course_status_color = "danger"
        elif absence_rate >= 30:
            course_status = "À RISQUE"
            course_status_color = "warning"
        
        # Count sessions and absences
        if academic_year:
            sessions_count = Seance.objects.filter(
                id_cours=cours,
                id_annee=academic_year
            ).count()
        else:
            sessions_count = Seance.objects.filter(id_cours=cours).count()
        
        absences_count = Absence.objects.filter(id_inscription=ins).count()
        
        # Get professor name
        prof_name = "Non assigné"
        if cours.professeur:
            prof_name = cours.professeur.get_full_name()

        courses_data.append({
            'inscription': ins,
            'course': cours,
            'code': cours.code_cours,
            'nom': cours.nom_cours,
            'professeur': prof_name,
            'sessions_count': sessions_count,
            'absences_count': absences_count,
            'total_abs': total_abs,
            'total_periods': cours.nombre_total_periodes,
            'absence_rate': round(absence_rate, 1),
            'status': course_status,
            'status_color': course_status_color,
            'is_exempted': ins.exemption_40,
        })

    return render(request, 'dashboard/student_courses.html', {
        'academic_year': academic_year,
        'courses_data': courses_data,
    })

@login_required
@student_required
def student_absences(request):
    """
    Page "Mes Absences" - Liste de toutes les absences de l'étudiant.
    """
    # Get current academic year
    academic_year = AnneeAcademique.objects.filter(active=True).first()
    if not academic_year:
        academic_year = AnneeAcademique.objects.order_by('-id_annee').first()

    # Get all inscriptions
    if academic_year:
        inscriptions = Inscription.objects.filter(
            id_etudiant=request.user,
            id_annee=academic_year,
            status='EN_COURS'
        )
    else:
        inscriptions = Inscription.objects.filter(id_etudiant=request.user)

    # Get all absences
    absences = Absence.objects.filter(
        id_inscription__in=inscriptions
    ).select_related(
        'id_seance', 'id_seance__id_cours', 'id_inscription'
    ).order_by('-id_seance__date_seance', '-id_seance__heure_debut')

    # Prepare absence data with justification status
    absences_data = []
    for absence in absences:
        justification = Justification.objects.filter(id_absence=absence).first()
        
        if justification:
            if justification.state == 'ACCEPTEE':
                status = "JUSTIFIÉE"
                status_color = "success"
            elif justification.state == 'REFUSEE':
                status = "NON JUSTIFIÉE"
                status_color = "danger"
            else:  # EN_ATTENTE
                status = "EN ATTENTE"
                status_color = "warning"
        else:
            if absence.statut == 'JUSTIFIEE':
                status = "JUSTIFIÉE"
                status_color = "success"
            else:
                status = "NON JUSTIFIÉE"
                status_color = "danger"
        
        # Can submit justification only if UNJUSTIFIED or PENDING (and no existing justification)
        can_submit = (status == "NON JUSTIFIÉE" or status == "EN ATTENTE") and not justification
        
        absences_data.append({
            'absence': absence,
            'status': status,
            'status_color': status_color,
            'justification': justification,
            'can_submit': can_submit,
        })

    return render(request, 'dashboard/student_absences.html', {
        'academic_year': academic_year,
        'absences_data': absences_data,
    })

@login_required
@student_required
def student_reports(request):
    """
    Page "Rapports" - Téléchargement des rapports PDF.
    """
    # Get current academic year
    academic_year = AnneeAcademique.objects.filter(active=True).first()
    if not academic_year:
        academic_year = AnneeAcademique.objects.order_by('-id_annee').first()

    # Get student's inscriptions for statistics
    if academic_year:
        inscriptions = Inscription.objects.filter(
            id_etudiant=request.user,
            id_annee=academic_year,
            status='EN_COURS'
        )
    else:
        inscriptions = Inscription.objects.filter(id_etudiant=request.user)

    # Calculate overall statistics
    total_courses = inscriptions.count()
    total_absences = Absence.objects.filter(id_inscription__in=inscriptions).count()
    
    total_abs_hours = 0
    total_periods = 0
    for ins in inscriptions:
        cours = ins.id_cours
        total_periods += cours.nombre_total_periodes
        abs_hours = Absence.objects.filter(
            id_inscription=ins,
            statut='NON_JUSTIFIEE'
        ).aggregate(total=Sum('duree_absence'))['total'] or 0
        total_abs_hours += abs_hours
    
    overall_rate = (total_abs_hours / total_periods * 100) if total_periods > 0 else 0

    return render(request, 'dashboard/student_reports.html', {
        'academic_year': academic_year,
        'total_courses': total_courses,
        'total_absences': total_absences,
        'overall_rate': round(overall_rate, 1),
    })
