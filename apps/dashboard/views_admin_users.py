"""
FICHIER : apps/dashboard/views_admin_users.py
RESPONSABILITE : Gestion des utilisateurs (admin) - CRUD, mot de passe, audit
FONCTIONNALITES PRINCIPALES :
  - Liste et filtrage utilisateurs par role/statut
  - Creation, modification, suppression utilisateurs
  - Reset mot de passe avec validation
  - Audit par utilisateur
  - Suppression en lot avec verification dependances
DEPENDANCES CLES : accounts.models, dashboard.forms_admin, audits.utils
"""

import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import transaction

from apps.utils import safe_get_page
from django.db.models import Count, Q
from django.db.models.deletion import ProtectedError
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_http_methods

from apps.absences.models import Absence
from apps.academics.models import Cours
from apps.accounts.models import TwoFactorBackupCode, User
from apps.audits.models import LogAudit
from apps.audits.utils import log_action
from apps.dashboard.decorators import admin_required
from apps.dashboard.forms_admin import UserForm
from apps.enrollments.models import Inscription

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Liste et filtrage utilisateurs
# ---------------------------------------------------------------------------


@login_required
@admin_required
@require_GET
def admin_users(request):
    """Liste et gestion des utilisateurs"""

    # Filtres
    role_filter = request.GET.get("role", "")
    search_query = request.GET.get("q", "")
    active_filter = request.GET.get("active", "")

    users = User.objects.all()

    if role_filter:
        users = users.filter(role=role_filter)
    if search_query:
        users = users.filter(
            Q(nom__icontains=search_query)
            | Q(prenom__icontains=search_query)
            | Q(email__icontains=search_query)
        )
    if active_filter == "true":
        users = users.filter(actif=True)
    elif active_filter == "false":
        users = users.filter(actif=False)

    users = users.order_by("nom", "prenom")

    # Pagination
    paginator = Paginator(users, 25)
    users_page = safe_get_page(paginator, request.GET.get("page"))

    return render(
        request,
        "dashboard/admin_users.html",
        {
            "users": users_page,
            "role_filter": role_filter,
            "search_query": search_query,
            "active_filter": active_filter,
        },
    )


@login_required
@admin_required
@require_http_methods(["GET", "POST"])
def admin_user_create(request):
    """Création d'un nouvel utilisateur"""

    if request.method == "POST":
        form = UserForm(request.POST)
        if form.is_valid():
            user = form.save()
            log_action(
                request.user,
                f"CRITIQUE: Création de l'utilisateur '{user.email}' (Rôle: {user.get_role_display()}, Nom: {user.get_full_name()}) - Gestion des utilisateurs",
                request,
                niveau="CRITIQUE",
                objet_type="USER",
                objet_id=user.id_utilisateur,
            )
            messages.success(request, f"Utilisateur '{user.email}' créé avec succès.")
            return redirect("dashboard:admin_users")
    else:
        form = UserForm()

    return render(
        request,
        "dashboard/admin_user_form.html",
        {
            "form": form,
            "title": "Créer un utilisateur",
            "editing_user": None,  # Pas d'utilisateur en cours d'édition lors de la création
        },
    )


@login_required
@admin_required
@require_http_methods(["GET", "POST"])
def admin_user_edit(request, user_id):
    """Modification d'un utilisateur"""

    user = get_object_or_404(User, id_utilisateur=user_id)

    if request.method == "POST":
        old_role = user.role
        old_active = user.actif
        form = UserForm(request.POST, instance=user)
        if form.is_valid():
            user = form.save()

            # Journaliser les changements de rôle
            if old_role != user.role:
                old_role_display = dict(User.Role.choices).get(old_role, old_role)
                log_action(
                    request.user,
                    f"CRITIQUE: Modification du rôle de '{user.email}' de {old_role_display} à {user.get_role_display()} - Gestion des utilisateurs",
                    request,
                    niveau="CRITIQUE",
                    objet_type="USER",
                    objet_id=user.id_utilisateur,
                )
            if old_active != user.actif:
                action = "activé" if user.actif else "désactivé"
                log_action(
                    request.user,
                    f"CRITIQUE: Compte '{user.email}' {action} (Gestion des utilisateurs - {'Réactivation' if user.actif else 'Désactivation'})",
                    request,
                    niveau="CRITIQUE",
                    objet_type="USER",
                    objet_id=user.id_utilisateur,
                )

            messages.success(
                request, f"Utilisateur '{user.email}' modifié avec succès."
            )
            return redirect("dashboard:admin_users")
    else:
        form = UserForm(instance=user)

    return render(
        request,
        "dashboard/admin_user_form.html",
        {
            "form": form,
            "editing_user": user,  # Utilisateur en cours d'édition
            "title": f"Modifier l'utilisateur {user.get_full_name()}",
        },
    )


