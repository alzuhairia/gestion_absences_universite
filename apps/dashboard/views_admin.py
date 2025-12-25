from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Count, Q, Sum
from django.core.paginator import Paginator
from django.http import JsonResponse, HttpResponse
from django.views.decorators.http import require_http_methods
from django.utils import timezone
from datetime import datetime, timedelta
import csv

from apps.accounts.models import User
from apps.academics.models import Faculte, Departement, Cours
from apps.academic_sessions.models import AnneeAcademique
from apps.enrollments.models import Inscription
from apps.absences.models import Absence
from apps.audits.models import LogAudit
from apps.audits.utils import log_action
from apps.dashboard.models import SystemSettings
from apps.dashboard.forms_admin import (
    FaculteForm, DepartementForm, CoursForm,
    UserForm, SystemSettingsForm, AnneeAcademiqueForm
)
from apps.dashboard.decorators import admin_required


def is_admin(user):
    """
    Vérifie si l'utilisateur est un administrateur.
    IMPORTANT: Séparé de is_secretary() pour éviter la confusion des rôles.
    """
    return user.is_authenticated and user.role == User.Role.ADMIN


@admin_required
def admin_dashboard_main(request):
    """
    Tableau de bord principal de l'administrateur avec KPIs et vue d'ensemble.
    IMPORTANT: L'administrateur configure et audite, il ne gère PAS les opérations quotidiennes.
    """
    
    # Récupérer l'année académique active
    academic_year = AnneeAcademique.objects.filter(active=True).first()
    
    # KPI 1: Nombre total d'étudiants
    total_students = User.objects.filter(role=User.Role.ETUDIANT, actif=True).count()
    
    # KPI 2: Nombre total de professeurs
    total_professors = User.objects.filter(role=User.Role.PROFESSEUR, actif=True).count()
    
    # KPI 3: Nombre de secrétaires
    total_secretaries = User.objects.filter(role=User.Role.SECRETAIRE, actif=True).count()
    
    # KPI 4: Nombre de cours actifs (année en cours)
    if academic_year:
        active_courses = Cours.objects.filter(
            actif=True,
            professeur__isnull=False
        ).filter(
            Q(id_cours__in=Inscription.objects.filter(id_annee=academic_year).values_list('id_cours', flat=True)) |
            Q(id_cours__in=academic_year.seances.values_list('id_cours', flat=True))
        ).distinct().count()
    else:
        active_courses = 0
    
    # KPI 5: Nombre d'alertes système (étudiants à risque > 40%)
    at_risk_count = 0
    all_inscriptions = Inscription.objects.select_related('id_cours', 'id_etudiant').all()
    for ins in all_inscriptions:
        cours = ins.id_cours
        if cours.nombre_total_periodes > 0:
            total_abs = Absence.objects.filter(
                id_inscription=ins,
                statut='NON_JUSTIFIEE'
            ).aggregate(total=Sum('duree_absence'))['total'] or 0
            rate = (total_abs / cours.nombre_total_periodes) * 100
            if rate >= 40 and not ins.exemption_40:
                at_risk_count += 1
    
    # KPI 6: Nombre d'actions critiques (journaux d'audit des 7 derniers jours)
    seven_days_ago = timezone.now() - timedelta(days=7)
    critical_actions = LogAudit.objects.filter(
        date_action__gte=seven_days_ago,
        niveau='CRITIQUE'
    ).count()
    
    # KPI 7: Total d'inscriptions actives
    if academic_year:
        total_inscriptions = Inscription.objects.filter(id_annee=academic_year).count()
    else:
        total_inscriptions = 0
    
    # KPI 8: Total d'absences enregistrées (année active)
    if academic_year:
        total_absences = Absence.objects.filter(
            id_inscription__id_annee=academic_year
        ).count()
    else:
        total_absences = 0
    
    # Journaux d'audit récents
    recent_audits = LogAudit.objects.select_related('id_utilisateur').order_by('-date_action')[:10]
    
    # Paramètres système
    settings = SystemSettings.get_settings()
    
    context = {
        'total_students': total_students,
        'total_professors': total_professors,
        'total_secretaries': total_secretaries,
        'active_courses': active_courses,
        'system_alerts': at_risk_count,
        'critical_actions': critical_actions,
        'total_inscriptions': total_inscriptions,
        'total_absences': total_absences,
        'recent_audits': recent_audits,
        'academic_year': academic_year,
        'settings': settings,
    }
    
    return render(request, 'dashboard/admin_dashboard.html', context)


