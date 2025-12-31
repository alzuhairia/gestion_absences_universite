from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Sum
from apps.enrollments.models import Inscription
from apps.absences.models import Absence, Justification
import base64
from apps.accounts.models import User
from apps.academics.models import Cours
from apps.academic_sessions.models import Seance, AnneeAcademique
from apps.audits.utils import log_action
from django.utils import timezone
import datetime
from apps.dashboard.decorators import professor_required, student_required

@login_required
@student_required
def absence_details(request, id_inscription):
    """
    Affiche les détails des absences pour un étudiant - Lecture seule.
    STRICT: Les étudiants peuvent uniquement consulter leurs absences et soumettre des justificatifs via la vue upload_justification.
    """
    # STRICT: Verify the inscription belongs to the logged-in student
    inscription = get_object_or_404(Inscription, id_inscription=id_inscription, id_etudiant=request.user)
    
    # Get all absences for this inscription
    absences = Absence.objects.filter(
        id_inscription=inscription
    ).order_by('-id_seance__date_seance').select_related('id_seance', 'id_seance__id_cours')
    
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
    
    # Get course and professor info
    course = inscription.id_cours
    prof_name = "Non assigné"
    if course.professeur:
        prof_name = course.professeur.get_full_name()
    
    # Calculate absence statistics
    total_abs_hours = Absence.objects.filter(
        id_inscription=inscription,
        statut='NON_JUSTIFIEE'
    ).aggregate(total=Sum('duree_absence'))['total'] or 0
    
    absence_rate = (total_abs_hours / course.nombre_total_periodes) * 100 if course.nombre_total_periodes > 0 else 0
    is_blocked = absence_rate >= 40 and not inscription.exemption_40

    return render(request, 'absences/details.html', {
        'inscription': inscription,
        'course': course,
        'absences_data': absences_data,
        'prof_name': prof_name,
        'absence_rate': round(absence_rate, 1),
        'is_blocked': is_blocked,
        'is_exempted': inscription.exemption_40,
    })