@login_required
@admin_required
@require_http_methods(["POST"])
def admin_user_reset_password(request, user_id):
    """Réinitialisation du mot de passe d'un utilisateur"""

    user = get_object_or_404(User, id_utilisateur=user_id)

    new_password = (request.POST.get("new_password") or "").strip()
    if not new_password:
        messages.error(request, "Le mot de passe ne peut pas être vide.")
        return redirect("dashboard:admin_user_edit", user_id=user_id)

    try:
        validate_password(new_password, user=user)
    except ValidationError as exc:
        for error in exc.messages:
            messages.error(request, error)
        return redirect("dashboard:admin_user_edit", user_id=user_id)

    with transaction.atomic():
        user.set_password(new_password)
        # Forcer l'utilisateur à changer son mot de passe à la prochaine connexion
        user.must_change_password = True
        user.save(update_fields=["password", "must_change_password"])
        log_action(
            request.user,
            f"CRITIQUE: Réinitialisation du mot de passe pour '{user.email}' (Gestion des utilisateurs - Action de sécurité)",
            request,
            niveau="CRITIQUE",
            objet_type="USER",
            objet_id=user.id_utilisateur,
        )
    messages.success(
        request,
        f"Mot de passe réinitialisé pour '{user.email}'. L'utilisateur devra le changer lors de sa prochaine connexion.",
    )

    return redirect("dashboard:admin_user_edit", user_id=user_id)


# ---------------------------------------------------------------------------
# Réinitialisation de la 2FA (perte du téléphone)
# ---------------------------------------------------------------------------


@login_required
@admin_required
@require_http_methods(["POST"])
def admin_user_reset_2fa(request, user_id):
    """
    Réinitialise la 2FA d'un utilisateur (cas : perte du téléphone).

    Cette action :
      - désactive la 2FA (two_factor_enabled=False)
      - efface le secret TOTP
      - supprime tous les codes de secours existants

    L'utilisateur pourra se reconnecter avec son seul mot de passe puis
    réactiver la 2FA depuis son profil s'il le souhaite.

    Action CRITIQUE — journalisée dans l'audit.
    """
    user = get_object_or_404(User, id_utilisateur=user_id)

    if not user.two_factor_enabled and not TwoFactorBackupCode.objects.filter(
        user=user
    ).exists():
        messages.info(
            request,
            f"L'utilisateur '{user.email}' n'a pas la 2FA activée.",
        )
        return redirect("dashboard:admin_user_edit", user_id=user_id)

    with transaction.atomic():
        user.two_factor_enabled = False
        user.two_factor_secret = ""
        user.save(update_fields=["two_factor_enabled", "two_factor_secret"])
        TwoFactorBackupCode.objects.filter(user=user).delete()

        log_action(
            request.user,
            f"CRITIQUE: Réinitialisation 2FA pour '{user.email}' "
            f"(Gestion des utilisateurs - Perte téléphone / action admin)",
            request,
            niveau="CRITIQUE",
            objet_type="USER",
            objet_id=user.id_utilisateur,
        )

    messages.success(
        request,
        f"2FA réinitialisée pour '{user.email}'. "
        "L'utilisateur pourra se connecter avec son mot de passe seul.",
    )
    return redirect("dashboard:admin_user_edit", user_id=user_id)


# ---------------------------------------------------------------------------
# Audit par utilisateur
# ---------------------------------------------------------------------------


@login_required
@admin_required
@require_GET
def admin_user_audit(request, user_id):
    """Consultation des journaux d'audit pour un utilisateur spécifique"""

    user = get_object_or_404(User, id_utilisateur=user_id)
    logs = LogAudit.objects.filter(id_utilisateur=user).order_by("-date_action")

    # Pagination
    paginator = Paginator(logs, 50)
    logs_page = safe_get_page(paginator, request.GET.get("page"))

    return render(
        request,
        "dashboard/admin_user_audit.html",
        {
            "user": user,
            "logs": logs_page,
        },
    )


# ---------------------------------------------------------------------------
# Suppression utilisateurs (unitaire et en lot)
# ---------------------------------------------------------------------------


