"""
FICHIER : apps/dashboard/forms_admin_users.py
RESPONSABILITE : Formulaire admin pour la création et modification d'utilisateurs
"""

from typing import Any, cast

from django import forms
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError

from apps.accounts.models import User


class UserForm(forms.ModelForm):
    password = forms.CharField(
        required=False,
        max_length=128,
        widget=forms.PasswordInput(attrs={"class": "form-control"}),
        help_text="Laissez vide pour ne pas modifier le mot de passe",
    )
    password_confirm = forms.CharField(
        required=False,
        max_length=128,
        widget=forms.PasswordInput(attrs={"class": "form-control"}),
        label="Confirmer le mot de passe",
        help_text="",
    )

    class Meta:
        model = User
        fields = ["nom", "prenom", "email", "role", "actif"]
        widgets = {
            "nom": forms.TextInput(attrs={"class": "form-control"}),
            "prenom": forms.TextInput(attrs={"class": "form-control"}),
            "email": forms.EmailInput(attrs={"class": "form-control"}),
            "role": forms.Select(attrs={"class": "form-select"}),
            "actif": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        is_creation = not (self.instance and self.instance.pk)

        if is_creation:
            self.fields["password"].required = True
            self.fields["password"].help_text = (
                "Définissez un mot de passe temporaire pour l'utilisateur"
            )
            self.fields["password_confirm"].required = True
            self.fields["password_confirm"].help_text = "Confirmez le mot de passe"
        else:
            self.fields["password"].required = False
            self.fields["password"].help_text = (
                "Laissez vide pour ne pas modifier le mot de passe"
            )
            self.fields["password_confirm"].required = False
            self.fields["password_confirm"].help_text = (
                "Confirmez le nouveau mot de passe (si vous modifiez le mot de passe)"
            )

        self.fields["nom"].label = "Nom"
        self.fields["prenom"].label = "Prénom"
        self.fields["email"].label = "Adresse Email"
        self.fields["role"].label = "Rôle"
        self.fields["actif"].label = "Compte Actif"
        self.fields["password"].label = "Mot de Passe"

    def clean_email(self):
        email = self.cleaned_data.get("email")
        if email:
            qs = User.objects.filter(email=email)
            if self.instance and self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise forms.ValidationError(
                    "Un utilisateur avec cette adresse email existe déjà."
                )
        return email

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get("password")
        password_confirm = cleaned_data.get("password_confirm")
        is_creation = not (self.instance and self.instance.pk)

        if is_creation:
            if not password:
                raise forms.ValidationError(
                    {
                        "password": "Le mot de passe est obligatoire lors de la création d'un utilisateur."
                    }
                )
            if not password_confirm:
                raise forms.ValidationError(
                    {
                        "password_confirm": "La confirmation du mot de passe est obligatoire."
                    }
                )

        if password:
            if password != password_confirm:
                raise forms.ValidationError(
                    {"password_confirm": "Les mots de passe ne correspondent pas."}
                )
            validation_user = (
                self.instance
                if self.instance and self.instance.pk
                else User(
                    email=cleaned_data.get("email", ""),
                    nom=cleaned_data.get("nom", ""),
                    prenom=cleaned_data.get("prenom", ""),
                    role=cleaned_data.get("role") or User.Role.ETUDIANT,
                )
            )
            try:
                validate_password(password, user=validation_user)
            except DjangoValidationError as exc:
                raise forms.ValidationError(
                    {"password": cast(Any, exc.messages)}
                )

        return cleaned_data

    def save(self, commit=True):
        user = super().save(commit=False)
        password = self.cleaned_data.get("password")
        is_creation = not (self.instance and self.instance.pk)

        if password:
            user.set_password(password)
            if is_creation:
                user.must_change_password = True

        if commit:
            user.save()
        return user