# ========== GESTION DE LA STRUCTURE ACADÉMIQUE ==========

@admin_required
@require_http_methods(["GET", "POST"])
def admin_faculties(request):
    """Liste et création de facultés"""
    
    if request.method == 'POST':
        form = FaculteForm(request.POST)
        if form.is_valid():
            faculte = form.save()
            log_action(
                request.user, 
                f"CRITIQUE: Création de la faculté '{faculte.nom_faculte}' (Configuration système)", 
                request,
                niveau='CRITIQUE',
                objet_type='FACULTE',
                objet_id=faculte.id_faculte
            )
            messages.success(request, f"Faculté '{faculte.nom_faculte}' créée avec succès.")
            return redirect('dashboard:admin_faculties')
    else:
        form = FaculteForm()
    
    faculties = Faculte.objects.all().order_by('nom_faculte')
    
    return render(request, 'dashboard/admin_faculties.html', {
        'faculties': faculties,
        'form': form,
    })


@admin_required
@require_http_methods(["GET", "POST"])
def admin_faculty_edit(request, faculte_id):
    """Modification ou désactivation d'une faculté"""
    
    faculte = get_object_or_404(Faculte, id_faculte=faculte_id)
    
    if request.method == 'POST':
        form = FaculteForm(request.POST, instance=faculte)
        if form.is_valid():
            old_name = faculte.nom_faculte
            faculte = form.save()
            action = "modifiée" if faculte.actif else "désactivée"
            log_action(
                request.user, 
                f"CRITIQUE: Faculté '{old_name}' {action} (Configuration système - {'Activation' if faculte.actif else 'Désactivation'})", 
                request,
                niveau='CRITIQUE',
                objet_type='FACULTE',
                objet_id=faculte.id_faculte
            )
            messages.success(request, f"Faculté '{faculte.nom_faculte}' {action} avec succès.")
            return redirect('dashboard:admin_faculties')
    else:
        form = FaculteForm(instance=faculte)
    
    return render(request, 'dashboard/admin_faculty_edit.html', {
        'faculte': faculte,
        'form': form,
    })


@admin_required
@require_http_methods(["GET", "POST"])
def admin_departments(request):
    """Liste et création de départements"""
    
    if request.method == 'POST':
        form = DepartementForm(request.POST)
        if form.is_valid():
            dept = form.save()
            log_action(
                request.user, 
                f"CRITIQUE: Création du département '{dept.nom_departement}' dans la faculté '{dept.id_faculte.nom_faculte}' (Configuration système)", 
                request,
                niveau='CRITIQUE',
                objet_type='DEPARTEMENT',
                objet_id=dept.id_departement
            )
            messages.success(request, f"Département '{dept.nom_departement}' créé avec succès.")
            return redirect('dashboard:admin_departments')
    else:
        form = DepartementForm()
    
    departments = Departement.objects.select_related('id_faculte').all().order_by('id_faculte__nom_faculte', 'nom_departement')
    
    return render(request, 'dashboard/admin_departments.html', {
        'departments': departments,
        'form': form,
    })


@admin_required
@require_http_methods(["GET", "POST"])
def admin_department_edit(request, dept_id):
    """Modification ou désactivation d'un département"""
    
    dept = get_object_or_404(Departement, id_departement=dept_id)
    
    if request.method == 'POST':
        form = DepartementForm(request.POST, instance=dept)
        if form.is_valid():
            old_name = dept.nom_departement
            dept = form.save()
            action = "modifié" if dept.actif else "désactivé"
            log_action(
                request.user, 
                f"CRITIQUE: Département '{old_name}' {action} (Configuration système - {'Activation' if dept.actif else 'Désactivation'})", 
                request,
                niveau='CRITIQUE',
                objet_type='DEPARTEMENT',
                objet_id=dept.id_departement
            )
            messages.success(request, f"Département '{dept.nom_departement}' {action} avec succès.")
            return redirect('dashboard:admin_departments')
    else:
        form = DepartementForm(instance=dept)
    
    return render(request, 'dashboard/admin_department_edit.html', {
        'department': dept,
        'form': form,
    })


