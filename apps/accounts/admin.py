"""
Configuration de l'admin Django pour l'application accounts de UniAbsences.

Ce module enregistre le modèle ``User`` personnalisé auprès du site
d'administration Django et fournit une interface d'admin sur mesure qui
prend en compte le modèle d'authentification du projet basé sur l'email
(pas de champ username) et la propriété virtuelle ``is_active`` (mappée
sur la colonne ``actif`` en base de données).

Classes
-------
``UserCreationForm``
    Un ``ModelForm`` qui remplace le schéma de création par défaut de Django
    à deux champs (password1 / password2) par un unique champ ``password`` ;
    la validation appelle le pipeline intégré ``validate_password`` de Django
    (y compris ``SystemSettingsPasswordValidator``).

``UserAdmin``
    Personnalise ``BaseUserAdmin`` pour le modèle ``User`` du projet : adapte
    les fieldsets, l'affichage en liste, la recherche et la sélection du
    formulaire pour correspondre aux champs spécifiques à l'université
    (``nom``, ``prenom``, ``role``, ``actif``).

Fait partie du système accounts de UniAbsences.
"""

from django import forms
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.password_validation import validate_password
from django.utils.translation import gettext_lazy as _

from .models import User


class UserCreationForm(forms.ModelForm):
    """
    Formulaire d'admin pour créer un nouveau ``User`` avec un seul champ de mot de passe en clair.

    Diffère du ``UserCreationForm`` intégré de Django de deux façons :
    - Utilise un seul champ ``password`` au lieu d'une paire de confirmation.
    - Exécute le pipeline complet ``validate_password`` de Django sur la
      valeur soumise afin que ``SystemSettingsPasswordValidator`` et tout
      autre validateur configuré soient appliqués avant la sauvegarde de
      l'enregistrement.
    """

    password = forms.CharField(label="Mot de passe", widget=forms.PasswordInput)

    class Meta:
        """Configuration ModelForm : modèle ``User`` et champs exposés à la création depuis l'admin."""

        model = User
        fields = ("email", "nom", "prenom", "role", "actif")

    def clean_password(self):
        """
        Valide le mot de passe soumis face aux validateurs configurés.

        Construit une instance ``User`` temporaire à partir des autres champs
        du formulaire afin que les vérifications de similarité d'attributs
        utilisateur (par exemple ``UserAttributeSimilarityValidator`` intégré
        à Django) disposent du contexte complet dont elles ont besoin.

        Retourne :
            str: Le mot de passe en clair validé.

        Lève :
            forms.ValidationError: Si un validateur de mot de passe configuré
                                   rejette la valeur.
        """
        password = self.cleaned_data.get("password")
        if password:
            # Construit un objet User partiel pour les vérifications de similarité/contexte.
            user = User(
                email=self.cleaned_data.get("email", ""),
                nom=self.cleaned_data.get("nom", ""),
                prenom=self.cleaned_data.get("prenom", ""),
            )
            validate_password(password, user=user)
        return password

    def save(self, commit=True):
        """
        Hache le mot de passe avant de persister le nouvel enregistrement utilisateur.

        Appelle ``set_password`` sur l'instance non sauvegardée pour que la
        valeur en clair issue du formulaire ne soit jamais écrite en base
        de données.

        Paramètres :
            commit (bool): Si ``True`` (par défaut) l'instance est sauvegardée
                           immédiatement en base de données.

        Retourne :
            User: La nouvelle instance d'utilisateur créée.
        """
        user = super().save(commit=False)
        # Hache le mot de passe en clair avant toute écriture en base.
        user.set_password(self.cleaned_data["password"])
        if commit:
            user.save()
        return user


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    """
    Configuration de l'admin Django pour le modèle ``User``.

    Adapte ``BaseUserAdmin`` au modèle utilisateur du projet basé sur l'email
    et piloté par les rôles. Principales différences par rapport au UserAdmin
    Django par défaut :

    - Le formulaire de création et le formulaire de modification utilisent
      tous deux ``UserCreationForm`` (aucun ``UserChangeForm`` séparé n'est
      nécessaire puisque le modèle n'a pas de champ username et que le mot
      de passe est géré via le champ unique).
    - ``is_active`` est exposé via la colonne ``actif`` ; la liste et le
      filtre de l'admin utilisent ``actif`` directement.
    - ``date_creation`` est en lecture seule — elle est définie automatiquement
      à la première sauvegarde.
    """

    add_form = UserCreationForm
    form = UserCreationForm

    # ── Vue en liste ──────────────────────────────────────────────────────
    list_display = ("email", "nom", "prenom", "role", "actif", "date_creation")
    list_filter = ("role", "actif", "date_creation")
    search_fields = ("email", "nom", "prenom")
    ordering = ("nom", "prenom")

    # ── Disposition du formulaire de modification / ajout ─────────────────
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        (_("Informations personnelles"), {"fields": ("nom", "prenom")}),
        (_("Rôle et statut"), {"fields": ("role", "actif")}),
        (
            _("Permissions"),
            {
                "fields": ("groups", "user_permissions"),
            },
        ),
        (_("Dates importantes"), {"fields": ("date_creation",)}),
    )

    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("email", "nom", "prenom", "password", "role", "actif"),
            },
        ),
    )

    # ``date_creation`` est définie automatiquement ; la modifier directement casserait la piste d'audit.
    readonly_fields = ("date_creation",)

    def get_form(self, request, obj=None, change=False, **kwargs):
        """
        Retourne la classe de formulaire appropriée pour l'action admin en cours.

        Utilise ``add_form`` (``UserCreationForm``) lors de la création d'un
        nouvel utilisateur (``obj is None``) et le ``form`` par défaut pour
        les modifications.

        Paramètres :
            request: La requête HTTP en cours.
            obj: L'instance ``User`` en cours d'édition, ou ``None`` lors
                 de la création.
            change (bool): ``True`` lors de l'édition d'un objet existant.
            **kwargs: Arguments nommés additionnels transmis au parent.

        Retourne :
            type: Une sous-classe de ``ModelForm`` adaptée à l'opération en cours.
        """
        defaults = {}
        if obj is None:
            # Flux de création — utilise le formulaire à champ de mot de passe unique.
            defaults["form"] = self.add_form
        defaults.update(kwargs)
        return super().get_form(request, obj, change=change, **defaults)
