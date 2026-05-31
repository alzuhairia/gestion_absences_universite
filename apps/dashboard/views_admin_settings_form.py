"""
Vue du formulaire des paramètres système pour le tableau de bord administrateur UniAbsences.

``admin_settings``
    Affiche et traite le ``SystemSettingsForm``. Persiste les modifications dans
    l'enregistrement singleton ``SystemSettings`` et redirige avec un message
    de succès. Réservé à ``@admin_required``.

Fait partie du tableau de bord UniAbsences.
"""

import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from apps.audits.utils import log_action
from apps.dashboard.decorators import admin_required
from apps.dashboard.forms_admin import SystemSettingsForm
from apps.dashboard.models import SystemSettings

logger = logging.getLogger(__name__)


@login_required
@admin_required
@require_http_methods(["GET", "POST"])
def admin_settings(request):
    """Gestion des paramètres système globaux"""

    settings = SystemSettings.get_settings()

    if request.method == "POST":
        old_threshold = settings.default_absence_threshold
        form = SystemSettingsForm(request.POST, instance=settings)
        if form.is_valid():
            settings = form.save(commit=False)
            settings.modified_by = request.user
            settings.save()

            if old_threshold != settings.default_absence_threshold:
                log_action(
                    request.user,
                    f"CRITIQUE: Modification du seuil d'absence par défaut de {old_threshold}% à {settings.default_absence_threshold}% (Paramètres système - Impact global)",
                    request,
                    niveau="CRITIQUE",
                    objet_type="SYSTEM",
                    objet_id=1,
                )

            log_action(
                request.user,
                f"CRITIQUE: Modification des paramètres système (Seuil: {settings.default_absence_threshold}%, Blocage: {settings.get_block_type_display()})",
                request,
                niveau="CRITIQUE",
                objet_type="SYSTEM",
                objet_id=1,
            )
            messages.success(request, "Paramètres système mis à jour avec succès.")
            return redirect("dashboard:admin_settings")
    else:
        form = SystemSettingsForm(instance=settings)

    return render(
        request,
        "dashboard/admin_settings.html",
        {
            "form": form,
            "settings": settings,
        },
    )
