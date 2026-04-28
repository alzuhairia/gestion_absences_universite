"""
FICHIER : apps/dashboard/views_admin_users_delete.py
RESPONSABILITE : Suppression unitaire et en lot des utilisateurs (admin)
"""
import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models.deletion import ProtectedError
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from apps.absences.models import Absence, Justification
from apps.academics.models import Cours
from apps.accounts.models import User
from apps.audits.models import LogAudit
from apps.audits.utils import log_action
from apps.dashboard.decorators import admin_required
from apps.enrollments.models import Inscription

logger = logging.getLogger(__name__)


@login_required
@admin_required
@require_http_methods(["POST"])
def admin_users_delete_multiple(request):
    """Suppression multiple d'utilisateurs avec verifications de securite"""

    try:
        raw_user_ids = request.POST.getlist("user_ids")

        if not raw_user_ids:
            messages.error(request, "Aucun utilisateur sélectionné.")
            return redirect("dashboard:admin_users")

        user_ids = []
        for raw_user_id in raw_user_ids:
            try:
                user_ids.append(int(raw_user_id))
            except (TypeError, ValueError):
                continue
        user_ids = list(dict.fromkeys(user_ids))

        if not user_ids:
            messages.error(request, "Aucun identifiant utilisateur valide reçu.")
            return redirect("dashboard:admin_users")

        force_delete = request.POST.get("force_delete") == "1"

        deleted_count = 0
        failed_count = 0
        errors = []

        with transaction.atomic():
            locked_users = list(
                User.objects.select_for_update().filter(id_utilisateur__in=user_ids)
            )
            users_by_id = {user.id_utilisateur: user for user in locked_users}

            for user_id in user_ids:
                try:
                    user = users_by_id.get(user_id)
                    if not user:
                        errors.append(f"Utilisateur avec ID {user_id} introuvable")
                        failed_count += 1
                        continue

                    if user == request.user:
                        errors.append(
                            f"Vous ne pouvez pas supprimer votre propre compte ({user.email})"
                        )
                        failed_count += 1
                        continue

                    user_email = user.email
                    user_name = user.get_full_name()
                    user_role = user.get_role_display()
                    user_id_for_log = user.id_utilisateur

                    if force_delete:
                        _cascade_delete_user_data(user, request.user)

                    Cours.objects.filter(professeur=user).update(professeur=None)

                    try:
                        user.delete()
                        log_action(
                            request.user,
                            f"CRITIQUE: Suppression de l'utilisateur '{user_email}' (ID: {user_id_for_log}, Rôle: {user_role}, Nom: {user_name}) - Suppression multiple{' forcée' if force_delete else ''}",
                            request,
                            niveau="CRITIQUE",
                            objet_type="USER",
                            objet_id=user_id_for_log,
                        )
                        deleted_count += 1
                    except ProtectedError:
                        errors.append(
                            f"'{user_email}' possède des données liées et n'a pas pu être supprimé"
                        )
                        failed_count += 1
                except Exception:
                    logger.exception(
                        "Erreur lors de la suppression de l'utilisateur %s", user_id
                    )
                    errors.append(
                        "Erreur interne lors de la suppression de cet utilisateur."
                    )
                    failed_count += 1

        if deleted_count > 0:
            messages.success(
                request, f"{deleted_count} utilisateur(s) supprimé(s) définitivement avec succès."
            )
        if failed_count > 0:
            error_msg = f"{failed_count} utilisateur(s) n'ont pas pu être supprimé(s)."
            if errors:
                error_msg += " Détails : " + " ; ".join(errors[:5])
            messages.error(request, error_msg)

        return redirect("dashboard:admin_users")

    except Exception:
        logger.exception("Erreur lors de la suppression multiple")
        messages.error(
            request,
            "Erreur interne lors de la suppression multiple. "
            "Veuillez vérifier les dépendances ou contacter l'administrateur système.",
        )
        return redirect("dashboard:admin_users")


def _cascade_delete_user_data(user, performed_by):
    """
    Supprime en cascade les données liées à un utilisateur avant sa suppression.

    Ordre : Justifications → Absences (de ses inscriptions) → Inscriptions,
    puis réassigne les absences encodées par cet utilisateur à l'admin qui supprime.

    Doit être appelée à l'intérieur d'un transaction.atomic().
    """
    student_absences = Absence.objects.filter(id_inscription__id_etudiant=user)
    Justification.objects.filter(id_absence__in=student_absences).delete()
    student_absences.delete()
    Inscription.objects.filter(id_etudiant=user).delete()
    Absence.objects.filter(encodee_par=user).update(encodee_par=performed_by)


