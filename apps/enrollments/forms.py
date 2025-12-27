"""
Formulaires pour la gestion des inscriptions.
"""
from django import forms
from django.core.exceptions import ValidationError
from apps.accounts.models import User
from apps.academics.models import Cours
from apps.academic_sessions.models import AnneeAcademique
from .models import Inscription


class StudentCreationForm(forms.Form):
    """Formulaire pour créer un étudiant lors de l'inscription"""
    nom = forms.CharField(
        max_length=100,
        label="Nom",
        widget=forms.TextInput(attrs={'class': 'form-control'})
    )
    prenom = forms.CharField(
        max_length=100,
        label="Prénom",
        widget=forms.TextInput(attrs={'class': 'form-control'})
    )
    email = forms.EmailField(
        label="Adresse e-mail",
        widget=forms.EmailInput(attrs={'class': 'form-control'})
    )
    niveau = forms.ChoiceField(
        choices=[(1, 'Année 1'), (2, 'Année 2'), (3, 'Année 3')],
        label="Niveau académique",
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'}),
        help_text="Niveau académique de l'étudiant (peut être défini lors de l'inscription)"
    )
    password = forms.CharField(
        label="Mot de passe temporaire",
        widget=forms.PasswordInput(attrs={'class': 'form-control'}),
        min_length=8,
        help_text="L'étudiant devra changer ce mot de passe lors de sa première connexion."
    )
    password_confirm = forms.CharField(
        label="Confirmation du mot de passe",
        widget=forms.PasswordInput(attrs={'class': 'form-control'})
    )
    
    def clean_email(self):
        email = self.cleaned_data.get('email')
        if User.objects.filter(email=email).exists():
            raise ValidationError("Un utilisateur avec cet e-mail existe déjà.")
        return email
    
    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get('password')
        password_confirm = cleaned_data.get('password_confirm')
        
        if password and password_confirm and password != password_confirm:
            raise ValidationError({
                'password_confirm': 'Les mots de passe ne correspondent pas.'
            })
        
        return cleaned_data
    
    def create_student(self):
        """Crée un compte étudiant avec le mot de passe temporaire"""
        student = User.objects.create_user(
            email=self.cleaned_data['email'],
            password=self.cleaned_data['password'],
            nom=self.cleaned_data['nom'],
            prenom=self.cleaned_data['prenom'],
            role=User.Role.ETUDIANT,
            actif=True,
            must_change_password=True,  # Forcer le changement de mot de passe
            niveau=int(self.cleaned_data.get('niveau')) if self.cleaned_data.get('niveau') else None  # Niveau académique si fourni
        )
        return student


class EnrollmentForm(forms.Form):
    """Formulaire pour l'inscription d'un étudiant"""
    ENROLLMENT_TYPE_CHOICES = [
        ('LEVEL', 'Inscription à un niveau complet (Année 1, 2 ou 3)'),
        ('COURSE', 'Inscription à un cours spécifique'),
    ]
    
    enrollment_type = forms.ChoiceField(
        choices=ENROLLMENT_TYPE_CHOICES,
        label="Type d'inscription",
        widget=forms.RadioSelect(attrs={'class': 'form-check-input'}),
        initial='COURSE'
    )
    
    # Niveau pour l'inscription à un niveau complet
    niveau = forms.ChoiceField(
        choices=[(1, 'Année 1'), (2, 'Année 2'), (3, 'Année 3')],
        label="Niveau d'étude",
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'}),
        help_text="Sélectionnez le niveau pour l'inscription à un niveau complet"
    )
    
    # Champs pour l'étudiant existant
    student_email = forms.EmailField(
        label="E-mail de l'étudiant (si compte existant)",
        required=False,
        widget=forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'email@example.com'})
    )
    
    # Champs pour créer un nouvel étudiant
    create_new_student = forms.BooleanField(
        label="Créer un nouveau compte étudiant",
        required=False,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'})
    )
    
    # Année académique
    academic_year = forms.ModelChoiceField(
        queryset=AnneeAcademique.objects.all().order_by('-libelle'),
        label="Année Académique",
        widget=forms.Select(attrs={'class': 'form-select'}),
        empty_label="Sélectionner une année académique"
    )
    
    # Cours spécifique (si inscription à un cours)
    course = forms.ModelChoiceField(
        queryset=Cours.objects.none(),  # Sera rempli dynamiquement selon l'année
        label="Cours",
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'}),
        empty_label="Sélectionner un cours"
    )
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Filtrer les cours actifs
        self.fields['course'].queryset = Cours.objects.filter(actif=True).select_related('id_annee', 'id_departement').order_by('id_annee__libelle', 'code_cours')
    
    def clean(self):
        cleaned_data = super().clean()
        enrollment_type = cleaned_data.get('enrollment_type')
        student_email = cleaned_data.get('student_email')
        create_new_student = cleaned_data.get('create_new_student')
        course = cleaned_data.get('course')
        niveau = cleaned_data.get('niveau')
        
        # Validation selon le type d'inscription
        if enrollment_type == 'LEVEL':
            if not niveau:
                raise ValidationError({
                    'niveau': 'Vous devez sélectionner un niveau pour une inscription à un niveau complet.'
                })
        elif enrollment_type == 'COURSE':
            if not course:
                raise ValidationError({
                    'course': 'Vous devez sélectionner un cours pour une inscription à un cours spécifique.'
                })
        
        # Validation de l'étudiant
        if not create_new_student and not student_email:
            raise ValidationError({
                'student_email': 'Vous devez soit sélectionner un étudiant existant, soit créer un nouveau compte.'
            })
        
        if create_new_student and student_email:
            raise ValidationError({
                'create_new_student': 'Vous ne pouvez pas créer un nouveau compte et utiliser un e-mail existant en même temps.'
            })
        
        return cleaned_data

