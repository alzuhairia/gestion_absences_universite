from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from .models import Absence
from apps.accounts.models import User
from apps.audits.utils import log_action
from apps.dashboard.decorators import secretary_required

_VALID_TYPES   = {"HEURE", "SEANCE", "JOURNEE"}
_VALID_STATUTS = {"EN_ATTENTE", "JUSTIFIEE", "NON_JUSTIFIEE"}


@login_required
@secretary_required
def edit_absence(request, pk):
    absence = get_object_or_404(Absence, pk=pk)

    if request.method == 'POST':
        # Capture old state for audit comparison
        old_statut = absence.statut
        old_duree  = float(absence.duree_absence or 0)
        old_type   = absence.type_absence

        # --- Validate all inputs BEFORE any DB write ---
        reason     = request.POST.get('reason', '').strip()
        new_type   = request.POST.get('type_absence', '')
        new_statut = request.POST.get('statut', '')

        if not reason:
            messages.error(
                request,
                "Un motif est obligatoire pour modifier une absence. "
                "Veuillez indiquer la raison de cette modification."
            )
            return render(request, 'absences/edit_absence.html', {'absence': absence})

        if new_type not in _VALID_TYPES:
            messages.error(request, "Type d'absence invalide.")
            return render(request, 'absences/edit_absence.html', {'absence': absence})

        if new_statut not in _VALID_STATUTS:
            messages.error(request, "Statut invalide.")
            return render(request, 'absences/edit_absence.html', {'absence': absence})

        try:
            new_duree = float(request.POST.get('duree_absence') or 0)
        except (ValueError, TypeError):
            messages.error(
                request,
                "Durée invalide. Veuillez entrer un nombre décimal (ex : 1.5)."
            )
            return render(request, 'absences/edit_absence.html', {'absence': absence})

        # --- Detect changes BEFORE saving ---
        change_desc = f"Absence {pk} UPDATED. "
        changed = False

        if old_statut != new_statut:
            change_desc += f"Statut: {old_statut} -> {new_statut}. "
            changed = True
        if old_duree != new_duree:
            change_desc += f"Durée: {old_duree} -> {new_duree}. "
            changed = True
        if old_type != new_type:
            change_desc += f"Type: {old_type} -> {new_type}. "
            changed = True

        if changed:
            change_desc += f"Motif: {reason}"

            absence.duree_absence = new_duree
            absence.type_absence  = new_type
            absence.statut        = new_statut
            absence.save()

            log_action(
                request.user,
                f"Secrétaire a modifié l'absence {pk} pour "
                f"{absence.id_inscription.id_etudiant.get_full_name()} - "
                f"{absence.id_seance.id_cours.code_cours}. {change_desc}",
                request,
                niveau='WARNING',
                objet_type='ABSENCE',
                objet_id=pk,
            )
            messages.success(
                request,
                "L'absence a été modifiée avec succès. "
                "La modification a été enregistrée dans le journal d'audit avec le motif indiqué."
            )
        else:
            messages.info(request, "Aucune modification détectée.")

        return redirect('absences:validation_list')

    return render(request, 'absences/edit_absence.html', {'absence': absence})
