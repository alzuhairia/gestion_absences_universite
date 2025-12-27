from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.contrib.admin.models import LogEntry
from django.db.models import Count, Q, Sum
from django.db import models as db_models
from django.db import IntegrityError, transaction, connection
from django.db.models.deletion import ProtectedError
from django.core.paginator import Paginator
from django.http import JsonResponse, HttpResponse
from django.views.decorators.http import require_http_methods
from django.utils import timezone
from datetime import datetime, timedelta
import csv
import logging

logger = logging.getLogger(__name__)

from apps.accounts.models import User
from apps.academics.models import Faculte, Departement, Cours
from apps.academic_sessions.models import AnneeAcademique
from apps.enrollments.models import Inscription
from apps.absences.models import Absence, Justification
from apps.audits.models import LogAudit
from apps.messaging.models import Message
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
    
    # KPI 4: Nombre de cours actifs
    # Pour le dashboard admin, on compte tous les cours actifs (configurés et prêts à être utilisés)
    # Un cours est considéré comme "actif" s'il est marqué comme actif dans le système
    active_courses = Cours.objects.filter(actif=True).count()
    
    # Optionnel : Compter aussi les cours avec professeur assigné ET utilisés dans l'année active
    # (pour avoir une vue plus détaillée)
    if academic_year:
        active_courses_with_activity = Cours.objects.filter(
            actif=True,
            professeur__isnull=False
        ).filter(
            Q(id_cours__in=Inscription.objects.filter(id_annee=academic_year).values_list('id_cours', flat=True)) |
            Q(id_cours__in=academic_year.seances.values_list('id_cours', flat=True))
        ).distinct().count()
    else:
        active_courses_with_activity = 0
    
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
@require_http_methods(["POST"])
def admin_faculty_delete(request, faculte_id):
    """Suppression d'une faculté avec suppression en cascade des départements et cours"""
    
    faculte = get_object_or_404(Faculte, id_faculte=faculte_id)
    faculte_nom = faculte.nom_faculte
    
    try:
        # Récupérer tous les départements de cette faculté
        departements = Departement.objects.filter(id_faculte=faculte)
        departements_count = departements.count()
        
        # Compteurs pour les éléments supprimés en cascade
        cours_count = 0
        inscriptions_count = 0
        seances_count = 0
        absences_count = 0
        justifications_count = 0
        
        # Si la faculté a des départements, supprimer en cascade
        if departements_count > 0:
            # Pour chaque département, supprimer ses cours et leurs dépendances
            for departement in departements:
                # Récupérer tous les cours de ce département
                cours = Cours.objects.filter(id_departement=departement)
                cours_count += cours.count()
                
                # Pour chaque cours, supprimer les dépendances
                for cours_item in cours:
                    # Supprimer les inscriptions liées à ce cours
                    from apps.enrollments.models import Inscription
                    inscriptions = Inscription.objects.filter(id_cours=cours_item)
                    inscriptions_count += inscriptions.count()
                    
                    # Pour chaque inscription, supprimer les absences et justifications
                    for inscription in inscriptions:
                        # Récupérer les absences liées à cette inscription
                        absences = Absence.objects.filter(id_inscription=inscription)
                        absences_count += absences.count()
                        
                        # Supprimer les justifications liées à ces absences
                        for absence in absences:
                            justif_count = Justification.objects.filter(id_absence=absence).count()
                            if justif_count > 0:
                                justifications_count += justif_count
                                Justification.objects.filter(id_absence=absence).delete()
                        
                        # Supprimer les absences
                        absences.delete()
                    
                    # Supprimer les inscriptions
                    inscriptions.delete()
                    
                    # Supprimer les séances liées à ce cours
                    from apps.academic_sessions.models import Seance
                    seances = Seance.objects.filter(id_cours=cours_item)
                    seances_count += seances.count()
                    seances.delete()
                
                # Supprimer les cours du département
                cours.delete()
            
            # Supprimer les départements
            departements.delete()
        
        # Supprimer la faculté
        faculte.delete()
        
        # Construire le message de cascade
        cascade_info = []
        if departements_count > 0:
            cascade_info.append(f"{departements_count} département(s)")
        if cours_count > 0:
            cascade_info.append(f"{cours_count} cours")
        if inscriptions_count > 0:
            cascade_info.append(f"{inscriptions_count} inscription(s)")
        if seances_count > 0:
            cascade_info.append(f"{seances_count} séance(s)")
        if absences_count > 0:
            cascade_info.append(f"{absences_count} absence(s)")
        if justifications_count > 0:
            cascade_info.append(f"{justifications_count} justification(s)")
        
        cascade_msg = f" (suppression en cascade: {', '.join(cascade_info)})" if cascade_info else ""
        
        # Journaliser la suppression
        log_action(
            request.user,
            f"CRITIQUE: Suppression de la faculté '{faculte_nom}' (ID: {faculte_id}){cascade_msg} - Configuration système",
            request,
            niveau='CRITIQUE',
            objet_type='FACULTE',
            objet_id=faculte_id
        )
        
        success_msg = f"Faculté '{faculte_nom}' supprimée avec succès."
        if cascade_info:
            success_msg += f" Suppression en cascade effectuée : {', '.join(cascade_info)}."
        messages.success(request, success_msg)
        
    except ProtectedError as e:
        # Gérer les erreurs PROTECT
        protected_objects = []
        for obj in e.protected_objects:
            protected_objects.append(str(obj))
        
        logger.error(f"ProtectedError lors de la suppression de la faculté {faculte_nom}: {e}")
        messages.error(
            request,
            f"Impossible de supprimer la faculté '{faculte_nom}'. "
            f"Dépendances trouvées : {', '.join(protected_objects)}. "
            f"Veuillez d'abord supprimer ou modifier ces éléments."
        )
    except Exception as e:
        logger.error(f"Erreur lors de la suppression de la faculté {faculte_nom}: {e}", exc_info=True)
        messages.error(
            request,
            f"Erreur lors de la suppression de la faculté '{faculte_nom}'. "
            f"Veuillez vérifier les dépendances ou contacter l'administrateur système."
        )
    
    return redirect('dashboard:admin_faculties')


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
@require_http_methods(["POST"])
def admin_department_delete(request, dept_id):
    """Suppression d'un département avec suppression en cascade des cours"""
    
    dept = get_object_or_404(Departement, id_departement=dept_id)
    dept_nom = dept.nom_departement
    faculte_nom = dept.id_faculte.nom_faculte
    
    try:
        # Récupérer tous les cours de ce département
        cours = Cours.objects.filter(id_departement=dept)
        cours_count = cours.count()
        
        # Compteurs pour les éléments supprimés en cascade
        inscriptions_count = 0
        seances_count = 0
        absences_count = 0
        justifications_count = 0
        
        # Si le département a des cours, supprimer en cascade
        if cours_count > 0:
            # Pour chaque cours, supprimer ses dépendances
            for cours_item in cours:
                # Supprimer les inscriptions liées à ce cours
                inscriptions = Inscription.objects.filter(id_cours=cours_item)
                inscriptions_count += inscriptions.count()
                
                # Pour chaque inscription, supprimer les absences et justifications
                for inscription in inscriptions:
                    # Récupérer les absences liées à cette inscription
                    absences = Absence.objects.filter(id_inscription=inscription)
                    absences_count += absences.count()
                    
                    # Supprimer les justifications liées à ces absences
                    for absence in absences:
                        justif_count = Justification.objects.filter(id_absence=absence).count()
                        if justif_count > 0:
                            justifications_count += justif_count
                            Justification.objects.filter(id_absence=absence).delete()
                    
                    # Supprimer les absences
                    absences.delete()
                
                # Supprimer les inscriptions
                inscriptions.delete()
                
                # Supprimer les séances liées à ce cours
                from apps.academic_sessions.models import Seance
                seances = Seance.objects.filter(id_cours=cours_item)
                seances_count += seances.count()
                seances.delete()
            
            # Supprimer les cours du département
            cours.delete()
        
        # Supprimer le département
        dept.delete()
        
        # Construire le message de cascade
        cascade_info = []
        if cours_count > 0:
            cascade_info.append(f"{cours_count} cours")
        if inscriptions_count > 0:
            cascade_info.append(f"{inscriptions_count} inscription(s)")
        if seances_count > 0:
            cascade_info.append(f"{seances_count} séance(s)")
        if absences_count > 0:
            cascade_info.append(f"{absences_count} absence(s)")
        if justifications_count > 0:
            cascade_info.append(f"{justifications_count} justification(s)")
        
        cascade_msg = f" (suppression en cascade: {', '.join(cascade_info)})" if cascade_info else ""
        
        # Journaliser la suppression
        log_action(
            request.user,
            f"CRITIQUE: Suppression du département '{dept_nom}' (Faculté: {faculte_nom}, ID: {dept_id}){cascade_msg} - Configuration système",
            request,
            niveau='CRITIQUE',
            objet_type='DEPARTEMENT',
            objet_id=dept_id
        )
        
        success_msg = f"Département '{dept_nom}' supprimé avec succès."
        if cascade_info:
            success_msg += f" Suppression en cascade effectuée : {', '.join(cascade_info)}."
        messages.success(request, success_msg)
        
    except ProtectedError as e:
        # Gérer les erreurs PROTECT
        protected_objects = []
        for obj in e.protected_objects:
            protected_objects.append(str(obj))
        
        logger.error(f"ProtectedError lors de la suppression du département {dept_nom}: {e}")
        messages.error(
            request,
            f"Impossible de supprimer le département '{dept_nom}'. "
            f"Dépendances trouvées : {', '.join(protected_objects)}. "
            f"Veuillez d'abord supprimer ou modifier ces éléments."
        )
    except Exception as e:
        logger.error(f"Erreur lors de la suppression du département {dept_nom}: {e}", exc_info=True)
        messages.error(
            request,
            f"Erreur lors de la suppression du département '{dept_nom}'. "
            f"Veuillez vérifier les dépendances ou contacter l'administrateur système."
        )
    
    return redirect('dashboard:admin_departments')


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