@admin_required
@require_http_methods(["GET", "POST"])
def admin_courses(request):
    """Liste et création de cours"""
    
    if request.method == 'POST':
        form = CoursForm(request.POST)
        if form.is_valid():
            cours = form.save()
            log_action(
                request.user, 
                f"CRITIQUE: Création du cours '{cours.code_cours} - {cours.nom_cours}' (Département: {cours.id_departement.nom_departement}, Seuil: {cours.get_seuil_absence()}%)", 
                request,
                niveau='CRITIQUE',
                objet_type='COURS',
                objet_id=cours.id_cours
            )
            messages.success(request, f"Cours '{cours.code_cours}' créé avec succès.")
            return redirect('dashboard:admin_courses')
    else:
        form = CoursForm()
    
    courses = Cours.objects.select_related('id_departement', 'id_departement__id_faculte', 'professeur').all().order_by('code_cours')
    
    # Pagination
    paginator = Paginator(courses, 20)
    page = request.GET.get('page')
    courses_page = paginator.get_page(page)
    
    return render(request, 'dashboard/admin_courses.html', {
        'courses': courses_page,
        'form': form,
    })


@admin_required
@require_http_methods(["GET", "POST"])
def admin_course_edit(request, course_id):
    """Modification ou désactivation d'un cours"""
    
    cours = get_object_or_404(Cours, id_cours=course_id)
    
    if request.method == 'POST':
        form = CoursForm(request.POST, instance=cours)
        if form.is_valid():
            old_code = cours.code_cours
            cours = form.save()
            action = "modifié" if cours.actif else "désactivé"
            log_action(
                request.user, 
                f"CRITIQUE: Cours '{old_code}' {action} (Configuration système - {'Activation' if cours.actif else 'Désactivation'})", 
                request,
                niveau='CRITIQUE',
                objet_type='COURS',
                objet_id=cours.id_cours
            )
            messages.success(request, f"Cours '{cours.code_cours}' {action} avec succès.")
            return redirect('dashboard:admin_courses')
    else:
        form = CoursForm(instance=cours)
    
    return render(request, 'dashboard/admin_course_edit.html', {
        'course': cours,
        'form': form,
    })


# ========== GESTION DES UTILISATEURS ==========

@admin_required
def admin_users(request):
    """Liste et gestion des utilisateurs"""
    
    # Filtres
    role_filter = request.GET.get('role', '')
    search_query = request.GET.get('q', '')
    active_filter = request.GET.get('active', '')
    
    users = User.objects.all()
    
    if role_filter:
        users = users.filter(role=role_filter)
    if search_query:
        users = users.filter(
            Q(nom__icontains=search_query) |
            Q(prenom__icontains=search_query) |
            Q(email__icontains=search_query)
        )
    if active_filter == 'true':
        users = users.filter(actif=True)
    elif active_filter == 'false':
        users = users.filter(actif=False)
    
    users = users.order_by('nom', 'prenom')
    
    # Pagination
    paginator = Paginator(users, 25)
    page = request.GET.get('page')
    users_page = paginator.get_page(page)
    
    return render(request, 'dashboard/admin_users.html', {
        'users': users_page,
        'role_filter': role_filter,
        'search_query': search_query,
        'active_filter': active_filter,
    })


@admin_required
@require_http_methods(["GET", "POST"])
def admin_user_create(request):
    """Création d'un nouvel utilisateur"""
    
    if request.method == 'POST':
        form = UserForm(request.POST)
        if form.is_valid():
            user = form.save()
            log_action(
                request.user, 
                f"CRITIQUE: Création de l'utilisateur '{user.email}' (Rôle: {user.get_role_display()}, Nom: {user.get_full_name()}) - Gestion des utilisateurs", 
                request,
                niveau='CRITIQUE',
                objet_type='USER',
                objet_id=user.id_utilisateur
            )
            messages.success(request, f"Utilisateur '{user.email}' créé avec succès.")
            return redirect('dashboard:admin_users')
    else:
        form = UserForm()
    
    return render(request, 'dashboard/admin_user_form.html', {
        'form': form,
        'title': 'Créer un utilisateur',
    })


