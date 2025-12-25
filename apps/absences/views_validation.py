from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.utils import timezone
from django.contrib import messages
from django.views.decorators.http import require_POST
from django.core.paginator import Paginator

from .models import Absence, Justification
from apps.accounts.models import User
from apps.notifications.models import Notification
from apps.audits.utils import log_action
from apps.dashboard.decorators import secretary_required

@login_required
@secretary_required
def validation_list(request):
    """
    Liste des justificatifs nécessitant une validation.
    """
    # Filter for PENDING or explicitly requested status
    status_filter = request.GET.get('status', 'EN_ATTENTE')
    
    justifications = Justification.objects.filter(
        state=status_filter
    ).select_related(
        'id_absence', 
        'id_absence__id_inscription', 
        'id_absence__id_inscription__id_etudiant',
        'id_absence__id_seance__id_cours'
    ).order_by('-id_justification')
    
    # Pagination
    paginator = Paginator(justifications, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    return render(request, 'absences/validation_list.html', {
        'page_obj': page_obj,
        'current_status': status_filter
    })

@login_required
@secretary_required
@require_POST
def process_justification(request, pk):
    """
    Traite une justification (Approuver/Refuser).
    SECRÉTAIRE UNIQUEMENT - Les administrateurs ne gèrent pas les justificatifs.
    """
    justification = get_object_or_404(Justification, pk=pk)
    action = request.POST.get('action') 
    comment = request.POST.get('comment', '')
    
    previous_state = justification.state
    
    if action == 'approve':
        justification.state = 'ACCEPTEE'
        justification.validee = True # Legacy support
        justification.commentaire_gestion = comment
        justification.validee_par = request.user
        justification.date_validation = timezone.now()
        justification.save()
        
        # Update Absence Status
        absence = justification.id_absence
        absence.statut = 'JUSTIFIEE'
        absence.save()
        
        # Determine Notification Message
        msg_text = f"Votre justification pour l'absence du {absence.id_seance.date_seance} a été ACCEPTÉE."
        
        log_action(
            request.user, 
            f"Secrétaire a APPROUVÉ la justification {justification.pk} pour l'absence {absence.pk} - {absence.id_seance.id_cours.code_cours}. Motif: {comment}", 
            request,
            niveau='INFO',
            objet_type='JUSTIFICATION',
            objet_id=justification.id_justification
        )
        
    elif action == 'reject':
        justification.state = 'REFUSEE'
        justification.validee = False # Legacy support
        justification.commentaire_gestion = comment
        justification.validee_par = request.user
        justification.date_validation = timezone.now()
        justification.save()
        
        # Update Absence Status
        absence = justification.id_absence
        absence.statut = 'NON_JUSTIFIEE'
        absence.save()
        
        msg_text = f"Votre justification pour l'absence du {absence.id_seance.date_seance} a été REFUSÉE. Motif : {comment}"
        
        log_action(
            request.user, 
            f"Secrétaire a REFUSÉ la justification {justification.pk} pour l'absence {absence.pk} - {absence.id_seance.id_cours.code_cours}. Motif: {comment}", 
            request,
            niveau='WARNING',
            objet_type='JUSTIFICATION',
            objet_id=justification.id_justification
        )
        
    else:
        messages.error(request, "Action invalide.")
        return redirect('absences:validation_list')

    # Send Notification (if state changed)
    if previous_state != justification.state:
        Notification.objects.create(
            id_utilisateur=justification.id_absence.id_inscription.id_etudiant,
            message=msg_text,
            date_envoi=timezone.now(),
            lue=False
        )
        if action == 'approve':
            messages.success(
                request, 
                f"Le justificatif a été accepté avec succès. L'absence de {absence.id_inscription.id_etudiant.get_full_name()} "
                f"pour le cours {absence.id_seance.id_cours.code_cours} est maintenant justifiée. L'étudiant a été notifié."
            )
        else:
            messages.warning(
                request, 
                f"Le justificatif a été refusé. L'absence de {absence.id_inscription.id_etudiant.get_full_name()} "
                f"reste non justifiée. L'étudiant a été notifié avec le motif indiqué."
            )
    
    return redirect('absences:validation_list')
