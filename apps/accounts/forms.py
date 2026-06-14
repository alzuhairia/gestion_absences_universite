"""
Formulaires d'authentification et de mot de passe pour le système accounts de UniAbsences.

Ce module étend les formulaires d'authentification intégrés de Django pour
appliquer le style spécifique au projet (classes CSS Bootstrap) et les
validateurs de mot de passe personnalisés issus de ``SystemSettings``.

Formulaires
-----------
``CustomAuthenticationForm``
    Formulaire de connexion — ajoute la classe CSS Bootstrap ``form-control``
    aux champs email et mot de passe.

``CustomUserCreationForm``
    Formulaire de création d'utilisateur utilisé dans l'admin et le flux de
    setup ; restreint les champs visibles à ceux pertinents pour le modèle
    universitaire (email, nom, prenom, role).

``CustomPasswordResetForm``
    Formulaire de demande de réinitialisation de mot de passe stylé avec les
    classes Bootstrap. Surcharge ``get_users`` pour filtrer sur le champ
    ``actif`` personnalisé plutôt que sur ``is_active`` par défaut de Django.

``CustomSetPasswordForm``
    Formulaire « Définir un nouveau mot de passe » affiché après un clic sur
    un lien de réinitialisation valide ; applique le style Bootstrap aux deux
    champs de mot de passe.

``CustomPasswordChangeForm``
    Formulaire de changement de mot de passe authentifié avec style Bootstrap.
    Ajoute une règle de validation inter-champs supplémentaire : le nouveau
    mot de passe doit être différent de l'ancien.

Fait partie du système accounts de UniAbsences.
"""

from django import forms
from django.contrib.auth.forms import (
    AuthenticationForm,
    PasswordChangeForm,
    PasswordResetForm,
    SetPasswordForm,
    UserCreationForm,
)

from .models import User


class CustomAuthenticationForm(AuthenticationForm):
    """
    Formulaire de connexion avec style Bootstrap.

    Remplace le label par défaut du champ ``username`` par un indice
    bilingue et applique la classe CSS ``form-control`` aux champs
    identifiant et mot de passe afin qu'ils s'intègrent au template de
    connexion Bootstrap 5.
    """

    username = forms.CharField(
        label="Nom d'utilisateur ou Email",
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )
    password = forms.CharField(
        label="Mot de passe",
        max_length=128,
        widget=forms.PasswordInput(attrs={"class": "form-control"}),
    )


class CustomUserCreationForm(UserCreationForm):
    """
    Formulaire minimal de création d'utilisateur pour l'admin Django et le wizard de setup.

    Hérite de la logique de hachage et de confirmation de mot de passe de
    ``UserCreationForm`` tout en restreignant les champs visibles aux quatre
    attributs nécessaires au modèle utilisateur universitaire.
    """

    class Meta:
        """Configuration ModelForm : modèle ``User`` et quatre champs visibles à la création."""

        model = User
        fields = ("email", "nom", "prenom", "role")


class CustomPasswordResetForm(PasswordResetForm):
    """
    Formulaire de demande de réinitialisation de mot de passe avec style Bootstrap et recherche utilisateur personnalisée.

    Surcharge ``get_users`` car le modèle ``User`` personnalisé stocke
    l'indicateur actif/inactif dans la colonne ``actif`` plutôt que dans le
    champ ``is_active`` par défaut de Django. Le champ email est également
    restylé avec des classes Bootstrap et un placeholder pour une meilleure UX.
    """

    email = forms.EmailField(
        label="Adresse email",
        max_length=254,
        widget=forms.EmailInput(
            attrs={
                "class": "form-control form-control-lg",
                "placeholder": "exemple@universite.edu",
                "autocomplete": "email",
            }
        ),
    )

    def get_users(self, email):
        """
        Retourne les utilisateurs actifs correspondant à ``email`` pour le flux de réinitialisation de mot de passe.

        Interroge le champ ``actif`` (équivalent dans le projet de l'``is_active``
        de Django) et filtre les comptes dont le mot de passe est inutilisable
        afin que les liens de réinitialisation ne soient envoyés qu'aux comptes
        qui peuvent réellement se connecter.

        Paramètres :
            email (str): L'adresse email soumise par l'utilisateur.

        Retourne :
            generator: Un générateur d'instances ``User`` qui sont actives et
                       possèdent un mot de passe utilisable.
        """
        # Filtre sur 'actif' (champ du projet) au lieu de 'is_active' par défaut.
        active_users = User.objects.filter(
            email__iexact=email,
            actif=True,
        )
        return (
            u
            for u in active_users
            if u.has_usable_password()
        )


