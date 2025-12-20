from django.db.models import Sum
from .models import Absence
from apps.notifications.models import Notification
from apps.audits.models import LogAudit

def recalculer_eligibilite(inscription):
    # 1. Calcul des absences NON JUSTIFIÉES uniquement (selon tes instructions)
    total_absence = Absence.objects.filter(
        id_inscription=inscription,
        statut='NON_JUSTIFIEE'
    ).aggregate(total=Sum('duree_absence'))['total'] or 0

    cours = inscription.id_cours
    taux = (total_absence / cours.nombre_total_periodes) * 100

    # 2. Logique de blocage / déblocage
    if taux >= cours.seuil_absence:
        if inscription.eligible_examen: # Si il était encore éligible
            inscription.eligible_examen = False
            inscription.save()

            # Notification
            Notification.objects.create(
                id_utilisateur=inscription.id_etudiant,
                message=f"ALERTE : Seuil de {cours.seuil_absence}% dépassé pour {cours.nom_cours}. Examen bloqué.",
                type='INTERNE'
            )
            
            # Log d'Audit (Requis par tes instructions)
            LogAudit.objects.create(
                id_utilisateur=inscription.id_etudiant,
                action=f"Blocage automatique examen : {cours.nom_cours} (Taux: {taux:.1f}%)",
                adresse_ip="127.0.0.1"
            )
    else:
        # Si l'étudiant repasse sous le seuil (ex: après une justification)
        if not inscription.eligible_examen:
            inscription.eligible_examen = True
            inscription.save()