@admin_required
@require_http_methods(["GET", "POST"])
def admin_user_edit(request, user_id):
    """Modification d'un utilisateur"""
    
    user = get_object_or_404(User, id_utilisateur=user_id)
    
    if request.method == 'POST':
        old_role = user.role
        old_active = user.actif
        form = UserForm(request.POST, instance=user)
        if form.is_valid():
            user = form.save()
            
            # Journaliser les changements de rôle
            if old_role != user.role:
                old_role_display = dict(User.Role.choices).get(old_role, old_role)
                log_action(
                    request.user, 
                    f"CRITIQUE: Modification du rôle de '{user.email}' de {old_role_display} à {user.get_role_display()} - Gestion des utilisateurs", 
                    request,
                    niveau='CRITIQUE',
                    objet_type='USER',
                    objet_id=user.id_utilisateur
                )
            if old_active != user.actif:
                action = "activé" if user.actif else "désactivé"
                log_action(
                    request.user, 
                    f"CRITIQUE: Compte '{user.email}' {action} (Gestion des utilisateurs - {'Réactivation' if user.actif else 'Désactivation'})", 
                    request,
                    niveau='CRITIQUE',
                    objet_type='USER',
                    objet_id=user.id_utilisateur
                )
            
            messages.success(request, f"Utilisateur '{user.email}' modifié avec succès.")
            return redirect('dashboard:admin_users')
    else:
        form = UserForm(instance=user)
    
    return render(request, 'dashboard/admin_user_form.html', {
        'form': form,
        'user': user,
        'title': f"Modifier l'utilisateur {user.get_full_name()}",
    })


@admin_required
@require_http_methods(["POST"])
def admin_user_reset_password(request, user_id):
    """Réinitialisation du mot de passe d'un utilisateur"""
    
    user = get_object_or_404(User, id_utilisateur=user_id)
    
    new_password = request.POST.get('new_password')
    if new_password:
        user.set_password(new_password)
        user.save()
        log_action(
            request.user, 
            f"CRITIQUE: Réinitialisation du mot de passe pour '{user.email}' (Gestion des utilisateurs - Action de sécurité)", 
            request,
            niveau='CRITIQUE',
            objet_type='USER',
            objet_id=user.id_utilisateur
        )
        messages.success(request, f"Mot de passe réinitialisé pour '{user.email}'.")
    else:
        messages.error(request, "Le mot de passe ne peut pas être vide.")
    
    return redirect('dashboard:admin_user_edit', user_id=user_id)


@admin_required
def admin_user_audit(request, user_id):
    """Consultation des journaux d'audit pour un utilisateur spécifique"""
    
    user = get_object_or_404(User, id_utilisateur=user_id)
    logs = LogAudit.objects.filter(id_utilisateur=user).order_by('-date_action')
    
    # Pagination
    paginator = Paginator(logs, 50)
    page = request.GET.get('page')
    logs_page = paginator.get_page(page)
    
    return render(request, 'dashboard/admin_user_audit.html', {
        'user': user,
        'logs': logs_page,
    })


# ========== PARAMÈTRES SYSTÈME ==========

@admin_required
@require_http_methods(["GET", "POST"])
def admin_settings(request):
    """Gestion des paramètres système globaux"""
    
    settings = SystemSettings.get_settings()
    
    if request.method == 'POST':
        old_threshold = settings.default_absence_threshold
        form = SystemSettingsForm(request.POST, instance=settings)
        if form.is_valid():
            settings = form.save(commit=False)
            settings.modified_by = request.user
            settings.save()
            
            # Journaliser les changements de seuil
            if old_threshold != settings.default_absence_threshold:
                log_action(
                    request.user, 
                    f"CRITIQUE: Modification du seuil d'absence par défaut de {old_threshold}% à {settings.default_absence_threshold}% (Paramètres système - Impact global)", 
                    request,
                    niveau='CRITIQUE',
                    objet_type='SYSTEM',
                    objet_id=1
                )
            
            log_action(
                request.user, 
                f"CRITIQUE: Modification des paramètres système (Seuil: {settings.default_absence_threshold}%, Blocage: {settings.get_block_type_display()})", 
                request,
                niveau='CRITIQUE',
                objet_type='SYSTEM',
                objet_id=1
            )
            messages.success(request, "Paramètres système mis à jour avec succès.")
            return redirect('dashboard:admin_settings')
    else:
        form = SystemSettingsForm(instance=settings)
    
    return render(request, 'dashboard/admin_settings.html', {
        'form': form,
        'settings': settings,
    })


# ========== GESTION DES ANNÉES ACADÉMIQUES ==========