@login_required
@student_required
def upload_justification(request, absence_id):
    """
    Téléchargement de justificatif - STRICT: Uniquement pour les étudiants, uniquement pour les absences NON JUSTIFIÉES ou EN ATTENTE.
    """
    absence = get_object_or_404(Absence, id_absence=absence_id)
    
    # STRICT: Verify the absence belongs to the logged-in student
    if absence.id_inscription.id_etudiant != request.user:
        messages.error(request, "Accès non autorisé. Vous ne pouvez consulter que vos propres absences.")
        return redirect('dashboard:student_dashboard')
    
    # STRICT: Can only submit justification for UNJUSTIFIED or PENDING absences
    if absence.statut == 'JUSTIFIEE':
        messages.info(
            request, 
            "Cette absence est déjà justifiée. Vous ne pouvez plus soumettre de justificatif pour cette absence."
        )
        return redirect('absences:details', id_inscription=absence.id_inscription.id_inscription)
    
    # Retrieve existing justification if any
    justification = Justification.objects.filter(id_absence=absence).first()
    
    # STRICT: If justification exists and is ACCEPTED, cannot modify
    if justification and justification.state == 'ACCEPTEE':
        messages.success(
            request, 
            "Votre justificatif a été accepté par le secrétariat. Cette absence est maintenant justifiée."
        )
        return redirect('absences:details', id_inscription=absence.id_inscription.id_inscription)
    
    # STRICT: If justification is EN_ATTENTE, cannot modify (already submitted)
    if justification and justification.state == 'EN_ATTENTE':
        messages.warning(
            request, 
            "Un justificatif a déjà été soumis pour cette absence et est actuellement en cours d'examen par le secrétariat. "
            "Vous ne pouvez plus le modifier. Vous serez notifié une fois la décision prise."
        )
        return redirect('absences:details', id_inscription=absence.id_inscription.id_inscription)

    if request.method == 'POST' and request.FILES.get('document'):
        file_content = request.FILES['document'].read()
        comment = request.POST.get('comment', '')
        
        # Validate file type
        file = request.FILES['document']
        allowed_types = ['application/pdf', 'image/jpeg', 'image/jpg', 'image/png']
        if file.content_type not in allowed_types:
            messages.error(
                request, 
                "Format de fichier non accepté. Veuillez télécharger un fichier au format PDF, JPG ou PNG."
            )
            return redirect('absences:upload', absence_id=absence_id)
        
        # Validate file size (max 5MB)
        if file.size > 5 * 1024 * 1024:
            messages.error(
                request, 
                "Le fichier est trop volumineux. La taille maximale autorisée est de 5 Mo. "
                "Veuillez compresser votre fichier ou utiliser un fichier plus léger."
            )
            return redirect('absences:upload', absence_id=absence_id)
        
        # Create or update justification
        new_justification = None
        if justification and justification.state == 'REFUSEE':
            # Resubmit if previous was refused - create new justification
            new_justification = Justification.objects.create(
                id_absence=absence,
                document=file_content,
                commentaire=comment,
                state='EN_ATTENTE',
                validee=False
            )
        elif not justification:
            # Create new justification
            new_justification = Justification.objects.create(
                id_absence=absence,
                document=file_content,
                commentaire=comment,
                state='EN_ATTENTE',
                validee=False
            )
        else:
            # Should not happen due to checks above, but handle gracefully
            messages.error(request, "Impossible de soumettre le justificatif dans l'état actuel.")
            return redirect('absences:upload', absence_id=absence_id)

        # Update absence status to EN_ATTENTE (for display purposes)
        absence.statut = 'EN_ATTENTE'
        absence.save()
        
        # Audit logging
        if new_justification:
            log_action(
                request.user, 
                f"Étudiant a soumis une justification pour l'absence {absence.id_absence} - {absence.id_seance.id_cours.code_cours}", 
                request,
                niveau='INFO',
                objet_type='JUSTIFICATION',
                objet_id=new_justification.id_justification
            )
        
        messages.success(
            request, 
            "Votre justificatif a été envoyé avec succès. Il sera examiné par le secrétariat dans les plus brefs délais. "
            "Vous serez notifié une fois la décision prise. Vous ne pourrez plus modifier ce justificatif."
        )
        return redirect('absences:details', id_inscription=absence.id_inscription.id_inscription)
        
    return render(request, 'absences/justify.html', {
        'absence': absence,
        'justification': justification
    })

# --- NOUVELLES FONCTIONS POUR LA SECRÉTAIRE (ADMIN) ---

@login_required
def valider_justificatif(request, absence_id):
    """ Valide une absence et déclenche le recalcul de l'éligibilité via signal """
    # SECRÉTAIRE UNIQUEMENT - Les administrateurs ne gèrent pas les justificatifs
    if request.user.role != User.Role.SECRETAIRE:
        if request.user.role == User.Role.ADMIN:
            messages.warning(
                request, 
                "Cette fonction est réservée au secrétariat. "
                "Les administrateurs gèrent la configuration, pas les opérations quotidiennes."
            )
        else:
            messages.error(request, "Action non autorisée.")
        return redirect('dashboard:index')

    absence = get_object_or_404(Absence, id_absence=absence_id)
    
    # 1. On marque l'absence comme justifiée
    absence.statut = 'JUSTIFIEE'
    absence.save() # Déclenche le signal pour le passage au VERT de l'étudiant
    
    # 2. On marque l'objet Justification comme validé
    Justification.objects.filter(id_absence=absence).update(validee=True, validee_par=request.user, date_validation=timezone.now())
    
    messages.success(request, f"L'absence de {absence.id_inscription.id_etudiant.email} a été validée.")
    return redirect('dashboard:admin_index')

