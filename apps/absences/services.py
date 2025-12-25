from django.db.models import Sum
from .models import Absence
from apps.notifications.models import Notification
from apps.audits.models import LogAudit


def recalculer_eligibilite(inscription):
    """
    Recalcule l'éligibilité d'un étudiant à l'examen basé sur ses absences non justifiées.
    
    Cette fonction est appelée automatiquement via un signal Django après chaque
    modification d'absence pour maintenir la cohérence des données.
    
    Args:
        inscription: Instance de Inscription à recalculer
    """
    # 1. Calcul des absences NON JUSTIFIÉES uniquement
    total_absence = Absence.objects.filter(
        id_inscription=inscription,
        statut='NON_JUSTIFIEE'
    ).aggregate(total=Sum('duree_absence'))['total'] or 0

    cours = inscription.id_cours
    
    # Vérifier que le cours a des périodes
    if cours.nombre_total_periodes == 0:
        # Si pas de périodes, l'étudiant est éligible
        if not inscription.eligible_examen:
            inscription.eligible_examen = True
            inscription.save(update_fields=['eligible_examen'])
        return
    
    # Calculer le taux d'absence
    taux = (total_absence / cours.nombre_total_periodes) * 100
    
    # Utiliser le seuil du cours (ou le seuil par défaut)
    seuil = cours.get_seuil_absence()
    
    # 2. Logique de blocage / déblocage
    if taux >= seuil and not inscription.exemption_40:
        # Étudiant dépasse le seuil et n'a pas d'exemption
        if inscription.eligible_examen:
            inscription.eligible_examen = False
            inscription.save(update_fields=['eligible_examen'])

            # Notification à l'étudiant
            Notification.objects.create(
                id_utilisateur=inscription.id_etudiant,
                message=f"ALERTE : Seuil de {seuil}% dépassé pour {cours.nom_cours}. Examen bloqué.",
                type='ALERTE'
            )
            
            # Log d'Audit
            LogAudit.objects.create(
                id_utilisateur=inscription.id_etudiant,
                action=f"CRITIQUE: Blocage automatique examen - {cours.nom_cours} (Taux: {taux:.1f}%, Seuil: {seuil}%)",
                adresse_ip="127.0.0.1",
                niveau='CRITIQUE',
                objet_type='INSCRIPTION',
                objet_id=inscription.id_inscription
            )
    else:
        # Étudiant est sous le seuil ou a une exemption
        if not inscription.eligible_examen:
            inscription.eligible_examen = True
            inscription.save(update_fields=['eligible_examen'])
            
            # Notification de déblocage
            Notification.objects.create(
                id_utilisateur=inscription.id_etudiant,
                message=f"Information : Vous êtes à nouveau éligible à l'examen pour {cours.nom_cours}.",
                type='INFO'
            )