@admin_required
def admin_academic_years(request):
    """Liste et gestion des années académiques"""
    
    if request.method == 'POST':
        form = AnneeAcademiqueForm(request.POST)
        if form.is_valid():
            year = form.save()
            log_action(
                request.user, 
                f"CRITIQUE: Création de l'année académique '{year.libelle}' (Configuration système - {'Année active' if year.active else 'Année inactive'})", 
                request,
                niveau='CRITIQUE',
                objet_type='AUTRE',
                objet_id=year.id_annee
            )
            messages.success(request, f"Année académique '{year.libelle}' créée avec succès.")
            return redirect('dashboard:admin_academic_years')
    else:
        form = AnneeAcademiqueForm()
    
    years = AnneeAcademique.objects.all().order_by('-libelle')
    
    return render(request, 'dashboard/admin_academic_years.html', {
        'years': years,
        'form': form,
    })


@admin_required
@require_http_methods(["POST"])
def admin_academic_year_set_active(request, year_id):
    """Définir une année académique comme active"""
    
    year = get_object_or_404(AnneeAcademique, id_annee=year_id)
    
    # Désactiver toutes les années
    AnneeAcademique.objects.update(active=False)
    
    # Activer l'année sélectionnée
    year.active = True
    year.save()
    
    log_action(
        request.user, 
        f"CRITIQUE: Année académique '{year.libelle}' définie comme active (Configuration système - Changement d'année académique)", 
        request,
        niveau='CRITIQUE',
        objet_type='AUTRE',
        objet_id=year.id_annee
    )
    messages.success(request, f"Année académique '{year.libelle}' définie comme active.")
    
    return redirect('dashboard:admin_academic_years')


# ========== JOURNAUX D'AUDIT ==========

@admin_required
def admin_audit_logs(request):
    """Consultation de tous les journaux d'audit avec filtres"""
    
    # Filtres
    role_filter = request.GET.get('role', '')
    action_filter = request.GET.get('action', '')
    date_from = request.GET.get('date_from', '')
    date_to = request.GET.get('date_to', '')
    user_filter = request.GET.get('user', '')
    search_query = request.GET.get('q', '')
    
    logs = LogAudit.objects.select_related('id_utilisateur').all()
    
    if role_filter:
        logs = logs.filter(id_utilisateur__role=role_filter)
    if action_filter:
        logs = logs.filter(action__icontains=action_filter)
    if date_from:
        logs = logs.filter(date_action__gte=date_from)
    if date_to:
        logs = logs.filter(date_action__lte=date_to)
    if user_filter:
        logs = logs.filter(
            Q(id_utilisateur__nom__icontains=user_filter) |
            Q(id_utilisateur__prenom__icontains=user_filter) |
            Q(id_utilisateur__email__icontains=user_filter)
        )
    if search_query:
        logs = logs.filter(action__icontains=search_query)
    
    logs = logs.order_by('-date_action')
    
    # Pagination
    paginator = Paginator(logs, 50)
    page = request.GET.get('page')
    logs_page = paginator.get_page(page)
    
    return render(request, 'dashboard/admin_audit_logs.html', {
        'logs': logs_page,
        'role_filter': role_filter,
        'action_filter': action_filter,
        'date_from': date_from,
        'date_to': date_to,
        'user_filter': user_filter,
        'search_query': search_query,
    })


# ========== EXPORTS ==========

@admin_required
def admin_export_audit_csv(request):
    """Export des journaux d'audit en CSV"""
    
    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="audit_logs_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv"'
    
    writer = csv.writer(response)
    writer.writerow(['Date/Heure', 'Utilisateur', 'Email', 'Rôle', 'Action', 'Adresse IP'])
    
    logs = LogAudit.objects.select_related('id_utilisateur').all().order_by('-date_action')
    
    # Appliquer les mêmes filtres que dans la vue
    role_filter = request.GET.get('role', '')
    action_filter = request.GET.get('action', '')
    date_from = request.GET.get('date_from', '')
    date_to = request.GET.get('date_to', '')
    
    if role_filter:
        logs = logs.filter(id_utilisateur__role=role_filter)
    if action_filter:
        logs = logs.filter(action__icontains=action_filter)
    if date_from:
        logs = logs.filter(date_action__gte=date_from)
    if date_to:
        logs = logs.filter(date_action__lte=date_to)
    
    for log in logs:
        writer.writerow([
            log.date_action.strftime('%Y-%m-%d %H:%M:%S'),
            f"{log.id_utilisateur.prenom} {log.id_utilisateur.nom}",
            log.id_utilisateur.email,
            log.id_utilisateur.get_role_display(),
            log.action,
            log.adresse_ip,
        ])
    
    log_action(
        request.user, 
        "Export des journaux d'audit (CSV)", 
        request,
        niveau='INFO',
        objet_type='SYSTEM'
    )
    return response

