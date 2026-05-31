"""
Formulaires des paramètres système et des années académiques pour le tableau de bord d'administration UniAbsences.

Forms
-----
``SystemSettingsForm``
    Édite l'enregistrement singleton ``SystemSettings`` : seuil
    d'absence par défaut, délai d'inactivité de session et exigences
    de complexité des mots de passe.

``AnneeAcademiqueForm``
    Crée / met à jour une année académique ; le ``save()`` du
    formulaire désactive toutes les autres années lorsque le nouvel
    enregistrement est défini avec ``active = True``.

Fait partie du système de tableau de bord UniAbsences.
"""

from django import forms

from apps.academic_sessions.models import AnneeAcademique
from apps.dashboard.models import SystemSettings


class SystemSettingsForm(forms.ModelForm):
    """
    ModelForm pour l'édition de l'enregistrement singleton ``SystemSettings``.

    Expose tous les paramètres système configurables regroupés en
    quatre sections :

    - **Règles académiques** — seuil d'absence par défaut et type de blocage.
    - **Politique de mots de passe** — longueur minimale et exigences
      de classes de caractères.
    - **MFA** — bascule globale d'authentification à deux facteurs.
    - **Présence GPS / QR** — coordonnées de l'établissement, rayon
      d'acceptation et intervalle de rotation du jeton QR.
    - **RGPD** — durée de conservation des données personnelles en jours.

    Le champ ``data_retention_days`` est exclu des ``labels`` et
    ``help_texts`` ici, et documenté au niveau du modèle à la place.
    """

    class Meta:
        """Configuration ModelForm : modèle ``SystemSettings`` et widgets/labels pour chaque réglage."""

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
    """
    ModelForm pour la création et la mise à jour d'une ``AnneeAcademique`` (année académique).

    Applique la règle métier d'une seule année active : lorsqu'une
    année est sauvegardée avec ``active=True``, ``save()`` désactive
    toutes les autres années actives à l'intérieur d'une transaction
    de base de données de sorte qu'exactement une année soit marquée
    active à tout moment.
    """

    class Meta:
        """Configuration ModelForm : modèle ``AnneeAcademique``, deux champs et widgets Bootstrap."""

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
        """
        Sauvegarde l'année académique en appliquant la contrainte d'une seule année active.

        Lorsque ``active=True``, tous les autres enregistrements
        ``AnneeAcademique`` actuellement actifs sont désactivés de
        manière atomique avant que l'enregistrement nouveau/mis à jour
        soit sauvegardé.

        Parameters
        ----------
        commit : bool, optional
            Lorsque ``False``, retourne l'instance non sauvegardée
            sans toucher à la base de données.  Par défaut ``True``.

        Returns
        -------
        AnneeAcademique
            L'instance d'année académique sauvegardée (ou préparée).
        """
        instance = super().save(commit=False)
        if commit:
            if instance.active:
                from django.db import transaction

                with transaction.atomic():
                    # Désactive toutes les autres années avant d'activer celle-ci.
                    AnneeAcademique.objects.exclude(pk=instance.pk).filter(
                        active=True
                    ).update(active=False)
                    instance.save()
            else:
                instance.save()
        return instance
