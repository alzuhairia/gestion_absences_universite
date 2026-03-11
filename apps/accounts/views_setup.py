"""
One-time initial setup view for creating the first admin account.

This view is only accessible when NO admin account exists in the database.
Once an admin is created (via this page or the management command), the
page returns 404 permanently.
"""

from django import forms
from django.http import Http404
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

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
        label="Mot de passe",
        widget=forms.PasswordInput(
            attrs={"class": "form-control", "placeholder": "Minimum 8 caractères"}
        ),
    )
    password_confirm = forms.CharField(
        min_length=8,
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
            # Double-check no admin was created between GET and POST
            if _admin_exists():
                raise Http404

            User.objects.create_superuser(
                email=form.cleaned_data["email"],
                nom=form.cleaned_data["nom"],
                prenom=form.cleaned_data["prenom"],
                password=form.cleaned_data["password"],
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
