from django.shortcuts import render, redirect
from django.db.models.functions import TruncMonth
from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.contrib import messages

from apps.enrollments.models import Inscription
from apps.absences.models import Absence, Justification
from apps.notifications.models import Notification
from apps.accounts.models import User
import random

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
    elif user.role == User.Role.ADMIN or user.role == User.Role.SECRETAIRE:
        return admin_dashboard(request)
    else:
        # Fallback ou message d'erreur
        messages.error(request, "Rôle non reconnu ou accès non autorisé.")
        return render(request, 'dashboard/error.html')

@login_required
def student_dashboard(request):
    """
    Vue du tableau de bord étudiant
    """
    if request.user.role != User.Role.ETUDIANT:
        return redirect('dashboard:index')

    # 1. Récupérer les inscriptions de l'étudiant connecté
    inscriptions = Inscription.objects.filter(id_etudiant=request.user)
    
    # 2. Récupérer les 5 dernières notifications
    notifications = Notification.objects.filter(
        id_utilisateur=request.user
    ).order_by('-date_envoi')[:5]
    
    cours_data = []
    
    for ins in inscriptions:
        # 3. Calcul des absences NON JUSTIFIÉES
        total_abs = Absence.objects.filter(
            id_inscription=ins, 
            statut='NON_JUSTIFIEE'
        ).aggregate(total=Sum('duree_absence'))['total'] or 0
        
        # 4. Infos du cours
        cours = ins.id_cours
        
        # 5. Calcul du seuil en heures
        seuil_h = (cours.nombre_total_periodes * cours.seuil_absence) / 100
        
        # 6. Pourcentage progression (par rapport au seuil de blocage)
        percent_of_threshold = (total_abs / seuil_h) * 100 if seuil_h > 0 else 0
        
        # 7. Taux global d'absence (pour la couleur)
        absence_rate = (total_abs / cours.nombre_total_periodes) * 100 if cours.nombre_total_periodes > 0 else 0
        
        # 8. Eligibilité calculée à la volée
        is_eligible = total_abs < seuil_h

        cours_data.append({
            'id': ins.id_inscription,
            'nom': cours.nom_cours,
            'professeur': get_prof_name(cours), 
            'total_abs': total_abs,
            'total_periods': cours.nombre_total_periodes,
            'seuil_h': seuil_h,
            'percent': min(percent_of_threshold, 100), # Largeur de la barre
            'absence_rate': absence_rate, # Pour la couleur (Global Rate)
            'status': is_eligible 
        })
    
    academic_year = "2024-2025"
    if inscriptions.exists():
        academic_year = inscriptions.first().id_annee.libelle

    return render(request, 'dashboard/student_index.html', {
        'cours_data': cours_data,
        'notifications': notifications,
        'academic_year': academic_year
    })

@login_required
def instructor_dashboard(request):
    """
    Vue du tableau de bord professeur
    Affiche la liste des cours assignés à ce professeur.
    """
    if request.user.role != User.Role.PROFESSEUR:
        return redirect('dashboard:index')

    courses = request.user.cours_set.all().select_related('id_departement')
    
    return render(request, 'dashboard/instructor_index.html', {
        'courses': courses
    })

@login_required
def admin_dashboard(request):
    """
    Vue tableau de bord admin / secrétaire
    """
    # Liste des justificatifs en attente
    pending_justifications = Justification.objects.filter(validee=False).select_related('id_absence__id_inscription__id_etudiant')
    
    return render(request, 'dashboard/admin_index.html', {
        'pending_justifications': pending_justifications
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

@login_required
def student_statistics(request):
    """
    Page de statistiques détaillées pour l'étudiant.
    """
    if request.user.role != User.Role.ETUDIANT:
        return redirect('dashboard:index')

    user = request.user
    inscriptions = Inscription.objects.filter(id_etudiant=user)
    
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
    
    for entry in absences_by_month:
        if entry['month']:
            trend_labels.append(entry['month'].strftime('%B')) # e.g. "January"
            trend_data.append(entry['total_hours'])

    # If no data, provide empty structure or mock for visualization
    if not trend_data:
        trend_labels = ["Sept", "Oct", "Nov", "Dec", "Jan"]
        trend_data = [0, 2, 5, 8, 4] # Mock data for "New" student experience

    context = {
        'total_hours_missed': total_hours_missed,
        'courses_at_risk': courses_at_risk,
        'course_labels': course_labels,
        'absence_percentages': absence_percentages,
        'trend_labels': trend_labels,
        'trend_data': trend_data,
    }
    
    return render(request, 'dashboard/statistics.html', context)