@admin_required
@require_http_methods(["POST"])
def admin_course_delete(request, course_id):
    """Suppression d'un cours avec suppression en cascade des inscriptions et absences"""
    
    cours = get_object_or_404(Cours, id_cours=course_id)
    cours_code = cours.code_cours
    cours_nom = cours.nom_cours
    dept_nom = cours.id_departement.nom_departement
    
    try:
        # Compteurs pour les éléments supprimés en cascade
        inscriptions_count = 0
        seances_count = 0
        absences_count = 0
        justifications_count = 0
        
        # Supprimer les inscriptions liées à ce cours
        inscriptions = Inscription.objects.filter(id_cours=cours)
        inscriptions_count = inscriptions.count()
        
        # Pour chaque inscription, supprimer les absences et justifications
        for inscription in inscriptions:
            # Récupérer les absences liées à cette inscription
            absences = Absence.objects.filter(id_inscription=inscription)
            absences_count += absences.count()
            
            # Supprimer les justifications liées à ces absences
            for absence in absences:
                justif_count = Justification.objects.filter(id_absence=absence).count()
                if justif_count > 0:
                    justifications_count += justif_count
                    Justification.objects.filter(id_absence=absence).delete()
            
            # Supprimer les absences
            absences.delete()
        
        # Supprimer les inscriptions
        inscriptions.delete()
        
        # Supprimer les séances liées à ce cours
        from apps.academic_sessions.models import Seance
        seances = Seance.objects.filter(id_cours=cours)
        seances_count = seances.count()
        seances.delete()
        
        # Supprimer le cours
        cours.delete()
        
        # Construire le message de cascade
        cascade_info = []
        if inscriptions_count > 0:
            cascade_info.append(f"{inscriptions_count} inscription(s)")
        if seances_count > 0:
            cascade_info.append(f"{seances_count} séance(s)")
        if absences_count > 0:
            cascade_info.append(f"{absences_count} absence(s)")
        if justifications_count > 0:
            cascade_info.append(f"{justifications_count} justification(s)")
        
        cascade_msg = f" (suppression en cascade: {', '.join(cascade_info)})" if cascade_info else ""
        
        # Journaliser la suppression
        log_action(
            request.user,
            f"CRITIQUE: Suppression du cours '{cours_code} - {cours_nom}' (Département: {dept_nom}, ID: {course_id}){cascade_msg} - Configuration système",
            request,
            niveau='CRITIQUE',
            objet_type='COURS',
            objet_id=course_id
        )
        
        success_msg = f"Cours '{cours_code}' supprimé avec succès."
        if cascade_info:
            success_msg += f" Suppression en cascade effectuée : {', '.join(cascade_info)}."
        messages.success(request, success_msg)
        
    except ProtectedError as e:
        # Gérer les erreurs PROTECT
        protected_objects = []
        for obj in e.protected_objects:
            protected_objects.append(str(obj))
        
        logger.error(f"ProtectedError lors de la suppression du cours {cours_code}: {e}")
        messages.error(
            request,
            f"Impossible de supprimer le cours '{cours_code}'. "
            f"Dépendances trouvées : {', '.join(protected_objects)}. "
            f"Veuillez d'abord supprimer ou modifier ces éléments."
        )
    except Exception as e:
        logger.error(f"Erreur lors de la suppression du cours {cours_code}: {e}", exc_info=True)
        messages.error(
            request,
            f"Erreur lors de la suppression du cours '{cours_code}'. "
            f"Veuillez vérifier les dépendances ou contacter l'administrateur système."
        )
    
    return redirect('dashboard:admin_courses')


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
        'editing_user': None,  # Pas d'utilisateur en cours d'édition lors de la création
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
        'editing_user': user,  # Utilisateur en cours d'édition
        'title': f"Modifier l'utilisateur {user.get_full_name()}",
    })