@login_required
def refuser_justificatif(request, absence_id):
    """ Refuse une justification et remet l'absence en NON_JUSTIFIEE """
    # SECRÉTAIRE UNIQUEMENT - Les administrateurs ne gèrent pas les justificatifs
    if request.user.role != User.Role.SECRETAIRE:
        if request.user.role == User.Role.ADMIN:
            messages.warning(
                request, 
                "Cette fonction est réservée au secrétariat. "
                "Les administrateurs gèrent la configuration, pas les opérations quotidiennes."
            )
        else:
            messages.error(request, "Action non autorisée.")
        return redirect('dashboard:index')

    absence = get_object_or_404(Absence, id_absence=absence_id)
    
    absence.statut = 'NON_JUSTIFIEE'
    absence.save() # Déclenche le signal (l'étudiant peut rester ou devenir ROUGE)
    
    # On marque le refus sur l'objet Justification
    Justification.objects.filter(id_absence=absence).update(validee=False, validee_par=request.user, date_validation=timezone.now())
    
    messages.warning(request, "Le justificatif a été refusé.")
    return redirect('dashboard:admin_index')

@login_required
def review_justification(request, absence_id):
    """
    Review justification - STRICT: Only for secretaries, NOT for professors or admins.
    Professors should NEVER see or modify justifications.
    Administrators manage configuration, not daily operations.
    """
    # STRICT RESTRICTION: Only secretaries can review justifications
    if request.user.role != User.Role.SECRETAIRE:
        if request.user.role == User.Role.ADMIN:
            messages.warning(
                request, 
                "Cette fonction est réservée au secrétariat. "
                "Les administrateurs gèrent la configuration, pas les opérations quotidiennes."
            )
        elif request.user.role == User.Role.PROFESSEUR:
            messages.error(request, "Accès non autorisé. Les justificatifs sont gérés par le secrétariat.")
        else:
            messages.error(request, "Action non autorisée.")
        return redirect('dashboard:index')
    
    absence = get_object_or_404(Absence, id_absence=absence_id)
    justification = get_object_or_404(Justification, id_absence=absence)
            
    if request.method == 'POST':
        # Mise à jour du commentaire de gestion
        new_comment = request.POST.get('commentaire_gestion')
        justification.commentaire_gestion = new_comment
        justification.save()
        messages.success(request, "Commentaire mis à jour.")
        # On redirige vers la même page pour voir le résultat
        return redirect('absences:review_justification', absence_id=absence_id)

    # Convertir le BLOB en Base64 pour affichage (si image/pdf)
    file_data = None
    file_type = "application/octet-stream" # Default
    if justification.document:
        file_data = base64.b64encode(justification.document).decode('utf-8')
        # Simple détection de type mime (à améliorer si besoin)
        # Mais pour l'instant on suppose que le navigateur gère via l'iframe ou le lien
        
    is_secretary = request.user.role == User.Role.SECRETAIRE

    return render(request, 'absences/review_justification.html', {
        'absence': absence,
        'justification': justification,
        'file_data': file_data,
        'is_secretary': is_secretary
    })

