from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from apps.accounts.models import User
from apps.audits.utils import log_action
from apps.dashboard.decorators import secretary_required

from .models import Absence

_VALID_TYPES = {"HEURE", "SEANCE", "JOURNEE"}
_VALID_STATUTS = {"EN_ATTENTE", "JUSTIFIEE", "NON_JUSTIFIEE"}


@login_required
@secretary_required
@require_http_methods(["GET", "POST"])
def edit_absence(request, pk):
    absence = get_object_or_404(Absence, pk=pk)

    if request.method == "POST":
        # --- Validate all inputs BEFORE any DB write ---
        reason = request.POST.get("reason", "").strip()
        new_type = request.POST.get("type_absence", "")
        new_statut = request.POST.get("statut", "")

        if not reason:
            messages.error(
                request,
                "Un motif est obligatoire pour modifier une absence. "
                "Veuillez indiquer la raison de cette modification.",
            )
            return render(request, "absences/edit_absence.html", {"absence": absence})

        if new_type not in _VALID_TYPES:
            messages.error(request, "Type d'absence invalide.")
            return render(request, "absences/edit_absence.html", {"absence": absence})

        if new_statut not in _VALID_STATUTS:
            messages.error(request, "Statut invalide.")
            return render(request, "absences/edit_absence.html", {"absence": absence})

        try:
            new_duree = float(request.POST.get("duree_absence") or 0)
        except (ValueError, TypeError):
            messages.error(
                request, "Durée invalide. Veuillez entrer un nombre décimal (ex : 1.5)."
            )
            return render(request, "absences/edit_absence.html", {"absence": absence})

        if new_duree <= 0:
            messages.error(request, "La durée doit être supérieure à zéro.")
            return render(request, "absences/edit_absence.html", {"absence": absence})

        with transaction.atomic():
            # Re-fetch with row lock to prevent concurrent modification (TOCTOU)
            absence = Absence.objects.select_for_update().get(pk=pk)

            # Capture old state for audit comparison inside the lock
            old_statut = absence.statut
            old_duree = float(absence.duree_absence or 0)
            old_type = absence.type_absence

            # --- Detect changes ---
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
                absence.type_absence = new_type
                absence.statut = new_statut
                absence.save()

                log_action(
                    request.user,
                    f"Secrétaire a modifié l'absence {pk} pour "
                    f"{absence.id_inscription.id_etudiant.get_full_name()} - "
                    f"{absence.id_seance.id_cours.code_cours}. {change_desc}",
                    request,
                    niveau="WARNING",
                    objet_type="ABSENCE",
                    objet_id=pk,
                )

        if changed:
            messages.success(
                request,
                "L'absence a été modifiée avec succès. "
                "La modification a été enregistrée dans le journal d'audit avec le motif indiqué.",
            )
        else:
            messages.info(request, "Aucune modification détectée.")

        return redirect("absences:validation_list")

    return render(request, "absences/edit_absence.html", {"absence": absence})
