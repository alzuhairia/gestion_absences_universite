from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from .models import Absence
from apps.accounts.models import User
from apps.audits.utils import log_action
from apps.dashboard.decorators import secretary_required

@login_required
@secretary_required
def edit_absence(request, pk):
    absence = get_object_or_404(Absence, pk=pk)
    
    if request.method == 'POST':
        # Capture old state for logging
        old_statut = absence.statut
        old_duree = absence.duree_absence
        old_type = absence.type_absence
        
        # Update fields
        absence.duree_absence = request.POST.get('duree_absence')
        absence.type_absence = request.POST.get('type_absence')
        new_statut = request.POST.get('statut')
        reason = request.POST.get('reason')
        
        if not reason or not reason.strip():
            messages.error(
                request, 
                "Un motif est obligatoire pour modifier une absence. Veuillez indiquer la raison de cette modification."
            )
            return render(request, 'absences/edit_absence.html', {'absence': absence})

        absence.statut = new_statut
        absence.save()
        
        # Log Audit
        if old_statut != new_statut or float(old_duree) != float(absence.duree_absence) or old_type != absence.type_absence:
            change_desc = f"Absence {pk} UPDATED. "
            if old_statut != new_statut:
                change_desc += f"Status: {old_statut} -> {new_statut}. "
            if float(old_duree) != float(absence.duree_absence):
                change_desc += f"Duration: {old_duree} -> {absence.duree_absence}. "
            
            change_desc += f"Reason: {reason}"
            
            log_action(
                request.user, 
                f"Secrétaire a modifié l'absence {pk} pour {absence.id_inscription.id_etudiant.get_full_name()} - {absence.id_seance.id_cours.code_cours}. {change_desc}", 
                request,
                niveau='WARNING',
                objet_type='ABSENCE',
                objet_id=pk
            )
            messages.success(
                request, 
                f"L'absence a été modifiée avec succès. La modification a été enregistrée dans le journal d'audit avec le motif indiqué."
            )
        else:
            messages.info(request, "Aucune modification détectée.")
            
        return redirect('absences:validation_list') # Or back to detail view if exists

    return render(request, 'absences/edit_absence.html', {'absence': absence})