@login_required
@admin_required
@require_http_methods(["POST"])
def admin_users_delete_multiple(request):
    """Suppression multiple d'utilisateurs avec verifications de securite"""

    try:
        raw_user_ids = request.POST.getlist("user_ids")

        if not raw_user_ids:
            messages.error(request, "Aucun utilisateur selectionne.")
            return redirect("dashboard:admin_users")

        user_ids = []
        for raw_user_id in raw_user_ids:
            try:
                user_ids.append(int(raw_user_id))
            except (TypeError, ValueError):
                continue
        # Deduplicate while preserving input order.
        user_ids = list(dict.fromkeys(user_ids))

        if not user_ids:
            messages.error(request, "Aucun identifiant utilisateur valide recu.")
            return redirect("dashboard:admin_users")

        deleted_count = 0
        deactivated_count = 0
        failed_count = 0
        errors = []

        with transaction.atomic():
            # Lock targeted users to prevent concurrent create/delete races on FK references.
            locked_users = list(
                User.objects.select_for_update().filter(id_utilisateur__in=user_ids)
            )
            users_by_id = {user.id_utilisateur: user for user in locked_users}

            selected_user_ids = [
                uid for uid in users_by_id.keys() if uid != request.user.id_utilisateur
            ]

            inscriptions_count_map = {}
            absences_encoded_count_map = {}
            audit_logs_count_map = {}
            cours_count_map = {}

            if selected_user_ids:
                inscriptions_count_map = dict(
                    Inscription.objects.filter(id_etudiant_id__in=selected_user_ids)
                    .values("id_etudiant_id")
                    .annotate(total=Count("id_inscription"))
                    .values_list("id_etudiant_id", "total")
                )
                absences_encoded_count_map = dict(
                    Absence.objects.filter(encodee_par_id__in=selected_user_ids)
                    .values("encodee_par_id")
                    .annotate(total=Count("id_absence"))
                    .values_list("encodee_par_id", "total")
                )
                audit_logs_count_map = dict(
                    LogAudit.objects.filter(id_utilisateur_id__in=selected_user_ids)
                    .values("id_utilisateur_id")
                    .annotate(total=Count("id_log"))
                    .values_list("id_utilisateur_id", "total")
                )
                cours_count_map = dict(
                    Cours.objects.filter(professeur_id__in=selected_user_ids)
                    .values("professeur_id")
                    .annotate(total=Count("id_cours"))
                    .values_list("professeur_id", "total")
                )

            to_deactivate_ids = {
                uid
                for uid in selected_user_ids
                if (
                    inscriptions_count_map.get(uid, 0) > 0
                    or absences_encoded_count_map.get(uid, 0) > 0
                    or audit_logs_count_map.get(uid, 0) > 0
                )
            }
            if to_deactivate_ids:
                User.objects.filter(id_utilisateur__in=to_deactivate_ids).update(
                    actif=False
                )

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

                    if user.id_utilisateur in to_deactivate_ids:
                        log_action(
                            request.user,
                            f"CRITIQUE: Desactivation de l'utilisateur '{user.email}' (ID: {user.id_utilisateur}) - Dependances detectees (suppression multiple)",
                            request,
                            niveau="CRITIQUE",
                            objet_type="USER",
                            objet_id=user.id_utilisateur,
                        )
                        deactivated_count += 1
                        continue

                    cours_count = cours_count_map.get(user.id_utilisateur, 0)
                    if cours_count > 0:
                        Cours.objects.filter(professeur=user).update(professeur=None)

                    user_email = user.email
                    user_name = user.get_full_name()
                    user_role = user.get_role_display()
                    user_id_for_log = user.id_utilisateur

                    try:
                        user.delete()
                        log_action(
                            request.user,
                            f"CRITIQUE: Suppression de l'utilisateur '{user_email}' (ID: {user_id_for_log}, Role: {user_role}, Nom: {user_name}) - Suppression multiple",
                            request,
                            niveau="CRITIQUE",
                            objet_type="USER",
                            objet_id=user_id_for_log,
                        )
                        deleted_count += 1
                    except ProtectedError:
                        # Safety net against edge cases during concurrent write loads.
                        User.objects.filter(id_utilisateur=user_id_for_log).update(
                            actif=False
                        )
                        log_action(
                            request.user,
                            f"CRITIQUE: Desactivation de l'utilisateur '{user_email}' (ID: {user_id_for_log}) - Dependances detectees pendant suppression",
                            request,
                            niveau="CRITIQUE",
                            objet_type="USER",
                            objet_id=user_id_for_log,
                        )
                        deactivated_count += 1
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
                request, f"{deleted_count} utilisateur(s) supprime(s) avec succes."
            )
        if deactivated_count > 0:
            messages.warning(
                request,
                f"{deactivated_count} utilisateur(s) desactive(s) (dependances detectees).",
            )
        if failed_count > 0:
            error_msg = f"{failed_count} utilisateur(s) n'ont pas pu etre supprime(s)."
            if errors:
                error_msg += " Details : " + " ; ".join(errors[:5])
            messages.error(request, error_msg)

        return redirect("dashboard:admin_users")

    except Exception:
        logger.exception("Erreur lors de la suppression multiple")
        messages.error(
            request,
            "Erreur interne lors de la suppression multiple. "
            "Veuillez verifier les dependances ou contacter l'administrateur systeme.",
        )
        return redirect("dashboard:admin_users")