@admin_required
@require_http_methods(["POST"])
def admin_user_reset_password(request, user_id):
    """Réinitialisation du mot de passe d'un utilisateur"""
    
    user = get_object_or_404(User, id_utilisateur=user_id)
    
    new_password = request.POST.get('new_password')
    if new_password:
        if len(new_password) < 8:
            messages.error(request, "Le mot de passe doit contenir au moins 8 caractères.")
            return redirect('dashboard:admin_user_edit', user_id=user_id)
        
        user.set_password(new_password)
        # Forcer l'utilisateur à changer son mot de passe à la prochaine connexion
        user.must_change_password = True
        user.save()
        log_action(
            request.user, 
            f"CRITIQUE: Réinitialisation du mot de passe pour '{user.email}' (Gestion des utilisateurs - Action de sécurité)", 
            request,
            niveau='CRITIQUE',
            objet_type='USER',
            objet_id=user.id_utilisateur
        )
        messages.success(
            request, 
            f"Mot de passe réinitialisé pour '{user.email}'. L'utilisateur devra le changer lors de sa prochaine connexion."
        )
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


@admin_required
@require_http_methods(["POST"])
def admin_users_delete_multiple(request):
    """Suppression multiple d'utilisateurs avec vérifications de sécurité"""
    
    try:
        user_ids = request.POST.getlist('user_ids')
        
        if not user_ids:
            messages.error(request, "Aucun utilisateur sélectionné.")
            return redirect('dashboard:admin_users')
        
        deleted_count = 0
        failed_count = 0
        errors = []
        
        for user_id in user_ids:
            try:
                user = User.objects.get(id_utilisateur=user_id)
                
                # Vérification 1: Ne pas supprimer soi-même
                if user == request.user:
                    errors.append(f"Vous ne pouvez pas supprimer votre propre compte ({user.email})")
                    failed_count += 1
                    continue
                
                # Vérification 2: Vérifier les dépendances qui empêchent la suppression
                dependencies = []
                
                # Vérifier les inscriptions (PROTECT) - on peut les supprimer en cascade
                inscriptions_count = Inscription.objects.filter(id_etudiant=user).count()
                
                # Vérifier les absences encodées (PROTECT) - on peut les supprimer en cascade
                absences_encoded_count = Absence.objects.filter(encodee_par=user).count()
                
                # Compteurs pour les justifications supprimées
                justifications_deleted_count = 0
                
                # Si l'utilisateur a des inscriptions, on les supprime d'abord (cascade)
                if inscriptions_count > 0:
                    # Supprimer les inscriptions et leurs absences associées
                    inscriptions = Inscription.objects.filter(id_etudiant=user)
                    for inscription in inscriptions:
                        # Récupérer les absences liées à cette inscription
                        absences = Absence.objects.filter(id_inscription=inscription)
                        # Supprimer d'abord les justifications liées à ces absences
                        for absence in absences:
                            justif_count = Justification.objects.filter(id_absence=absence).count()
                            if justif_count > 0:
                                justifications_deleted_count += justif_count
                                Justification.objects.filter(id_absence=absence).delete()
                        # Puis supprimer les absences
                        absences.delete()
                    # Supprimer les inscriptions
                    inscriptions.delete()
                
                # Si l'utilisateur a encodé des absences, on les supprime
                if absences_encoded_count > 0:
                    # Récupérer les absences encodées par l'utilisateur
                    absences_encoded = Absence.objects.filter(encodee_par=user)
                    # Supprimer d'abord les justifications liées à ces absences
                    for absence in absences_encoded:
                        justif_count = Justification.objects.filter(id_absence=absence).count()
                        if justif_count > 0:
                            justifications_deleted_count += justif_count
                            Justification.objects.filter(id_absence=absence).delete()
                    # Puis supprimer les absences
                    absences_encoded.delete()
                
                # Sauvegarder les informations AVANT la suppression
                user_email = user.email
                user_name = user.get_full_name()
                user_role = user.get_role_display()
                user_id_for_log = user.id_utilisateur
                
                # Vérifier les cours assignés (SET_NULL)
                cours_count = Cours.objects.filter(professeur=user).count()
                if cours_count > 0:
                    Cours.objects.filter(professeur=user).update(professeur=None)
                
                # Supprimer les logs d'audit AVANT de supprimer l'utilisateur
                audit_logs_count = LogAudit.objects.filter(id_utilisateur=user).count()
                if audit_logs_count > 0:
                    LogAudit.objects.filter(id_utilisateur=user).delete()
                
                # Supprimer les logs de l'admin Django (django_admin_log)
                admin_logs_count = LogEntry.objects.filter(user=user).count()
                if admin_logs_count > 0:
                    LogEntry.objects.filter(user=user).delete()
                
                # Supprimer les messages où l'utilisateur est expéditeur ou destinataire
                messages_count = Message.objects.filter(
                    Q(expediteur=user) | Q(destinataire=user)
                ).count()
                if messages_count > 0:
                    Message.objects.filter(
                        Q(expediteur=user) | Q(destinataire=user)
                    ).delete()
                
                # Supprimer l'utilisateur directement via SQL
                with connection.cursor() as cursor:
                    cursor.execute(
                        "DELETE FROM utilisateur WHERE id_utilisateur = %s",
                        [user.id_utilisateur]
                    )
                
                # Vérifier que la suppression a réussi
                if User.objects.filter(id_utilisateur=user.id_utilisateur).exists():
                    errors.append(f"Échec de la suppression de '{user_email}'")
                    failed_count += 1
                    continue
                
                # Journaliser APRÈS la suppression réussie
                cascade_info = []
                if inscriptions_count > 0:
                    cascade_info.append(f"{inscriptions_count} inscription(s)")
                if absences_encoded_count > 0:
                    cascade_info.append(f"{absences_encoded_count} absence(s) encodée(s)")
                if justifications_deleted_count > 0:
                    cascade_info.append(f"{justifications_deleted_count} justification(s)")
                
                cascade_msg = f" (suppression en cascade: {', '.join(cascade_info)})" if cascade_info else ""
                log_action(
                    request.user,
                    f"CRITIQUE: Suppression de l'utilisateur '{user_email}' (ID: {user_id_for_log}, Rôle: {user_role}, Nom: {user_name}){cascade_msg} - Suppression multiple",
                    request,
                    niveau='CRITIQUE',
                    objet_type='USER',
                    objet_id=user_id_for_log
                )
                
                deleted_count += 1
                
            except User.DoesNotExist:
                errors.append(f"Utilisateur avec ID {user_id} introuvable")
                failed_count += 1
            except Exception as e:
                logger.error(f"Erreur lors de la suppression de l'utilisateur {user_id}: {e}", exc_info=True)
                errors.append(f"Erreur lors de la suppression: {str(e)}")
                failed_count += 1
        
        # Messages de résultat
        if deleted_count > 0:
            messages.success(request, f"{deleted_count} utilisateur(s) supprimé(s) avec succès.")
        
        if failed_count > 0:
            error_msg = f"{failed_count} utilisateur(s) n'ont pas pu être supprimé(s)."
            if errors:
                error_msg += " Détails : " + " ; ".join(errors[:5])  # Limiter à 5 erreurs
            messages.error(request, error_msg)
        
        return redirect('dashboard:admin_users')
        
    except Exception as e:
        logger.error(f"Erreur lors de la suppression multiple: {e}", exc_info=True)
        messages.error(
            request, 
            f"Erreur lors de la suppression multiple : {str(e)}. "
            f"Veuillez vérifier les dépendances ou contacter l'administrateur système."
        )
        return redirect('dashboard:admin_users')