@login_required
@professor_required
@login_required
@professor_required
def mark_absence(request, course_id):
    """
    Vue pour qu'un professeur puisse noter les absences d'une séance.
    
    IMPORTANT POUR LA SOUTENANCE :
    Cette fonction implémente la saisie des présences/absences par le professeur.
    
    Logique métier :
    1. Vérification que le cours appartient au professeur (sécurité)
    2. Création ou récupération de la séance
    3. Pour chaque étudiant inscrit :
       - Marquer comme PRÉSENT, ABSENT, ou ABSENT JUSTIFIÉ
       - Si absent, définir le type (séance complète, retard/partiel, journée)
       - Calculer la durée de l'absence
    
    RÈGLE CRITIQUE - PROTECTION DES ABSENCES JUSTIFIÉES :
    - Les absences encodées par le secrétariat (statut JUSTIFIEE) sont PROTÉGÉES
    - Le professeur peut les VOIR mais ne peut PAS les modifier
    - Cette règle garantit l'intégrité des absences officielles
    
    SÉCURITÉ :
    - @professor_required : seul un professeur peut accéder
    - Vérification supplémentaire : course.professeur == request.user
    - Double vérification pour garantir que le professeur ne peut accéder qu'à ses cours
    
    Args:
        request: Objet HttpRequest contenant les données du formulaire
        course_id: ID du cours pour lequel faire l'appel
        
    Returns:
        HttpResponse avec le formulaire ou redirection après sauvegarde
    """
    # ============================================
    # VÉRIFICATION DE SÉCURITÉ
    # ============================================
    # IMPORTANT : Double vérification (décorateur + vérification de propriété)
    # Un professeur ne peut accéder qu'à SES propres cours
    
    course = get_object_or_404(Cours, id_cours=course_id)
    if course.professeur != request.user:
        messages.error(request, "Accès non autorisé à ce cours.")
        return redirect('dashboard:instructor_dashboard')

    if request.method == 'POST':
        # --- TRAITEMENT DU FORMULAIRE ---
        date_seance = request.POST.get('date_seance')
        heure_debut = request.POST.get('heure_debut')
        heure_fin = request.POST.get('heure_fin')
        
        # Récupération de l'année active (mock ou réelle)
        annee = AnneeAcademique.objects.filter(active=True).first()
        if not annee:
             # Fallback si pas d'année active définie
             annee, _ = AnneeAcademique.objects.get_or_create(libelle="2024-2025", defaults={'active': True})

        # Création ou Récupération de la séance
        seance, created = Seance.objects.get_or_create(
            date_seance=date_seance,
            heure_debut=heure_debut,
            heure_fin=heure_fin,
            id_cours=course,
            defaults={'id_annee': annee}
        )
        
        if not created:
             messages.info(
                 request, 
                 "Une séance existe déjà pour cette date. Les absences seront mises à jour pour cette séance existante."
             )

        # Calcul durée théorique
        fmt = '%H:%M'
        t_debut = datetime.datetime.strptime(heure_debut, fmt)
        t_fin = datetime.datetime.strptime(heure_fin, fmt)
        duree_seance = (t_fin - t_debut).seconds / 3600.0

        # Traitement des étudiants
        # On itère sur les clés POST qui commencent par 'status_'
        # Format attendu : status_{inscription_id}
        for key, value in request.POST.items():
            if key.startswith('status_'):
                inscription_id = key.split('_')[1]
                status = value # 'PRESENT' ou 'ABSENT'
                inscription = Inscription.objects.get(id_inscription=inscription_id)
                
                # ============================================
                # PROTECTION DES ABSENCES JUSTIFIÉES
                # ============================================
                # RÈGLE MÉTIER CRITIQUE :
                # Les absences encodées par le secrétariat (statut JUSTIFIEE) sont OFFICIELLES
                # Le professeur peut les CONSULTER mais ne peut PAS les modifier
                # Cela garantit l'intégrité des données et la hiérarchie des rôles
                
                existing_absence = Absence.objects.filter(id_inscription=inscription, id_seance=seance).first()
                is_prof = request.user.role == User.Role.PROFESSEUR

                if status == 'ABSENT':
                    # Vérifier si une absence existe déjà pour cet étudiant et cette séance
                    if is_prof and existing_absence:
                        # Le professeur ne peut pas modifier une absence existante
                        # (il peut seulement créer de nouvelles absences)
                        continue
                    
                    # PROTECTION SPÉCIALE : Absences justifiées par le secrétariat
                    if is_prof and existing_absence and existing_absence.statut == 'JUSTIFIEE':
                        # L'absence est justifiée par le secrétariat = OFFICIELLE
                        # Le professeur ne peut pas la modifier (skip)
                        continue

                    type_absence = request.POST.get(f'type_{inscription_id}', 'SEANCE')
                    
                    # Déterminer la durée
                    duree = duree_seance # Default for SEANCE
                    if type_absence == 'HEURE':
                         try:
                             duree = float(request.POST.get(f'duree_{inscription_id}', 0))
                         except:
                             duree = duree_seance
                    elif type_absence == 'JOURNEE':
                        duree = 8.0 # Valeur arbitraire pour journée
                        
                    # Création ou Mise à jour Absence (only if not validated)
                    if existing_absence and existing_absence.statut == 'JUSTIFIEE':
                        # Skip validated absences - professors cannot modify them
                        continue
                    
                    absence, created = Absence.objects.update_or_create(
                        id_inscription=inscription,
                        id_seance=seance,
                        defaults={
                            'type_absence': type_absence,
                            'duree_absence': duree,
                            'statut': 'NON_JUSTIFIEE',
                            'encodee_par': request.user
                        }
                    )
                    
                    # Audit logging for professor actions
                    if is_prof:
                        action_desc = f"Professeur a enregistré une absence pour {inscription.id_etudiant.get_full_name()} - {course.code_cours} le {date_seance}"
                        log_action(
                            request.user, 
                            action_desc, 
                            request,
                            niveau='INFO',
                            objet_type='ABSENCE',
                            objet_id=absence.id_absence
                        )
                else:
                    # Si marqué PRÉSENT, on supprime une éventuelle absence existante pour cette séance
                    # STRICT: Professors CANNOT delete or modify existing absences
                    if existing_absence:
                        if is_prof:
                            # Professors cannot delete absences (especially validated ones)
                            continue
                        # Only admins/secretaries can delete
                        if existing_absence.statut != 'JUSTIFIEE':
                            existing_absence.delete()
        
        # Audit logging for session creation/attendance
        if request.user.role == User.Role.PROFESSEUR:
            if created:
                log_action(
                    request.user, 
                    f"Professeur a créé une séance pour {course.code_cours} le {date_seance}", 
                    request,
                    niveau='INFO',
                    objet_type='SEANCE',
                    objet_id=seance.id_seance if hasattr(seance, 'id_seance') else None
                )
            log_action(
                request.user, 
                f"Professeur a enregistré la présence pour {course.code_cours} le {date_seance}", 
                request,
                niveau='INFO',
                objet_type='SEANCE',
                objet_id=seance.id_seance if hasattr(seance, 'id_seance') else None
            )
        
        messages.success(
            request, 
            f"Les absences ont été enregistrées avec succès pour la séance du {date_seance}. "
            "Vous pouvez consulter les détails dans la page du cours."
        )
        return redirect('dashboard:instructor_dashboard')

    # --- AFFICHAGE DU FORMULAIRE (GET) ---
    students = Inscription.objects.filter(id_cours=course).select_related('id_etudiant').order_by('id_etudiant__nom')
    
    # Check for date in GET (from dashboard link)
    today = request.GET.get('date', timezone.now().strftime('%Y-%m-%d'))
    default_start = "08:30"
    default_end = "10:30"
    
    existing_seance = Seance.objects.filter(id_cours=course, date_seance=today).order_by('-id_seance').first()
    
    existing_absences = {}
    is_edit_mode = False
    
    if existing_seance:
        is_edit_mode = True
        default_start = existing_seance.heure_debut.strftime('%H:%M')
        default_end = existing_seance.heure_fin.strftime('%H:%M')
        
        abs_list = Absence.objects.filter(id_seance=existing_seance)
        for ab in abs_list:
            existing_absences[ab.id_inscription.id_inscription] = {
                'type': ab.type_absence,
                'duree': ab.duree_absence,
                'statut': ab.statut
            }
            
    # Attach absence data to students for template usage
    for ins in students:
        ins.absence_data = existing_absences.get(ins.id_inscription)

    return render(request, 'absences/mark_absence.html', {
        'course': course,
        'students': students,
        'today': today,
        'default_start': default_start,
        'default_end': default_end,
        'is_edit_mode': is_edit_mode
    })