@login_required
@admin_required
@require_http_methods(["GET", "POST"])
def admin_user_delete(request, user_id):
    """Suppression d'un utilisateur avec verifications de securite"""

    try:
        user = get_object_or_404(User, id_utilisateur=user_id)

        # Verification 1: Ne pas supprimer soi-meme
        if user == request.user:
            messages.error(request, "Vous ne pouvez pas supprimer votre propre compte.")
            return redirect("dashboard:admin_users")

        # Verification 2: Ne pas supprimer le dernier admin actif
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

        # FIX VERT #19 — Page de confirmation avant suppression définitive
        if request.method == "GET":
            if (
                inscriptions_count > 0
                or absences_encoded_count > 0
                or audit_logs_count > 0
            ):
                # Pas de page de confirmation : on sait déjà que ce sera une désactivation
                cascade_items = [
                    item
                    for item in [
                        {"count": inscriptions_count, "label": "inscription(s)"},
                        {
                            "count": absences_encoded_count,
                            "label": "absence(s) encodée(s)",
                        },
                        {"count": audit_logs_count, "label": "entrée(s) d'audit"},
                    ]
                    if item["count"] > 0
                ]
                return render(
                    request,
                    "dashboard/admin_confirm_delete.html",
                    {
                        "object_label": f"Utilisateur « {user.get_full_name()} » ({user.email})",
                        "cascade_items": cascade_items,
                        "extra_warning": "Des dépendances ont été détectées. Le compte sera DÉSACTIVÉ (pas supprimé).",
                        "cancel_url": "/dashboard/admin/users/",
                        "cancel_label": "Utilisateurs",
                    },
                )
            else:
                cascade_items = [
                    item
                    for item in [
                        {
                            "count": cours_count,
                            "label": "cours (sera détaché du professeur)",
                        },
                    ]
                    if item["count"] > 0
                ]
                return render(
                    request,
                    "dashboard/admin_confirm_delete.html",
                    {
                        "object_label": f"Utilisateur « {user.get_full_name()} » ({user.email})",
                        "cascade_items": cascade_items,
                        "cancel_url": "/dashboard/admin/users/",
                        "cancel_label": "Utilisateurs",
                    },
                )

        if inscriptions_count > 0 or absences_encoded_count > 0 or audit_logs_count > 0:
            user.actif = False
            user.save(update_fields=["actif"])
            log_action(
                request.user,
                f"CRITIQUE: Desactivation de l'utilisateur '{user.email}' (ID: {user.id_utilisateur}) - Dependances detectees",
                request,
                niveau="CRITIQUE",
                objet_type="USER",
                objet_id=user.id_utilisateur,
            )
            messages.warning(
                request,
                "Suppression bloquee: l'utilisateur a des dependances. Le compte a ete desactive.",
            )
            return redirect("dashboard:admin_users")

        user_email = user.email
        user_name = user.get_full_name()
        user_role = user.get_role_display()
        user_id_for_log = user.id_utilisateur

        try:
            with transaction.atomic():
                if cours_count > 0:
                    Cours.objects.filter(professeur=user).update(professeur=None)

                user.groups.clear()
                user.user_permissions.clear()
                user.delete()

                log_action(
                    request.user,
                    f"CRITIQUE: Suppression de l'utilisateur '{user_email}' (ID: {user_id_for_log}, Role: {user_role}, Nom: {user_name}) - Gestion des utilisateurs",
                    request,
                    niveau="CRITIQUE",
                    objet_type="USER",
                    objet_id=user_id_for_log,
                )

            messages.success(request, f"Utilisateur '{user_email}' supprime avec succes.")

        except ProtectedError:
            # Race condition: a PROTECT FK was created after the count checks.
            # Fall back to deactivation.
            user.actif = False
            user.save(update_fields=["actif"])
            log_action(
                request.user,
                f"CRITIQUE: Desactivation (fallback) de l'utilisateur '{user_email}' "
                f"(ID: {user_id_for_log}) - Dependances PROTECT detectees lors de la suppression",
                request,
                niveau="CRITIQUE",
                objet_type="USER",
                objet_id=user_id_for_log,
            )
            messages.warning(
                request,
                f"Des dépendances bloquantes ont été détectées. "
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
            "Veuillez verifier les dependances ou contacter l'administrateur systeme.",
        )
        return redirect("dashboard:admin_users")