@admin_required
@require_http_methods(["POST"])
def admin_user_delete(request, user_id):
    """Suppression d'un utilisateur avec vérifications de sécurité"""
    
    try:
        user = get_object_or_404(User, id_utilisateur=user_id)
        
        # Vérification 1: Ne pas supprimer soi-même
        if user == request.user:
            messages.error(request, "Vous ne pouvez pas supprimer votre propre compte.")
            return redirect('dashboard:admin_users')
        
        # Vérification 2: Gérer les dépendances avant suppression
        # On supprime automatiquement les inscriptions et absences en cascade
        
        # Vérifier les inscriptions (PROTECT) - on les supprime en cascade
        inscriptions_count = Inscription.objects.filter(id_etudiant=user).count()
        
        # Vérifier les absences encodées (PROTECT) - on les supprime en cascade
        absences_encoded_count = Absence.objects.filter(encodee_par=user).count()
        
        # Vérifier les logs d'audit (PROTECT) - IMPORTANT: on les supprimera AVANT l'utilisateur
        # On ne bloque pas la suppression, on supprimera les logs d'audit d'abord
        audit_logs_count = LogAudit.objects.filter(id_utilisateur=user).count()
        
        # Vérifier les cours assignés (SET_NULL - pas bloquant mais à noter)
        cours_count = Cours.objects.filter(professeur=user).count()
        
        # Compteurs pour les justifications supprimées
        justifications_deleted_count = 0
        
        # Si l'utilisateur a des inscriptions, on les supprime d'abord (cascade)
        if inscriptions_count > 0:
            # Supprimer les inscriptions et leurs absences associées
            inscriptions = Inscription.objects.filter(id_etudiant=user)
            for inscription in inscriptions:
                # Récupérer les absences liées à cette inscription
                absences = Absence.objects.filter(id_inscription=inscription)
                # Supprimer d'abord les justifications liées à ces absences
                for absence in absences:
                    justif_count = Justification.objects.filter(id_absence=absence).count()
                    if justif_count > 0:
                        justifications_deleted_count += justif_count
                        Justification.objects.filter(id_absence=absence).delete()
                # Puis supprimer les absences
                absences.delete()
            # Supprimer les inscriptions
            inscriptions.delete()
            logger.info(f"Suppression en cascade de {inscriptions_count} inscription(s) pour l'utilisateur {user.email}")
            if justifications_deleted_count > 0:
                logger.info(f"Suppression en cascade de {justifications_deleted_count} justification(s) pour l'utilisateur {user.email}")
        
        # Si l'utilisateur a encodé des absences, on les supprime
        if absences_encoded_count > 0:
            # Récupérer les absences encodées par l'utilisateur
            absences_encoded = Absence.objects.filter(encodee_par=user)
            # Supprimer d'abord les justifications liées à ces absences
            for absence in absences_encoded:
                justif_count = Justification.objects.filter(id_absence=absence).count()
                if justif_count > 0:
                    justifications_deleted_count += justif_count
                    Justification.objects.filter(id_absence=absence).delete()
            # Puis supprimer les absences
            absences_encoded.delete()
            logger.info(f"Suppression en cascade de {absences_encoded_count} absence(s) encodée(s) pour l'utilisateur {user.email}")
            if justifications_deleted_count > 0:
                logger.info(f"Suppression en cascade de {justifications_deleted_count} justification(s) pour l'utilisateur {user.email}")
        
        # Sauvegarder les informations AVANT la suppression (pour le log et le message)
        user_email = user.email
        user_name = user.get_full_name()
        user_role = user.get_role_display()
        user_id_for_log = user.id_utilisateur
        
        # Si l'utilisateur est professeur, mettre à NULL les cours assignés
        if cours_count > 0:
            Cours.objects.filter(professeur=user).update(professeur=None)
        
        # IMPORTANT: Supprimer les logs d'audit AVANT de supprimer l'utilisateur
        # Car les logs ont PROTECT qui empêcherait la suppression de l'utilisateur
        # On supprime tous les logs d'audit où cet utilisateur est référencé
        if audit_logs_count > 0:
            LogAudit.objects.filter(id_utilisateur=user).delete()
        
        # Supprimer les logs de l'admin Django (django_admin_log)
        admin_logs_count = LogEntry.objects.filter(user=user).count()
        if admin_logs_count > 0:
            LogEntry.objects.filter(user=user).delete()
        
        # Supprimer les messages où l'utilisateur est expéditeur ou destinataire
        messages_count = Message.objects.filter(
            Q(expediteur=user) | Q(destinataire=user)
        ).count()
        if messages_count > 0:
            Message.objects.filter(
                Q(expediteur=user) | Q(destinataire=user)
            ).delete()
        
        # IMPORTANT: Supprimer l'utilisateur AVANT de journaliser
        # Car le log d'audit a une relation PROTECT qui empêcherait la suppression
        # Si la suppression réussit, on journalisera après
        try:
            # Supprimer l'utilisateur directement via SQL pour éviter les problèmes ManyToMany
            # Car PermissionsMixin ajoute des relations ManyToMany qui peuvent ne pas exister
            with connection.cursor() as cursor:
                # Supprimer directement l'utilisateur via SQL
                cursor.execute(
                    "DELETE FROM utilisateur WHERE id_utilisateur = %s",
                    [user.id_utilisateur]
                )
            
            # Vérifier que la suppression a réussi
            if User.objects.filter(id_utilisateur=user.id_utilisateur).exists():
                raise Exception("La suppression de l'utilisateur a échoué")
            
            # Journaliser APRÈS la suppression réussie (sans objet_id car l'utilisateur n'existe plus)
            # On utilise l'ID sauvegardé dans le message
            cascade_info = []
            if inscriptions_count > 0:
                cascade_info.append(f"{inscriptions_count} inscription(s)")
            if absences_encoded_count > 0:
                cascade_info.append(f"{absences_encoded_count} absence(s) encodée(s)")
            if justifications_deleted_count > 0:
                cascade_info.append(f"{justifications_deleted_count} justification(s)")
            
            cascade_msg = f" (suppression en cascade: {', '.join(cascade_info)})" if cascade_info else ""
            log_action(
                request.user,
                f"CRITIQUE: Suppression de l'utilisateur '{user_email}' (ID: {user_id_for_log}, Rôle: {user_role}, Nom: {user_name}){cascade_msg} - Gestion des utilisateurs",
                request,
                niveau='CRITIQUE',
                objet_type='USER',
                objet_id=user_id_for_log  # On garde l'ID pour référence historique
            )
            
            success_msg = f"Utilisateur '{user_email}' supprimé avec succès."
            if cascade_info:
                success_msg += f" Suppression en cascade effectuée : {', '.join(cascade_info)}."
            messages.success(request, success_msg)
            return redirect('dashboard:admin_users')
            
        except ProtectedError as e:
            # Gérer spécifiquement les erreurs PROTECT
            protected_objects = []
            for obj in e.protected_objects:
                protected_objects.append(str(obj))
            
            logger.error(f"ProtectedError lors de la suppression de l'utilisateur {user_email}: {e}")
            messages.error(
                request, 
                f"Impossible de supprimer l'utilisateur '{user_email}' car il est référencé par d'autres éléments du système. "
                f"Éléments protégés : {', '.join(protected_objects[:5])}. "
                f"Veuillez d'abord supprimer ou modifier ces éléments, ou désactiver le compte au lieu de le supprimer."
            )
            return redirect('dashboard:admin_users')
        except IntegrityError as e:
            # Gérer les erreurs d'intégrité référentielle
            logger.error(f"IntegrityError lors de la suppression de l'utilisateur {user_email}: {e}")
            messages.error(
                request, 
                f"Impossible de supprimer cet utilisateur car il est référencé par d'autres éléments du système. "
                f"Veuillez d'abord supprimer ou modifier ces éléments, ou désactiver le compte au lieu de le supprimer."
            )
            return redirect('dashboard:admin_users')
        except Exception as e:
            # Gérer toute autre exception inattendue
            logger.error(f"Exception lors de la suppression de l'utilisateur {user_email}: {e}", exc_info=True)
            messages.error(
                request, 
                f"Erreur lors de la suppression de l'utilisateur '{user_email}': {str(e)}. "
                f"Veuillez vérifier les dépendances ou contacter l'administrateur système."
            )
            return redirect('dashboard:admin_users')
        
    except Exception as e:
        # Gérer les exceptions lors de la récupération de l'utilisateur
        logger.error(f"Exception lors de la récupération de l'utilisateur {user_id}: {e}", exc_info=True)
        messages.error(
            request, 
            f"Erreur lors de la suppression de l'utilisateur : {str(e)}. "
            f"Veuillez vérifier les dépendances ou contacter l'administrateur système."
        )
        return redirect('dashboard:admin_users')


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


