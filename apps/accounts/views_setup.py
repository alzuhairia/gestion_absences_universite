"""
FICHIER : apps/accounts/views_setup.py
RESPONSABILITE : Configuration initiale - creation du premier administrateur
FONCTIONNALITES PRINCIPALES :
  - Page unique de setup (accessible uniquement si aucun admin n'existe)
  - Formulaire de creation du premier admin avec validation
DEPENDANCES CLES : accounts.models
"""

from django import forms
from django.contrib.auth.password_validation import validate_password
from django.db import transaction
from django.http import Http404
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from apps.audits.utils import log_action

from .models import User


def _admin_exists():
    return User.objects.filter(role=User.Role.ADMIN).exists()


class InitialAdminForm(forms.Form):
    prenom = forms.CharField(
        max_length=100,
        label="Prénom",
        widget=forms.TextInput(
            attrs={"class": "form-control", "placeholder": "Prénom", "autofocus": True}
        ),
    )
    nom = forms.CharField(
        max_length=100,
        label="Nom",
        widget=forms.TextInput(
            attrs={"class": "form-control", "placeholder": "Nom"}
        ),
    )
    email = forms.EmailField(
        max_length=255,
        label="Adresse email",
        widget=forms.EmailInput(
            attrs={"class": "form-control", "placeholder": "admin@example.com"}
        ),
    )
    password = forms.CharField(
        min_length=8,
        max_length=128,
        label="Mot de passe",
        widget=forms.PasswordInput(
            attrs={"class": "form-control", "placeholder": "Minimum 8 caractères"}
        ),
    )
    password_confirm = forms.CharField(
        min_length=8,
        max_length=128,
        label="Confirmer le mot de passe",
        widget=forms.PasswordInput(
            attrs={"class": "form-control", "placeholder": "Retapez le mot de passe"}
        ),
    )

    def clean_email(self):
        email = self.cleaned_data["email"]
        if User.objects.filter(email=email).exists():
            raise forms.ValidationError("Un utilisateur avec cet email existe déjà.")
        return email

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get("password")
        password_confirm = cleaned_data.get("password_confirm")
        if password and password_confirm and password != password_confirm:
            raise forms.ValidationError("Les mots de passe ne correspondent pas.")
        if password:
            validate_password(password)
        return cleaned_data


@require_http_methods(["GET", "POST"])
def initial_setup(request):
    """
    One-time setup page. Returns 404 if any admin already exists.
    """
    if _admin_exists():
        raise Http404

    if request.method == "POST":
        form = InitialAdminForm(request.POST)
        if form.is_valid():
            with transaction.atomic():
                # Re-check under transaction to prevent race condition
                if User.objects.select_for_update().filter(role=User.Role.ADMIN).exists():
                    raise Http404

                admin = User.objects.create_superuser(
                    email=form.cleaned_data["email"],
                    nom=form.cleaned_data["nom"],
                    prenom=form.cleaned_data["prenom"],
                    password=form.cleaned_data["password"],
                )
                log_action(
                    admin,
                    f"CRITIQUE: Compte administrateur initial cree via setup ({admin.email})",
                    request,
                    niveau="CRITIQUE",
                    objet_type="USER",
                    objet_id=admin.id_utilisateur,
                )
            return redirect("setup_complete")
    else:
        form = InitialAdminForm()

    return render(request, "accounts/setup.html", {"form": form})


@require_http_methods(["GET"])
def setup_complete(request):
    """
    Success page after initial admin creation.
    Also returns 404 if no admin exists (prevents direct access).
    """
    if not _admin_exists():
        raise Http404

    return render(request, "accounts/setup_complete.html")
