"""
FICHIER : apps/dashboard/forms_admin_academic.py
RESPONSABILITE : Formulaires académiques admin — Facultés, Départements, Cours
"""

from django import forms

from apps.academic_sessions.models import AnneeAcademique
from apps.academics.models import Cours, Departement, Faculte
from apps.accounts.models import User


class FaculteForm(forms.ModelForm):
    class Meta:
        model = Faculte
        fields = ["nom_faculte", "actif"]
        widgets = {
            "nom_faculte": forms.TextInput(attrs={"class": "form-control"}),
            "actif": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }
        labels = {
            "nom_faculte": "Nom de la Faculté",
            "actif": "Actif",
        }
        help_texts = {
            "actif": "Désactiver une faculté la masque sans la supprimer",
        }


class DepartementForm(forms.ModelForm):
    class Meta:
        model = Departement
        fields = ["nom_departement", "id_faculte", "actif"]
        widgets = {
            "nom_departement": forms.TextInput(attrs={"class": "form-control"}),
            "id_faculte": forms.Select(attrs={"class": "form-select"}),
            "actif": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }
        labels = {
            "nom_departement": "Nom du Département",
            "id_faculte": "Faculté de rattachement",
            "actif": "Actif",
        }
        help_texts = {
            "actif": "Désactiver un département le masque sans le supprimer",
        }


class CoursForm(forms.ModelForm):
    prerequisites = forms.ModelMultipleChoiceField(
        queryset=Cours.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple(attrs={"class": "form-check-input"}),
        help_text="Cochez les cours qui sont des prérequis pour ce cours. Laissez vide si aucun prérequis n'est requis.",
    )

    class Meta:
        model = Cours
        fields = [
            "code_cours",
            "nom_cours",
            "nombre_total_periodes",
            "seuil_absence",
            "id_departement",
            "niveau",
            "professeur",
            "prerequisites",
            "actif",
        ]
        widgets = {
            "code_cours": forms.TextInput(attrs={"class": "form-control"}),
            "nom_cours": forms.TextInput(attrs={"class": "form-control"}),
            "nombre_total_periodes": forms.NumberInput(attrs={"class": "form-control"}),
            "seuil_absence": forms.NumberInput(attrs={"class": "form-control"}),
            "id_departement": forms.Select(attrs={"class": "form-select"}),
            "niveau": forms.Select(attrs={"class": "form-select"}),
            "professeur": forms.Select(attrs={"class": "form-select"}),
            "actif": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._resolved_year = None
        self.fields["id_departement"].queryset = Departement.objects.filter(actif=True)
        self.fields["professeur"].queryset = User.objects.filter(
            role=User.Role.PROFESSEUR, actif=True
        )

        if "id_annee" in self.fields:
            self.fields["id_annee"].queryset = AnneeAcademique.objects.all().order_by(
                "-libelle"
            )
            self.fields["id_annee"].widget = forms.HiddenInput()

        self.fields["niveau"].required = True

        if self.instance and self.instance.pk:
            current_niveau = self.instance.niveau

            if current_niveau == 1:
                prerequisite_queryset = Cours.objects.none()
            elif current_niveau == 2:
                prerequisite_queryset = (
                    Cours.objects.filter(actif=True, niveau=1)
                    .exclude(id_cours=self.instance.id_cours)
                    .order_by("code_cours")
                )
            elif current_niveau == 3:
                prerequisite_queryset = (
                    Cours.objects.filter(actif=True, niveau__in=[1, 2])
                    .exclude(id_cours=self.instance.id_cours)
                    .order_by("niveau", "code_cours")
                )
            else:
                prerequisite_queryset = (
                    Cours.objects.filter(actif=True)
                    .exclude(id_cours=self.instance.id_cours)
                    .order_by("code_cours")
                )

            self.fields["prerequisites"].queryset = prerequisite_queryset
            self.fields["prerequisites"].initial = self.instance.prerequisites.all()
        else:
            submitted_niveau = self.data.get("niveau") if self.is_bound else None
            if submitted_niveau:
                try:
                    submitted_niveau = int(submitted_niveau)
                except (TypeError, ValueError):
                    submitted_niveau = None

            if submitted_niveau and submitted_niveau >= 2:
                self.fields["prerequisites"].queryset = Cours.objects.filter(
                    actif=True, niveau__lt=submitted_niveau
                ).order_by("niveau", "code_cours")
            else:
                self.fields["prerequisites"].queryset = Cours.objects.none()

        self.fields["code_cours"].label = "Code du Cours"
        self.fields["nom_cours"].label = "Intitulé du Cours"
        self.fields["nombre_total_periodes"].label = "Total Périodes (h)"
        self.fields["seuil_absence"].label = "Seuil d'Absence (%)"
        self.fields["id_departement"].label = "Département"
        self.fields["niveau"].label = "Niveau d'étude"
        if "id_annee" in self.fields:
            self.fields["id_annee"].label = "Année Académique"
        self.fields["professeur"].label = "Professeur Responsable"
        self.fields["prerequisites"].label = "Prérequis"
        self.fields["actif"].label = "Actif"

        self.fields["niveau"].help_text = (
            "Niveau du cours (1, 2 ou 3). Détermine les prérequis autorisés."
        )
        self.fields["seuil_absence"].help_text = (
            "Seuil personnalisé pour ce cours. Si vide, utilise le seuil par défaut du système."
        )
        self.fields["actif"].help_text = (
            "Désactiver un cours le masque sans le supprimer"
        )

    def clean(self):
        cleaned_data = super().clean()
        if not self.instance.pk:
            active_year = AnneeAcademique.objects.filter(active=True).first()
            if not active_year:
                active_year = AnneeAcademique.objects.order_by("-libelle").first()
            if not active_year:
                raise forms.ValidationError(
                    "Impossible de créer un cours : aucune année académique n'est définie dans le système."
                )
            self._resolved_year = active_year
        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)

        if not instance.pk:
            instance.id_annee = self._resolved_year

        if commit:
            instance.save()
            instance.prerequisites.set(self.cleaned_data["prerequisites"])
        return instance
