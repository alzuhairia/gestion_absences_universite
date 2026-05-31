"""
Formulaires pour l'encodage direct d'absences par le secrétariat.

Ce module fournit le formulaire Django utilisé par le secrétariat pour encoder
directement des absences — en contournant le flux de marquage d'absence du
professeur. Cela est utile lorsqu'un étudiant remet un justificatif papier au
bureau ou lorsque le secrétariat doit enregistrer une absence rétroactivement.

Responsabilités :
  - SecretaryJustifiedAbsenceForm : collecter l'étudiant, la date, les cours
    concernés, le type/la durée d'absence, une plage horaire facultative, un
    commentaire interne et un fichier justificatif facultatif.
  - Filtrer les cours disponibles à l'année académique active.
  - Validation croisée des champs (l'absence partielle requiert une durée ; la
    plage horaire doit être complète et logiquement ordonnée).

Fait partie du système de gestion des absences UniAbsences.
"""

from typing import cast

from django import forms

from apps.absences.models import Absence
from apps.academic_sessions.models import AnneeAcademique
from apps.academics.models import Cours
from apps.accounts.models import User


class SecretaryJustifiedAbsenceForm(forms.Form):
    """
    Formulaire pour le secrétariat permettant d'encoder directement une absence pour un étudiant.

    Permet d'encoder en une seule étape les absences justifiées (avec un
    document justificatif) et non justifiées. Plusieurs cours peuvent être
    sélectionnés pour la même date, créant un enregistrement d'absence par
    cours sélectionné.

    Le queryset cours est peuplé dynamiquement dans __init__ pour inclure
    uniquement les cours de l'année académique actuellement active.

    Règles de validation appliquées dans clean() :
      - duree_absence est requise lorsque type_absence vaut PARTIEL.
      - heure_debut et heure_fin sont mutuellement requises (soit les deux
        présentes, soit les deux absentes).
      - heure_fin doit être strictement postérieure à heure_debut.
    """

    etudiant = forms.ModelChoiceField(
        queryset=User.objects.filter(role=User.Role.ETUDIANT, actif=True),
        label="Étudiant",
        required=True,
        widget=forms.Select(attrs={"class": "form-select"}),
        help_text="Sélectionnez l'étudiant concerné",
    )

    date_absence = forms.DateField(
        label="Date de l'absence",
        required=True,
        widget=forms.DateInput(attrs={"type": "date", "class": "form-control"}),
        help_text="Date à laquelle l'absence a eu lieu",
    )

    cours = forms.ModelMultipleChoiceField(
        queryset=Cours.objects.none(),
        label="Cours concernés",
        required=True,
        widget=forms.CheckboxSelectMultiple(attrs={"class": "form-check-input"}),
        help_text="Sélectionnez un ou plusieurs cours pour cette date",
    )

    heure_debut = forms.TimeField(
        label="Heure de début",
        required=False,
        widget=forms.TimeInput(attrs={"type": "time", "class": "form-control"}),
        help_text="Heure de début (optionnel, pour une absence partielle)",
    )

    heure_fin = forms.TimeField(
        label="Heure de fin",
        required=False,
        widget=forms.TimeInput(attrs={"type": "time", "class": "form-control"}),
        help_text="Heure de fin (optionnel, pour une absence partielle)",
    )

    type_absence = forms.ChoiceField(
        choices=[
            (Absence.TypeAbsence.ABSENT, "Absent"),
            (Absence.TypeAbsence.PARTIEL, "Absence partielle"),
        ],
        label="Type d'absence",
        initial=Absence.TypeAbsence.ABSENT,
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    duree_absence = forms.FloatField(
        label="Durée (heures)",
        required=False,
        min_value=0.01,
        widget=forms.NumberInput(
            attrs={"class": "form-control", "step": "0.5", "min": "0.01"}
        ),
        help_text="Durée en heures (requis si type = Absence partielle)",
    )

    commentaire = forms.CharField(
        label="Commentaire",
        required=False,
        max_length=2000,
        widget=forms.Textarea(attrs={"class": "form-control", "rows": 3, "maxlength": "2000"}),
        help_text="Commentaire interne (optionnel, max 2000 caractères)",
    )

    document = forms.FileField(
        label="Document justificatif",
        required=False,
        widget=forms.FileInput(
            attrs={"class": "form-control", "accept": ".pdf,.jpg,.jpeg,.png"}
        ),
        help_text="Optionnel (PDF, JPG, PNG — max 5 Mo). Si fourni, l'absence sera marquée comme justifiée.",
    )

    def __init__(self, *args, **kwargs):
        """
        Initialise le formulaire et peuple le queryset cours pour l'année académique active.

        Si aucune année académique n'est actuellement active, le champ cours est
        laissé vide afin que le formulaire puisse tout de même être rendu (avec
        une erreur explicative affichée par la vue).
        """
        super().__init__(*args, **kwargs)

        # Filtrer les cours à l'année académique active uniquement.
        annee_active = AnneeAcademique.objects.filter(active=True).first()
        if annee_active:
            cast(forms.ModelMultipleChoiceField, self.fields["cours"]).queryset = (
                Cours.objects.filter(id_annee=annee_active)
                .select_related("id_departement", "id_departement__id_faculte")
                .order_by("code_cours")
            )
        else:
            cast(forms.ModelMultipleChoiceField, self.fields["cours"]).queryset = Cours.objects.none()

    def clean(self):
        """
        Applique les règles de validation croisée des champs.

        Règles :
          - Une absence partielle (PARTIEL) doit comporter une durée explicite positive.
          - Si heure_debut est fournie, heure_fin est requise, et inversement.
          - heure_fin doit être strictement postérieure à heure_debut.

        Returns:
            dict: Le dictionnaire cleaned_data validé.

        Raises:
            forms.ValidationError: indexée par le nom du champ en erreur.
        """
        cleaned_data = super().clean()
        type_absence = cleaned_data.get("type_absence")
        duree_absence = cleaned_data.get("duree_absence")
        heure_debut = cleaned_data.get("heure_debut")
        heure_fin = cleaned_data.get("heure_fin")

        # Une absence partielle doit avoir une durée explicite (pas de valeur par défaut sur la séance complète).
        if type_absence == Absence.TypeAbsence.PARTIEL and (not duree_absence or duree_absence <= 0):
            raise forms.ValidationError(
                {"duree_absence": "La durée est requise pour une absence partielle."}
            )

        # Si heure_debut ou heure_fin est renseignée, les deux doivent l'être
        if heure_debut and not heure_fin:
            raise forms.ValidationError(
                {
                    "heure_fin": "L'heure de fin est requise si vous spécifiez une heure de début."
                }
            )
        if heure_fin and not heure_debut:
            raise forms.ValidationError(
                {
                    "heure_debut": "L'heure de début est requise si vous spécifiez une heure de fin."
                }
            )

        # Vérifier que heure_fin > heure_debut
        if heure_debut and heure_fin and heure_fin <= heure_debut:
            raise forms.ValidationError(
                {"heure_fin": "L'heure de fin doit être après l'heure de début."}
            )

        return cleaned_data
