from django import forms
from apps.enrollments.models import Inscription
from apps.academics.models import Cours
from apps.academic_sessions.models import AnneeAcademique, Seance
from apps.accounts.models import User


class SecretaryJustifiedAbsenceForm(forms.Form):
    """
    Formulaire pour que le secrétariat encode une absence justifiée.
    """
    etudiant = forms.ModelChoiceField(
        queryset=User.objects.filter(role=User.Role.ETUDIANT),
        label="Étudiant",
        required=True,
        help_text="Sélectionnez l'étudiant concerné"
    )
    
    date_absence = forms.DateField(
        label="Date de l'absence",
        required=True,
        widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
        help_text="Date à laquelle l'absence a eu lieu"
    )
    
    cours = forms.ModelMultipleChoiceField(
        queryset=Cours.objects.none(),
        label="Cours concernés",
        required=True,
        widget=forms.CheckboxSelectMultiple(attrs={'class': 'form-check-input'}),
        help_text="Sélectionnez un ou plusieurs cours pour cette date"
    )
    
    heure_debut = forms.TimeField(
        label="Heure de début",
        required=False,
        widget=forms.TimeInput(attrs={'type': 'time', 'class': 'form-control'}),
        help_text="Heure de début (optionnel, pour une absence partielle)"
    )
    
    heure_fin = forms.TimeField(
        label="Heure de fin",
        required=False,
        widget=forms.TimeInput(attrs={'type': 'time', 'class': 'form-control'}),
        help_text="Heure de fin (optionnel, pour une absence partielle)"
    )
    
    type_absence = forms.ChoiceField(
        choices=[
            ('SEANCE', 'Séance complète'),
            ('HEURE', 'Retard / Partiel'),
            ('JOURNEE', 'Journée complète'),
        ],
        label="Type d'absence",
        initial='SEANCE',
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    
    duree_absence = forms.FloatField(
        label="Durée (heures)",
        required=False,
        min_value=0,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'step': '0.5', 'min': '0'}),
        help_text="Durée en heures (requis si type = Retard/Partiel)"
    )
    
    commentaire = forms.CharField(
        label="Commentaire",
        required=False,
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        help_text="Commentaire interne (optionnel)"
    )
    
    document = forms.FileField(
        label="Document justificatif",
        required=False,
        widget=forms.FileInput(attrs={'class': 'form-control', 'accept': '.pdf,.jpg,.jpeg,.png'}),
        help_text="Document justificatif (PDF, image) - optionnel"
    )
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Filtrer les cours par année académique active
        annee_active = AnneeAcademique.objects.filter(active=True).first()
        if annee_active:
            self.fields['cours'].queryset = Cours.objects.filter(
                id_annee=annee_active
            ).select_related('id_departement', 'id_departement__id_faculte').order_by('code_cours')
        else:
            self.fields['cours'].queryset = Cours.objects.none()
    
    def clean(self):
        cleaned_data = super().clean()
        type_absence = cleaned_data.get('type_absence')
        duree_absence = cleaned_data.get('duree_absence')
        heure_debut = cleaned_data.get('heure_debut')
        heure_fin = cleaned_data.get('heure_fin')
        
        # Si type = HEURE, la durée est requise
        if type_absence == 'HEURE' and (not duree_absence or duree_absence <= 0):
            raise forms.ValidationError({
                'duree_absence': 'La durée est requise pour une absence partielle.'
            })
        
        # Si heure_debut ou heure_fin est renseigné, les deux doivent l'être
        if (heure_debut and not heure_fin) or (heure_fin and not heure_debut):
            raise forms.ValidationError({
                'heure_fin': 'Si vous renseignez une heure, veuillez renseigner l\'heure de début ET l\'heure de fin.'
            })
        
        return cleaned_data

