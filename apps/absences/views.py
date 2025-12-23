from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from apps.enrollments.models import Inscription
from apps.absences.models import Absence, Justification
import base64
from apps.accounts.models import User

@login_required
def absence_details(request, id_inscription):
    """
    Affiche les détails des absences pour une inscription donnée.
    Permet aussi d'uploader un justificatif.
    """
    inscription = get_object_or_404(Inscription, id_inscription=id_inscription, id_etudiant=request.user)
    absences = Absence.objects.filter(id_inscription=inscription).order_by('-id_seance__date_seance').select_related('id_seance')
    
    if request.method == 'POST':
        # Gestion de l'upload de justificatif
        absence_id = request.POST.get('absence_id')
        comment = request.POST.get('comment')
        file = request.FILES.get('document')
        
        if absence_id and file:
            try:
                absence = Absence.objects.get(id_absence=absence_id, id_inscription=inscription)
                # Création de la justification (Stockage Binaire)
                file_content = file.read()
                
                Justification.objects.create(
                    id_absence=absence,
                    document=file_content,
                    commentaire=comment,
                    validee=False
                )
                
                # Mettre à jour le statut de l'absence pour l'expérience utilisateur
                absence.statut = 'EN_ATTENTE'
                absence.save()
                
                messages.success(request, "Justificatif envoyé avec succès.")
            except Absence.DoesNotExist:
                messages.error(request, "Absence invalide.")
            except Exception as e:
                messages.error(request, f"Erreur lors de l'envoi : {str(e)}")
        
        return redirect('absences:details', id_inscription=id_inscription)

    profs = User.objects.filter(role=User.Role.PROFESSEUR)
    prof_name = profs.first().get_full_name() if profs.exists() else "Staff Académique"

    return render(request, 'absences/details.html', {
        'inscription': inscription,
        'absences': absences,
        'prof_name': prof_name,
    })

@login_required
def upload_justification(request, absence_id):
    absence = get_object_or_404(Absence, id_absence=absence_id)
    
    # Retrieve existing justification if any
    justification = Justification.objects.filter(id_absence=absence).first()

    if request.method == 'POST' and request.FILES.get('document'):
        file_content = request.FILES['document'].read()
        comment = request.POST.get('comment')
        
        if justification:
            # Update existing
            justification.document = file_content
            justification.commentaire = comment
            justification.validee = False
            justification.save()
        else:
            # Create new
            Justification.objects.create(
                id_absence=absence,
                document=file_content,
                commentaire=comment,
                validee=False
            )

        absence.statut = 'EN_ATTENTE'
        absence.save()
        
        messages.success(request, "Justificatif envoyé avec succès.")
        return redirect('absences:details', id_inscription=absence.id_inscription.id_inscription)
        
    return render(request, 'absences/justify.html', {
        'absence': absence,
        'justification': justification
    })

# --- NOUVELLES FONCTIONS POUR LA SECRÉTAIRE (ADMIN) ---

@login_required
def valider_justificatif(request, absence_id):
    """ Valide une absence et déclenche le recalcul de l'éligibilité via signal """
    absence = get_object_or_404(Absence, id_absence=absence_id)
    
    # 1. On marque l'absence comme justifiée
    absence.statut = 'JUSTIFIEE'
    absence.save() # Déclenche le signal pour le passage au VERT de l'étudiant
    
    # 2. On marque l'objet Justification comme validé
    Justification.objects.filter(id_absence=absence).update(validee=True)
    
    messages.success(request, f"L'absence de {absence.id_inscription.id_etudiant.email} a été validée.")
    return redirect('dashboard:admin_index')

@login_required
def refuser_justificatif(request, absence_id):
    """ Refuse une justification et remet l'absence en NON_JUSTIFIEE """
    absence = get_object_or_404(Absence, id_absence=absence_id)
    
    absence.statut = 'NON_JUSTIFIEE'
    absence.save() # Déclenche le signal (l'étudiant peut rester ou devenir ROUGE)
    
    # On marque le refus sur l'objet Justification
    Justification.objects.filter(id_absence=absence).update(validee=False)
    
    messages.warning(request, "Le justificatif a été refusé.")
    return redirect('dashboard:admin_index')