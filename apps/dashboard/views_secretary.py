"""
Vues pour la gestion de la structure académique par le secrétaire.
Le secrétaire a accès complet à la structure académique (facultés, départements, cours, années académiques).
"""
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.views.decorators.http import require_http_methods
from django.core.paginator import Paginator
from django.db.models import Q
from django.db import transaction
from django.db.models.deletion import ProtectedError
import logging

from apps.academics.models import Faculte, Departement, Cours
from apps.academic_sessions.models import AnneeAcademique
from apps.enrollments.models import Inscription
from apps.absences.models import Absence, Justification
from apps.dashboard.forms_admin import FaculteForm, DepartementForm, CoursForm, AnneeAcademiqueForm
from apps.dashboard.decorators import secretary_required
from apps.audits.utils import log_action
from apps.audits.models import LogAudit

logger = logging.getLogger(__name__)


# ========== GESTION DES FACULTÉS ==========

@secretary_required
@require_http_methods(["GET", "POST"])
def secretary_faculties(request):
    """Liste et création de facultés"""
    
    if request.method == 'POST':
        form = FaculteForm(request.POST)
        if form.is_valid():
            faculte = form.save()
            log_action(
                request.user, 
                f"CRITIQUE: Création de la faculté '{faculte.nom_faculte}' (Gestion structure académique - Secrétaire)", 
                request,
                niveau='CRITIQUE',
                objet_type='FACULTE',
                objet_id=faculte.id_faculte
            )
            messages.success(request, f"Faculté '{faculte.nom_faculte}' créée avec succès.")
            return redirect('dashboard:secretary_faculties')
    else:
        form = FaculteForm()
    
    faculties = Faculte.objects.all().order_by('nom_faculte')
    
    return render(request, 'dashboard/secretary_faculties.html', {
        'faculties': faculties,
        'form': form,
    })


@secretary_required
@require_http_methods(["GET", "POST"])
def secretary_faculty_edit(request, faculte_id):
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
                f"CRITIQUE: Faculté '{old_name}' {action} (Gestion structure académique - Secrétaire)", 
                request,
                niveau='CRITIQUE',
                objet_type='FACULTE',
                objet_id=faculte.id_faculte
            )
            messages.success(request, f"Faculté '{faculte.nom_faculte}' {action} avec succès.")
            return redirect('dashboard:secretary_faculties')
    else:
        form = FaculteForm(instance=faculte)
    
    return render(request, 'dashboard/secretary_faculty_edit.html', {
        'faculte': faculte,
        'form': form,
    })


@secretary_required
@require_http_methods(["POST"])
def secretary_faculty_delete(request, faculte_id):
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
            f"CRITIQUE: Suppression de la faculté '{faculte_nom}' (ID: {faculte_id}){cascade_msg} - Gestion structure académique - Secrétaire",
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
    
    return redirect('dashboard:secretary_faculties')


# ========== GESTION DES DÉPARTEMENTS ==========

@secretary_required
@require_http_methods(["GET", "POST"])
def secretary_departments(request):
    """Liste et création de départements"""
    
    if request.method == 'POST':
        form = DepartementForm(request.POST)
        if form.is_valid():
            dept = form.save()
            log_action(
                request.user, 
                f"CRITIQUE: Création du département '{dept.nom_departement}' dans la faculté '{dept.id_faculte.nom_faculte}' (Gestion structure académique - Secrétaire)", 
                request,
                niveau='CRITIQUE',
                objet_type='DEPARTEMENT',
                objet_id=dept.id_departement
            )
            messages.success(request, f"Département '{dept.nom_departement}' créé avec succès.")
            return redirect('dashboard:secretary_departments')
    else:
        form = DepartementForm()
    
    departments = Departement.objects.select_related('id_faculte').all().order_by('id_faculte__nom_faculte', 'nom_departement')
    
    return render(request, 'dashboard/secretary_departments.html', {
        'departments': departments,
        'form': form,
    })


@secretary_required
@require_http_methods(["GET", "POST"])
def secretary_department_edit(request, dept_id):
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
                f"CRITIQUE: Département '{old_name}' {action} (Gestion structure académique - Secrétaire)", 
                request,
                niveau='CRITIQUE',
                objet_type='DEPARTEMENT',
                objet_id=dept.id_departement
            )
            messages.success(request, f"Département '{dept.nom_departement}' {action} avec succès.")
            return redirect('dashboard:secretary_departments')
    else:
        form = DepartementForm(instance=dept)
    
    return render(request, 'dashboard/secretary_department_edit.html', {
        'department': dept,
        'form': form,
    })


@secretary_required
@require_http_methods(["POST"])
def secretary_department_delete(request, dept_id):
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
            f"CRITIQUE: Suppression du département '{dept_nom}' (Faculté: {faculte_nom}, ID: {dept_id}){cascade_msg} - Gestion structure académique - Secrétaire",
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
    
    return redirect('dashboard:secretary_departments')


# ========== GESTION DES COURS ==========

