from django import forms
from apps.academics.models import Faculte, Departement, Cours
from apps.accounts.models import User
from apps.dashboard.models import SystemSettings
from apps.academic_sessions.models import AnneeAcademique


class FaculteForm(forms.ModelForm):
    class Meta:
        model = Faculte
        fields = ['nom_faculte', 'actif']
        widgets = {
            'nom_faculte': forms.TextInput(attrs={'class': 'form-control'}),
            'actif': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }
        labels = {
            'nom_faculte': 'Nom de la Faculté',
            'actif': 'Actif',
        }
        help_texts = {
            'actif': 'Désactiver une faculté la masque sans la supprimer',
        }


class DepartementForm(forms.ModelForm):
    class Meta:
        model = Departement
        fields = ['nom_departement', 'id_faculte', 'actif']
        widgets = {
            'nom_departement': forms.TextInput(attrs={'class': 'form-control'}),
            'id_faculte': forms.Select(attrs={'class': 'form-select'}),
            'actif': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }
        labels = {
            'nom_departement': 'Nom du Département',
            'id_faculte': 'Faculté de rattachement',
            'actif': 'Actif',
        }
        help_texts = {
            'actif': 'Désactiver un département le masque sans le supprimer',
        }


class CoursForm(forms.ModelForm):
    prerequisites = forms.ModelMultipleChoiceField(
        queryset=Cours.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple(attrs={'class': 'form-check-input'}),
        help_text="Cochez les cours qui sont des prérequis pour ce cours. Laissez vide si aucun prérequis n'est requis."
    )
    
    class Meta:
        model = Cours
        fields = [
            'code_cours', 'nom_cours', 'nombre_total_periodes',
            'seuil_absence', 'id_departement', 'professeur',
            'prerequisites', 'actif'
        ]
        widgets = {
            'code_cours': forms.TextInput(attrs={'class': 'form-control'}),
            'nom_cours': forms.TextInput(attrs={'class': 'form-control'}),
            'nombre_total_periodes': forms.NumberInput(attrs={'class': 'form-control'}),
            'seuil_absence': forms.NumberInput(attrs={'class': 'form-control'}),
            'id_departement': forms.Select(attrs={'class': 'form-select'}),
            'professeur': forms.Select(attrs={'class': 'form-select'}),
            'actif': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Filtrer les départements actifs
        self.fields['id_departement'].queryset = Departement.objects.filter(actif=True)
        # Filtrer les professeurs actifs
        self.fields['professeur'].queryset = User.objects.filter(
            role=User.Role.PROFESSEUR,
            actif=True
        )
        # Pour les prérequis, exclure le cours actuel et ne montrer que les cours actifs
        if self.instance and self.instance.pk:
            self.fields['prerequisites'].queryset = Cours.objects.filter(
                actif=True
            ).exclude(id_cours=self.instance.id_cours).order_by('code_cours')
            # Définir les prérequis initiaux uniquement lors de l'édition
            self.fields['prerequisites'].initial = self.instance.prerequisites.all()
        else:
            # Lors de la création, aucun prérequis n'est sélectionné par défaut
            self.fields['prerequisites'].queryset = Cours.objects.filter(actif=True).order_by('code_cours')
            self.fields['prerequisites'].initial = []  # Aucun prérequis par défaut
        
        # Labels en français
        self.fields['code_cours'].label = 'Code du Cours'
        self.fields['nom_cours'].label = 'Intitulé du Cours'
        self.fields['nombre_total_periodes'].label = 'Total Périodes (h)'
        self.fields['seuil_absence'].label = "Seuil d'Absence (%)"
        self.fields['id_departement'].label = 'Département'
        self.fields['professeur'].label = 'Professeur Responsable'
        self.fields['prerequisites'].label = 'Prérequis'
        self.fields['actif'].label = 'Actif'
        
        # Help texts en français
        self.fields['seuil_absence'].help_text = "Seuil personnalisé pour ce cours. Si vide, utilise le seuil par défaut du système."
        self.fields['actif'].help_text = 'Désactiver un cours le masque sans le supprimer'
    
    def save(self, commit=True):
        instance = super().save(commit=commit)
        if commit:
            instance.prerequisites.set(self.cleaned_data['prerequisites'])
        return instance


class UserForm(forms.ModelForm):
    password = forms.CharField(
        required=False,
        widget=forms.PasswordInput(attrs={'class': 'form-control'}),
        help_text="Laissez vide pour ne pas modifier le mot de passe"
    )
    password_confirm = forms.CharField(
        required=False,
        widget=forms.PasswordInput(attrs={'class': 'form-control'}),
        label='Confirmer le mot de passe',
        help_text=""
    )
    
    class Meta:
        model = User
        fields = ['nom', 'prenom', 'email', 'role', 'actif']
        widgets = {
            'nom': forms.TextInput(attrs={'class': 'form-control'}),
            'prenom': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'role': forms.Select(attrs={'class': 'form-select'}),
            'actif': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        is_creation = not (self.instance and self.instance.pk)
        
        if is_creation:
            # Lors de la création, le mot de passe est obligatoire
            self.fields['password'].required = True
            self.fields['password'].help_text = "Définissez un mot de passe temporaire pour l'utilisateur"
            self.fields['password_confirm'].required = True
            self.fields['password_confirm'].help_text = "Confirmez le mot de passe"
        else:
            # Lors de la modification, le mot de passe est optionnel
            self.fields['password'].required = False
            self.fields['password'].help_text = "Laissez vide pour ne pas modifier le mot de passe"
            self.fields['password_confirm'].required = False
            self.fields['password_confirm'].help_text = "Confirmez le nouveau mot de passe (si vous modifiez le mot de passe)"
        
        # Labels en français
        self.fields['nom'].label = 'Nom'
        self.fields['prenom'].label = 'Prénom'
        self.fields['email'].label = 'Adresse Email'
        self.fields['role'].label = 'Rôle'
        self.fields['actif'].label = 'Compte Actif'
        self.fields['password'].label = 'Mot de Passe'
    
    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get('password')
        password_confirm = cleaned_data.get('password_confirm')
        is_creation = not (self.instance and self.instance.pk)
        
        # Lors de la création, le mot de passe est obligatoire
        if is_creation:
            if not password:
                raise forms.ValidationError({
                    'password': 'Le mot de passe est obligatoire lors de la création d\'un utilisateur.'
                })
            if not password_confirm:
                raise forms.ValidationError({
                    'password_confirm': 'La confirmation du mot de passe est obligatoire.'
                })
        
        # Si un mot de passe est fourni, vérifier qu'il correspond à la confirmation
        if password:
            if password != password_confirm:
                raise forms.ValidationError({
                    'password_confirm': 'Les mots de passe ne correspondent pas.'
                })
            # Valider la longueur minimale
            if len(password) < 8:
                raise forms.ValidationError({
                    'password': 'Le mot de passe doit contenir au moins 8 caractères.'
                })
        
        return cleaned_data
    
    def save(self, commit=True):
        user = super().save(commit=False)
        password = self.cleaned_data.get('password')
        is_creation = not (self.instance and self.instance.pk)
        
        if password:
            user.set_password(password)
            # Lors de la création, forcer le changement de mot de passe à la première connexion
            if is_creation:
                user.must_change_password = True
        
        if commit:
            user.save()
        return user


class SystemSettingsForm(forms.ModelForm):
    class Meta:
        model = SystemSettings
        fields = [
            'default_absence_threshold', 'block_type',
            'password_min_length', 'password_require_uppercase',
            'password_require_lowercase', 'password_require_numbers',
            'password_require_special', 'mfa_enabled_globally',
            'data_retention_days'
        ]
        widgets = {
            'default_absence_threshold': forms.NumberInput(attrs={'class': 'form-control'}),
            'block_type': forms.Select(attrs={'class': 'form-select'}),
            'password_min_length': forms.NumberInput(attrs={'class': 'form-control'}),
            'password_require_uppercase': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'password_require_lowercase': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'password_require_numbers': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'password_require_special': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'mfa_enabled_globally': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'data_retention_days': forms.NumberInput(attrs={'class': 'form-control'}),
        }
        labels = {
            'default_absence_threshold': "Seuil d'Absence par Défaut (%)",
            'block_type': 'Type de Blocage',
            'password_min_length': 'Longueur Minimale du Mot de Passe',
            'password_require_uppercase': 'Exiger Majuscules',
            'password_require_lowercase': 'Exiger Minuscules',
            'password_require_numbers': 'Exiger Chiffres',
            'password_require_special': 'Exiger Caractères Spéciaux',
            'mfa_enabled_globally': 'Authentification à Deux Facteurs (Globale)',
            'data_retention_days': 'Rétention des Données (jours)',
        }
        help_texts = {
            'default_absence_threshold': 'Seuil par défaut appliqué aux nouveaux cours',
            'block_type': "Comportement lorsque le seuil est dépassé",
            'data_retention_days': 'Durée de conservation des données personnelles',
        }


class AnneeAcademiqueForm(forms.ModelForm):
    class Meta:
        model = AnneeAcademique
        fields = ['libelle', 'active']
        widgets = {
            'libelle': forms.TextInput(attrs={'class': 'form-control'}),
            'active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }
        labels = {
            'libelle': 'Libellé',
            'active': 'Définir comme Année Active',
        }
        help_texts = {
            'libelle': 'Format recommandé: AAAA-AAAA (ex: 2023-2024)',
            'active': "Une seule année peut être active à la fois. L'année précédente sera automatiquement désactivée.",
        }
    
    def clean_active(self):
        active = self.cleaned_data.get('active')
        if active:
            # Désactiver toutes les autres années
            AnneeAcademique.objects.exclude(
                pk=self.instance.pk if self.instance.pk else None
            ).update(active=False)
        return active