@admin_required
@require_http_methods(["POST"])
def admin_academic_year_delete(request, year_id):
    """Suppression d'une année académique avec suppression en cascade des inscriptions et séances"""
    
    year = get_object_or_404(AnneeAcademique, id_annee=year_id)
    year_libelle = year.libelle
    is_active = year.active
    
    try:
        # Compteurs pour les éléments supprimés en cascade
        inscriptions_count = 0
        seances_count = 0
        absences_count = 0
        justifications_count = 0
        
        # Vérifier si l'année est active
        if is_active:
            messages.error(
                request,
                f"Impossible de supprimer l'année académique '{year_libelle}' car elle est actuellement active. "
                f"Veuillez d'abord définir une autre année comme active."
            )
            return redirect('dashboard:admin_academic_years')
        
        # Supprimer les inscriptions liées à cette année
        inscriptions = Inscription.objects.filter(id_annee=year)
        inscriptions_count = inscriptions.count()
        
        # Pour chaque inscription, supprimer les absences et justifications
        for inscription in inscriptions:
            # Récupérer les absences liées à cette inscription
            absences = Absence.objects.filter(id_inscription=inscription)
            absences_count += absences.count()
            
            # Supprimer les justifications liées à ces absences
            for absence in absences:
                justif_count = Justification.objects.filter(id_absence=absence).count()
                if justif_count > 0:
                    justifications_count += justif_count
                    Justification.objects.filter(id_absence=absence).delete()
            
            # Supprimer les absences
            absences.delete()
        
        # Supprimer les inscriptions
        inscriptions.delete()
        
        # Supprimer les séances liées à cette année
        from apps.academic_sessions.models import Seance
        seances = Seance.objects.filter(id_annee=year)
        seances_count = seances.count()
        seances.delete()
        
        # Supprimer l'année académique
        year.delete()
        
        # Construire le message de cascade
        cascade_info = []
        if inscriptions_count > 0:
            cascade_info.append(f"{inscriptions_count} inscription(s)")
        if seances_count > 0:
            cascade_info.append(f"{seances_count} séance(s)")
        if absences_count > 0:
            cascade_info.append(f"{absences_count} absence(s)")
        if justifications_count > 0:
            cascade_info.append(f"{justifications_count} justification(s)")
        
        cascade_msg = f" (suppression en cascade: {', '.join(cascade_info)})" if cascade_info else ""
        
        # Journaliser la suppression
        log_action(
            request.user,
            f"CRITIQUE: Suppression de l'année académique '{year_libelle}' (ID: {year_id}){cascade_msg} - Configuration système",
            request,
            niveau='CRITIQUE',
            objet_type='AUTRE',
            objet_id=year_id
        )
        
        success_msg = f"Année académique '{year_libelle}' supprimée avec succès."
        if cascade_info:
            success_msg += f" Suppression en cascade effectuée : {', '.join(cascade_info)}."
        messages.success(request, success_msg)
        
    except ProtectedError as e:
        # Gérer les erreurs PROTECT
        protected_objects = []
        for obj in e.protected_objects:
            protected_objects.append(str(obj))
        
        logger.error(f"ProtectedError lors de la suppression de l'année académique {year_libelle}: {e}")
        messages.error(
            request,
            f"Impossible de supprimer l'année académique '{year_libelle}'. "
            f"Dépendances trouvées : {', '.join(protected_objects)}. "
            f"Veuillez d'abord supprimer ou modifier ces éléments."
        )
    except Exception as e:
        logger.error(f"Erreur lors de la suppression de l'année académique {year_libelle}: {e}", exc_info=True)
        messages.error(
            request,
            f"Erreur lors de la suppression de l'année académique '{year_libelle}'. "
            f"Veuillez vérifier les dépendances ou contacter l'administrateur système."
        )
    
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