@login_required
@admin_required
@require_http_methods(["GET", "POST"])
def admin_user_delete(request, user_id):
    """Suppression d'un utilisateur avec verifications de securite"""

    try:
        user = get_object_or_404(User, id_utilisateur=user_id)

        if user == request.user:
            messages.error(request, "Vous ne pouvez pas supprimer votre propre compte.")
            return redirect("dashboard:admin_users")

        if user.role == User.Role.ADMIN and user.actif:
            active_admin_count = User.objects.filter(
                role=User.Role.ADMIN, actif=True
            ).count()
            if active_admin_count <= 1:
                messages.error(
                    request,
                    "Impossible de supprimer le dernier administrateur actif.",
                )
                return redirect("dashboard:admin_users")

        inscriptions_count = Inscription.objects.filter(id_etudiant=user).count()
        absences_encoded_count = Absence.objects.filter(encodee_par=user).count()
        audit_logs_count = LogAudit.objects.filter(id_utilisateur=user).count()
        cours_count = Cours.objects.filter(professeur=user).count()

        has_dependencies = (
            inscriptions_count > 0
            or absences_encoded_count > 0
            or audit_logs_count > 0
        )

        if request.method == "GET":
            cascade_items = [
                item
                for item in [
                    {"count": inscriptions_count, "label": "inscription(s)"},
                    {"count": absences_encoded_count, "label": "absence(s) encodée(s)"},
                    {"count": audit_logs_count, "label": "entrée(s) d'audit"},
                    {"count": cours_count, "label": "cours (sera détaché du professeur)"},
                ]
                if item["count"] > 0
            ]
            return render(
                request,
                "dashboard/admin_confirm_delete.html",
                {
                    "object_label": f"Utilisateur « {user.get_full_name()} » ({user.email})",
                    "cascade_items": cascade_items,
                    "has_dependencies": has_dependencies,
                    "cancel_url": "/dashboard/admin/users/",
                    "cancel_label": "Utilisateurs",
                },
            )

        action = request.POST.get("action", "")
        user_email = user.email
        user_name = user.get_full_name()
        user_role = user.get_role_display()
        user_id_for_log = user.id_utilisateur

        if action == "deactivate":
            user.actif = False
            user.save(update_fields=["actif"])
            log_action(
                request.user,
                f"CRITIQUE: Désactivation de l'utilisateur '{user_email}' (ID: {user_id_for_log}) - Choix admin",
                request,
                niveau="CRITIQUE",
                objet_type="USER",
                objet_id=user_id_for_log,
            )
            messages.success(
                request,
                f"Le compte '{user_email}' a été désactivé. Les données liées sont conservées.",
            )
            return redirect("dashboard:admin_users")

        try:
            with transaction.atomic():
                if has_dependencies and action == "force_delete":
                    _cascade_delete_user_data(user, request.user)

                if cours_count > 0:
                    Cours.objects.filter(professeur=user).update(professeur=None)

                user.delete()

                log_action(
                    request.user,
                    f"CRITIQUE: Suppression de l'utilisateur '{user_email}' "
                    f"(ID: {user_id_for_log}, Rôle: {user_role}, Nom: {user_name}) - "
                    f"{'Suppression forcée avec données' if action == 'force_delete' else 'Gestion des utilisateurs'}",
                    request,
                    niveau="CRITIQUE",
                    objet_type="USER",
                    objet_id=user_id_for_log,
                )

            messages.success(request, f"Utilisateur '{user_email}' supprimé définitivement avec succès.")

        except ProtectedError:
            user.actif = False
            user.save(update_fields=["actif"])
            log_action(
                request.user,
                f"CRITIQUE: Désactivation (fallback) de l'utilisateur '{user_email}' "
                f"(ID: {user_id_for_log}) - Dépendances PROTECT détectées lors de la suppression",
                request,
                niveau="CRITIQUE",
                objet_type="USER",
                objet_id=user_id_for_log,
            )
            messages.warning(
                request,
                f"Des données liées ont été détectées. "
                f"Le compte '{user_email}' a été désactivé au lieu d'être supprimé.",
            )

        return redirect("dashboard:admin_users")

    except Exception:
        logger.exception(
            "Exception lors de la suppression de l'utilisateur %s", user_id
        )
        messages.error(
            request,
            "Erreur interne lors de la suppression de l'utilisateur. "
            "Veuillez vérifier les dépendances ou contacter l'administrateur système.",
        )
        return redirect("dashboard:admin_users")