@secretary_required
@require_http_methods(["GET", "POST"])
def secretary_courses(request):
    """Liste et création de cours"""
    
    if request.method == 'POST':
        form = CoursForm(request.POST)
        if form.is_valid():
            cours = form.save()
            log_action(
                request.user, 
                f"CRITIQUE: Création du cours '{cours.code_cours} - {cours.nom_cours}' (Département: {cours.id_departement.nom_departement}, Seuil: {cours.get_seuil_absence()}%) - Gestion structure académique - Secrétaire", 
                request,
                niveau='CRITIQUE',
                objet_type='COURS',
                objet_id=cours.id_cours
            )
            messages.success(request, f"Cours '{cours.code_cours}' créé avec succès.")
            return redirect('dashboard:secretary_courses')
    else:
        form = CoursForm()
    
    courses = Cours.objects.select_related('id_departement', 'id_departement__id_faculte', 'professeur').all().order_by('code_cours')
    
    # Pagination
    paginator = Paginator(courses, 20)
    page = request.GET.get('page')
    courses_page = paginator.get_page(page)
    
    return render(request, 'dashboard/secretary_courses.html', {
        'courses': courses_page,
        'form': form,
    })


@secretary_required
@require_http_methods(["GET", "POST"])
def secretary_course_edit(request, course_id):
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
                f"CRITIQUE: Cours '{old_code}' {action} (Gestion structure académique - Secrétaire)", 
                request,
                niveau='CRITIQUE',
                objet_type='COURS',
                objet_id=cours.id_cours
            )
            messages.success(request, f"Cours '{cours.code_cours}' {action} avec succès.")
            return redirect('dashboard:secretary_courses')
    else:
        form = CoursForm(instance=cours)
    
    return render(request, 'dashboard/secretary_course_edit.html', {
        'course': cours,
        'form': form,
    })


@secretary_required
@require_http_methods(["POST"])
def secretary_course_delete(request, course_id):
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
            f"CRITIQUE: Suppression du cours '{cours_code} - {cours_nom}' (Département: {dept_nom}, ID: {course_id}){cascade_msg} - Gestion structure académique - Secrétaire",
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
    
    return redirect('dashboard:secretary_courses')


# ========== GESTION DES ANNÉES ACADÉMIQUES ==========

@secretary_required
@require_http_methods(["GET", "POST"])
def secretary_academic_years(request):
    """Liste et gestion des années académiques"""
    
    if request.method == 'POST':
        form = AnneeAcademiqueForm(request.POST)
        if form.is_valid():
            year = form.save()
            log_action(
                request.user, 
                f"CRITIQUE: Création de l'année académique '{year.libelle}' (Gestion structure académique - Secrétaire)", 
                request,
                niveau='CRITIQUE',
                objet_type='AUTRE',
                objet_id=year.id_annee
            )
            messages.success(request, f"Année académique '{year.libelle}' créée avec succès.")
            return redirect('dashboard:secretary_academic_years')
    else:
        form = AnneeAcademiqueForm()
    
    years = AnneeAcademique.objects.all().order_by('-libelle')
    
    return render(request, 'dashboard/secretary_academic_years.html', {
        'years': years,
        'form': form,
    })


@secretary_required
@require_http_methods(["POST"])
def secretary_academic_year_set_active(request, year_id):
    """Définir une année académique comme active"""
    
    year = get_object_or_404(AnneeAcademique, id_annee=year_id)
    
    # Désactiver toutes les années
    AnneeAcademique.objects.update(active=False)
    
    # Activer l'année sélectionnée
    year.active = True
    year.save()
    
    log_action(
        request.user, 
        f"CRITIQUE: Année académique '{year.libelle}' définie comme active (Gestion structure académique - Secrétaire)", 
        request,
        niveau='CRITIQUE',
        objet_type='AUTRE',
        objet_id=year.id_annee
    )
    messages.success(request, f"Année académique '{year.libelle}' définie comme active.")
    
    return redirect('dashboard:secretary_academic_years')


@secretary_required
@require_http_methods(["POST"])
def secretary_academic_year_delete(request, year_id):
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
            return redirect('dashboard:secretary_academic_years')
        
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
            f"CRITIQUE: Suppression de l'année académique '{year_libelle}' (ID: {year_id}){cascade_msg} - Gestion structure académique - Secrétaire",
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
    
    return redirect('dashboard:secretary_academic_years')


# ========== JOURNAUX D'AUDIT ==========

@secretary_required
def secretary_audit_logs(request):
    """Consultation de tous les journaux d'audit avec filtres (pour secrétaire)"""
    
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
    from django.core.paginator import Paginator
    paginator = Paginator(logs, 50)
    page = request.GET.get('page')
    logs_page = paginator.get_page(page)
    
    return render(request, 'dashboard/secretary_audit_logs.html', {
        'logs': logs_page,
        'role_filter': role_filter,
        'action_filter': action_filter,
        'date_from': date_from,
        'date_to': date_to,
        'user_filter': user_filter,
        'search_query': search_query,
    })

