"""
FICHIER : apps/accounts/forms.py
RESPONSABILITE : Formulaires d'authentification et de mots de passe
FONCTIONNALITES PRINCIPALES :
  - CustomAuthenticationForm : formulaire de connexion stylise
  - CustomUserCreationForm : creation utilisateur avec validation mot de passe
  - CustomPasswordResetForm : demande de reinitialisation mot de passe
  - CustomSetPasswordForm : definition nouveau mot de passe apres reset
  - CustomPasswordChangeForm : changement de mot de passe utilisateur connecte
DEPENDANCES CLES : django.contrib.auth.forms, apps.accounts.models
"""

from django import forms
from django.contrib.auth.forms import (
    AuthenticationForm,
    PasswordChangeForm,
    PasswordResetForm,
    SetPasswordForm,
    UserCreationForm,
)

from .models import User


class CustomAuthenticationForm(AuthenticationForm):
    username = forms.CharField(
        label="Nom d'utilisateur ou Email",
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )
    password = forms.CharField(
        label="Mot de passe",
        widget=forms.PasswordInput(attrs={"class": "form-control"}),
    )


class CustomUserCreationForm(UserCreationForm):
    class Meta:
        model = User
        fields = ("email", "nom", "prenom", "role")


class CustomPasswordResetForm(PasswordResetForm):
    """Formulaire de demande de réinitialisation du mot de passe avec labels en français.

    Overrides get_users() because the custom User model uses 'actif' instead of
    Django's default 'is_active' field.
    """

    email = forms.EmailField(
        label="Adresse email",
        max_length=254,
        widget=forms.EmailInput(
            attrs={
                "class": "form-control form-control-lg",
                "placeholder": "exemple@universite.edu",
                "autocomplete": "email",
            }
        ),
    )

    def get_users(self, email):
        """Return active users matching the given email (uses 'actif' field)."""
        active_users = User.objects.filter(
            email__iexact=email,
            actif=True,
        )
        return (
            u
            for u in active_users
            if u.has_usable_password()
        )


class CustomSetPasswordForm(SetPasswordForm):
    """Formulaire de définition du nouveau mot de passe avec labels en français"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["new_password1"].label = "Nouveau mot de passe"
        self.fields["new_password1"].help_text = (
            "Votre nouveau mot de passe doit contenir au moins 8 caractères"
        )
        self.fields["new_password1"].widget.attrs.update(
            {
                "class": "form-control form-control-lg",
                "placeholder": "••••••••",
                "autocomplete": "new-password",
            }
        )

        self.fields["new_password2"].label = "Confirmer le nouveau mot de passe"
        self.fields["new_password2"].help_text = (
            "Entrez à nouveau le nouveau mot de passe pour confirmation"
        )
        self.fields["new_password2"].widget.attrs.update(
            {
                "class": "form-control form-control-lg",
                "placeholder": "••••••••",
                "autocomplete": "new-password",
            }
        )


class CustomPasswordChangeForm(PasswordChangeForm):
    """Formulaire personnalisé pour le changement de mot de passe avec labels en français"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Personnaliser les labels en français
        self.fields["old_password"].label = "Ancien mot de passe"
        self.fields["old_password"].help_text = "Entrez votre mot de passe actuel"
        self.fields["old_password"].widget.attrs.update(
            {
                "class": "form-control form-control-lg",
                "placeholder": "••••••••",
                "autocomplete": "current-password",
            }
        )

        self.fields["new_password1"].label = "Nouveau mot de passe"
        self.fields["new_password1"].help_text = (
            "Votre nouveau mot de passe doit contenir au moins 8 caractères"
        )
        self.fields["new_password1"].widget.attrs.update(
            {
                "class": "form-control form-control-lg",
                "placeholder": "••••••••",
                "autocomplete": "new-password",
            }
        )

        self.fields["new_password2"].label = "Confirmer le nouveau mot de passe"
        self.fields["new_password2"].help_text = (
            "Entrez à nouveau le nouveau mot de passe pour confirmation"
        )
        self.fields["new_password2"].widget.attrs.update(
            {
                "class": "form-control form-control-lg",
                "placeholder": "••••••••",
                "autocomplete": "new-password",
            }
        )
