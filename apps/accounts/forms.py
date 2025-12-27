# apps/accounts/forms.py
from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm, PasswordChangeForm
from .models import User

class CustomAuthenticationForm(AuthenticationForm):
    username = forms.CharField(
        label="Nom d'utilisateur ou Email",
        widget=forms.TextInput(attrs={'class': 'form-control'})
    )
    password = forms.CharField(
        label="Mot de passe",
        widget=forms.PasswordInput(attrs={'class': 'form-control'})
    )

class CustomUserCreationForm(UserCreationForm):
    class Meta:
        model = User
        fields = ('email', 'nom', 'prenom', 'role')

class CustomPasswordChangeForm(PasswordChangeForm):
    """Formulaire personnalisé pour le changement de mot de passe avec labels en français"""
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Personnaliser les labels en français
        self.fields['old_password'].label = 'Ancien mot de passe'
        self.fields['old_password'].help_text = 'Entrez votre mot de passe actuel'
        self.fields['old_password'].widget.attrs.update({
            'class': 'form-control form-control-lg',
            'placeholder': '••••••••',
            'autocomplete': 'current-password'
        })
        
        self.fields['new_password1'].label = 'Nouveau mot de passe'
        self.fields['new_password1'].help_text = 'Votre nouveau mot de passe doit contenir au moins 8 caractères'
        self.fields['new_password1'].widget.attrs.update({
            'class': 'form-control form-control-lg',
            'placeholder': '••••••••',
            'autocomplete': 'new-password'
        })
        
        self.fields['new_password2'].label = 'Confirmer le nouveau mot de passe'
        self.fields['new_password2'].help_text = 'Entrez à nouveau le nouveau mot de passe pour confirmation'
        self.fields['new_password2'].widget.attrs.update({
            'class': 'form-control form-control-lg',
            'placeholder': '••••••••',
            'autocomplete': 'new-password'
        })
    
    def clean_new_password2(self):
        """Personnaliser les messages d'erreur en français"""
        password1 = self.cleaned_data.get('new_password1')
        password2 = self.cleaned_data.get('new_password2')
        
        if password1 and password2:
            if password1 != password2:
                raise forms.ValidationError("Les deux mots de passe ne correspondent pas.")
        
        return password2