class CustomSetPasswordForm(SetPasswordForm):
    """
    Formulaire « Définir un nouveau mot de passe » affiché après un clic sur un lien de réinitialisation valide.

    Applique le style Bootstrap ``form-control form-control-lg`` et des
    labels/placeholders en français aux deux champs de mot de passe. La
    validation de complexité du mot de passe est déléguée au pipeline
    ``AUTH_PASSWORD_VALIDATORS`` de Django (qui inclut
    ``SystemSettingsPasswordValidator``).
    """

    def __init__(self, *args, **kwargs):
        """
        Initialise le formulaire et applique le style Bootstrap aux deux champs de mot de passe.

        Paramètres :
            *args : arguments positionnels transmis à ``SetPasswordForm.__init__``.
            **kwargs : arguments nommés transmis à ``SetPasswordForm.__init__``.
        """
        super().__init__(*args, **kwargs)
        # Style du champ nouveau mot de passe.
        self.fields["new_password1"].label = "Nouveau mot de passe"
        self.fields["new_password1"].help_text = (
            "Votre nouveau mot de passe doit contenir au moins 8 caractères"
        )
        self.fields["new_password1"].widget.attrs.update(
            {
                "class": "form-control form-control-lg",
                "placeholder": "••••••••",
                "autocomplete": "new-password",
            }
        )
        # Style du champ de confirmation.
        self.fields["new_password2"].label = "Confirmer le nouveau mot de passe"
        self.fields["new_password2"].help_text = (
            "Entrez à nouveau le nouveau mot de passe pour confirmation"
        )
        self.fields["new_password2"].widget.attrs.update(
            {
                "class": "form-control form-control-lg",
                "placeholder": "••••••••",
                "autocomplete": "new-password",
            }
        )


class CustomPasswordChangeForm(PasswordChangeForm):
    """
    Formulaire de changement de mot de passe authentifié avec style Bootstrap
    et une règle inter-champs supplémentaire : le nouveau mot de passe doit
    être différent de l'ancien.

    Utilisé par ``CustomPasswordChangeView`` qui efface aussi le drapeau
    ``must_change_password`` lors d'une soumission réussie.
    """

    def __init__(self, *args, **kwargs):
        """
        Initialise le formulaire et applique le style Bootstrap aux trois champs de mot de passe.

        Paramètres :
            *args : arguments positionnels transmis à ``PasswordChangeForm.__init__``.
            **kwargs : arguments nommés transmis à ``PasswordChangeForm.__init__``.
        """
        super().__init__(*args, **kwargs)
        # Style du champ mot de passe actuel.
        self.fields["old_password"].label = "Ancien mot de passe"
        self.fields["old_password"].help_text = "Entrez votre mot de passe actuel"
        self.fields["old_password"].widget.attrs.update(
            {
                "class": "form-control form-control-lg",
                "placeholder": "••••••••",
                "autocomplete": "current-password",
            }
        )
        # Style du champ nouveau mot de passe.
        self.fields["new_password1"].label = "Nouveau mot de passe"
        self.fields["new_password1"].help_text = (
            "Votre nouveau mot de passe doit contenir au moins 8 caractères"
        )
        self.fields["new_password1"].widget.attrs.update(
            {
                "class": "form-control form-control-lg",
                "placeholder": "••••••••",
                "autocomplete": "new-password",
            }
        )
        # Style du champ de confirmation.
        self.fields["new_password2"].label = "Confirmer le nouveau mot de passe"
        self.fields["new_password2"].help_text = (
            "Entrez à nouveau le nouveau mot de passe pour confirmation"
        )
        self.fields["new_password2"].widget.attrs.update(
            {
                "class": "form-control form-control-lg",
                "placeholder": "••••••••",
                "autocomplete": "new-password",
            }
        )

    def clean_new_password1(self):
        """
        Valide que le nouveau mot de passe diffère du mot de passe actuel.

        Appelée automatiquement par le pipeline de validation de formulaires
        de Django après l'exécution des validateurs de champ individuels.

        Retour :
            str : le nouveau mot de passe validé s'il diffère de l'ancien.

        Lève :
            forms.ValidationError : si le nouveau mot de passe est identique
                                    au mot de passe actuel.
        """
        old_password = self.cleaned_data.get("old_password")
        new_password1 = self.cleaned_data.get("new_password1")
        # Rejette si les deux champs sont présents et identiques — le même mot
        # de passe n'est pas un vrai changement et dégrade l'hygiène de sécurité.
        if old_password and new_password1 and old_password == new_password1:
            raise forms.ValidationError(
                "Le nouveau mot de passe doit être différent de l'ancien."
            )
        return new_password1
