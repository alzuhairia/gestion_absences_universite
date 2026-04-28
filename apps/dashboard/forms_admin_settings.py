"""
FICHIER : apps/dashboard/forms_admin_settings.py
RESPONSABILITE : Formulaires admin — Paramètres système et Années académiques
"""

from django import forms

from apps.academic_sessions.models import AnneeAcademique
from apps.dashboard.models import SystemSettings


class SystemSettingsForm(forms.ModelForm):
    class Meta:
        model = SystemSettings
        fields = [
            "default_absence_threshold",
            "block_type",
            "password_min_length",
            "password_require_uppercase",
            "password_require_lowercase",
            "password_require_numbers",
            "password_require_special",
            "mfa_enabled_globally",
            "data_retention_days",
            "gps_latitude",
            "gps_longitude",
            "gps_radius_meters",
            "qr_token_duration_seconds",
        ]
        widgets = {
            "default_absence_threshold": forms.NumberInput(
                attrs={"class": "form-control"}
            ),
            "block_type": forms.Select(attrs={"class": "form-select"}),
            "password_min_length": forms.NumberInput(attrs={"class": "form-control"}),
            "password_require_uppercase": forms.CheckboxInput(
                attrs={"class": "form-check-input"}
            ),
            "password_require_lowercase": forms.CheckboxInput(
                attrs={"class": "form-check-input"}
            ),
            "password_require_numbers": forms.CheckboxInput(
                attrs={"class": "form-check-input"}
            ),
            "password_require_special": forms.CheckboxInput(
                attrs={"class": "form-check-input"}
            ),
            "mfa_enabled_globally": forms.CheckboxInput(
                attrs={"class": "form-check-input"}
            ),
            "data_retention_days": forms.NumberInput(attrs={"class": "form-control"}),
            "gps_latitude": forms.NumberInput(
                attrs={"class": "form-control", "step": "0.00001", "placeholder": "ex: 36.75250"}
            ),
            "gps_longitude": forms.NumberInput(
                attrs={"class": "form-control", "step": "0.00001", "placeholder": "ex: 3.04200"}
            ),
            "gps_radius_meters": forms.NumberInput(
                attrs={"class": "form-control", "min": "10", "max": "5000"}
            ),
            "qr_token_duration_seconds": forms.NumberInput(
                attrs={"class": "form-control", "min": "15", "max": "600"}
            ),
        }
        labels = {
            "default_absence_threshold": "Seuil d'Absence par Défaut (%)",
            "block_type": "Type de Blocage",
            "password_min_length": "Longueur Minimale du Mot de Passe",
            "password_require_uppercase": "Exiger Majuscules",
            "password_require_lowercase": "Exiger Minuscules",
            "password_require_numbers": "Exiger Chiffres",
            "password_require_special": "Exiger Caractères Spéciaux",
            "mfa_enabled_globally": "Authentification à Deux Facteurs (Globale)",
            "data_retention_days": "Rétention des Données (jours)",
        }
        help_texts = {
            "default_absence_threshold": "Seuil par défaut appliqué aux nouveaux cours",
            "block_type": "Comportement lorsque le seuil est dépassé",
            "data_retention_days": "Durée de conservation des données personnelles",
        }


class AnneeAcademiqueForm(forms.ModelForm):
    class Meta:
        model = AnneeAcademique
        fields = ["libelle", "active"]
        widgets = {
            "libelle": forms.TextInput(attrs={"class": "form-control"}),
            "active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }
        labels = {
            "libelle": "Libellé",
            "active": "Définir comme Année Active",
        }
        help_texts = {
            "libelle": "Format recommandé: AAAA-AAAA (ex: 2023-2024)",
            "active": "Une seule année peut être active à la fois. L'année précédente sera automatiquement désactivée.",
        }

    def save(self, commit=True):
        instance = super().save(commit=False)
        if commit:
            if instance.active:
                from django.db import transaction

                with transaction.atomic():
                    AnneeAcademique.objects.exclude(pk=instance.pk).filter(
                        active=True
                    ).update(active=False)
                    instance.save()
            else:
                instance.save()
        return instance
