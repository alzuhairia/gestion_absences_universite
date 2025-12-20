# apps/accounts/admin.py - VERSION CORRIGÉE
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils.translation import gettext_lazy as _
from django import forms
from .models import User

class UserCreationForm(forms.ModelForm):
    """Formulaire de création d'utilisateur sans champs password1/password2"""
    password = forms.CharField(label='Mot de passe', widget=forms.PasswordInput)
    
    class Meta:
        model = User
        fields = ('email', 'nom', 'prenom', 'role', 'actif')
    
    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data["password"])
        if commit:
            user.save()
        return user

@admin.register(User)
class UserAdmin(BaseUserAdmin):
    """Admin adapté pour notre modèle avec champs virtuels"""
    
    add_form = UserCreationForm
    form = UserCreationForm
    
    # Champs à afficher
    list_display = ('email', 'nom', 'prenom', 'role', 'actif', 'date_creation')
    list_filter = ('role', 'actif', 'date_creation')
    search_fields = ('email', 'nom', 'prenom')
    ordering = ('nom', 'prenom')
    
    # Configuration des formulaires (simplifiée)
    fieldsets = (
        (None, {'fields': ('email', 'password')}),
        (_('Informations personnelles'), {'fields': ('nom', 'prenom')}),
        (_('Rôle et statut'), {'fields': ('role', 'actif')}),
        (_('Permissions'), {
            'fields': ('groups', 'user_permissions'),
        }),
        (_('Dates importantes'), {'fields': ('date_creation',)}),
    )
    
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('email', 'nom', 'prenom', 'password', 'role', 'actif'),
        }),
    )
    
    readonly_fields = ('date_creation',)
    
    def get_form(self, request, obj=None, **kwargs):
        """Adapte le formulaire selon si on crée ou modifie"""
        defaults = {}
        if obj is None:
            defaults['form'] = self.add_form
        defaults.update(kwargs)
        return super().get_form(request, obj, **defaults)