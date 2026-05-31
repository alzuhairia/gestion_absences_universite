"""
Formulaire de gestion des utilisateurs pour le tableau de bord d'administration UniAbsences.

``UserForm``
    ModelForm pour la création et l'édition de comptes utilisateurs
    depuis le tableau de bord d'administration.  Applique les
    validateurs de mot de passe configurés de Django à la création et
    impose l'exigence du ``niveau`` pour les comptes étudiants.

Fait partie du système de tableau de bord UniAbsences.
"""

from typing import Any, cast

from django import forms
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError

from apps.accounts.models import User


class UserForm(forms.ModelForm):
    """
    ModelForm pour la création et l'édition de comptes ``User`` depuis le tableau de bord d'administration.

    Différences entre les modes **create** et **edit** :

    - **Create** (pas de PK d'instance) : ``password`` et
      ``password_confirm`` sont requis.  ``save()`` hache le mot de
      passe et définit ``must_change_password = True`` afin que
      l'utilisateur soit forcé de choisir son propre mot de passe à
      la première connexion.
    - **Edit** (l'instance a une PK) : les deux champs de mot de passe
      sont optionnels.  Si l'un est fourni, les deux doivent
      correspondre et le nouveau mot de passe est validé contre les
      validateurs de mot de passe configurés de Django.

    Le formulaire valide également que l'adresse email soumise est
    unique, en excluant le propre enregistrement de l'utilisateur
    courant durant les opérations d'édition.
    """

    password = forms.CharField(
        required=False,
        max_length=128,
        widget=forms.PasswordInput(attrs={"class": "form-control"}),
        help_text="Laissez vide pour ne pas modifier le mot de passe",
    )
    password_confirm = forms.CharField(
        required=False,
        max_length=128,
        widget=forms.PasswordInput(attrs={"class": "form-control"}),
        label="Confirmer le mot de passe",
        help_text="",
    )

    class Meta:
        """Configuration ModelForm : modèle ``User`` et champs métier exposés (hors mot de passe)."""

        model = User
        fields = ["nom", "prenom", "email", "role", "actif"]
        widgets = {
            "nom": forms.TextInput(attrs={"class": "form-control"}),
            "prenom": forms.TextInput(attrs={"class": "form-control"}),
            "email": forms.EmailInput(attrs={"class": "form-control"}),
            "role": forms.Select(attrs={"class": "form-select"}),
            "actif": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def __init__(self, *args, **kwargs):
        """
        Configure les exigences des champs de mot de passe selon le mode (create ou edit).

        En mode création, ``password`` et ``password_confirm`` sont
        rendus obligatoires et dotés de textes d'aide informatifs.
        En mode édition ils sont optionnels avec une indication
        « laissez vide pour conserver le mot de passe actuel ».

        Parameters
        ----------
        *args, **kwargs
            Transmis à ``ModelForm.__init__``.
        """
        super().__init__(*args, **kwargs)
        is_creation = not (self.instance and self.instance.pk)

        if is_creation:
            self.fields["password"].required = True
            self.fields["password"].help_text = (
                "Définissez un mot de passe temporaire pour l'utilisateur"
            )
            self.fields["password_confirm"].required = True
            self.fields["password_confirm"].help_text = "Confirmez le mot de passe"
        else:
            self.fields["password"].required = False
            self.fields["password"].help_text = (
                "Laissez vide pour ne pas modifier le mot de passe"
            )
            self.fields["password_confirm"].required = False
            self.fields["password_confirm"].help_text = (
                "Confirmez le nouveau mot de passe (si vous modifiez le mot de passe)"
            )

        self.fields["nom"].label = "Nom"
        self.fields["prenom"].label = "Prénom"
        self.fields["email"].label = "Adresse Email"
        self.fields["role"].label = "Rôle"
        self.fields["actif"].label = "Compte Actif"
        self.fields["password"].label = "Mot de Passe"

    def clean_email(self):
        """
        Valide que l'adresse email soumise n'est pas déjà utilisée.

        Durant les opérations d'édition, le propre enregistrement de
        l'utilisateur courant est exclu du contrôle d'unicité afin
        qu'un admin puisse sauvegarder sans changer l'email.

        Returns
        -------
        str
            L'adresse email validée et en minuscules.

        Raises
        ------
        forms.ValidationError
            Si un autre compte utilisateur possède déjà cette adresse email.
        """
        email = self.cleaned_data.get("email")
        if email:
            qs = User.objects.filter(email=email)
            # Exclut le propre enregistrement de l'utilisateur courant durant les opérations d'édition.
            if self.instance and self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise forms.ValidationError(
                    "Un utilisateur avec cette adresse email existe déjà."
                )
        return email

    def clean(self):
        """
        Validation inter-champs pour la concordance et la robustesse des mots de passe.

        Garantit qu'en mode création les deux champs de mot de passe
        sont présents et identiques.  Lorsqu'un mot de passe est
        fourni (création ou édition), exécute les
        ``AUTH_PASSWORD_VALIDATORS`` configurés de Django contre un
        objet ``User`` temporaire afin que les validateurs aient accès
        au contexte des attributs utilisateur (par ex. similarité au
        nom/email).

        Returns
        -------
        dict
            Les données du formulaire validées.

        Raises
        ------
        forms.ValidationError
            Si les mots de passe sont absents en mode création, ne
            correspondent pas, ou échouent aux validateurs de
            robustesse configurés.
        """
        cleaned_data = super().clean()
        password = cleaned_data.get("password")
        password_confirm = cleaned_data.get("password_confirm")
        is_creation = not (self.instance and self.instance.pk)

        if is_creation:
            if not password:
                raise forms.ValidationError(
                    {
                        "password": "Le mot de passe est obligatoire lors de la création d'un utilisateur."
                    }
                )
            if not password_confirm:
                raise forms.ValidationError(
                    {
                        "password_confirm": "La confirmation du mot de passe est obligatoire."
                    }
                )

        if password:
            if password != password_confirm:
                raise forms.ValidationError(
                    {"password_confirm": "Les mots de passe ne correspondent pas."}
                )
            validation_user = (
                self.instance
                if self.instance and self.instance.pk
                else User(
                    email=cleaned_data.get("email", ""),
                    nom=cleaned_data.get("nom", ""),
                    prenom=cleaned_data.get("prenom", ""),
                    role=cleaned_data.get("role") or User.Role.ETUDIANT,
                )
            )
            try:
                validate_password(password, user=validation_user)
            except DjangoValidationError as exc:
                raise forms.ValidationError(
                    {"password": cast(Any, exc.messages)}
                )

        return cleaned_data

    def save(self, commit=True):
        """
        Sauvegarde le compte utilisateur en hachant le mot de passe lorsqu'il est fourni.

        Pour les nouveaux comptes, définit ``must_change_password =
        True`` afin que l'utilisateur soit invité à choisir son propre
        mot de passe à la première connexion.

        Parameters
        ----------
        commit : bool, optional
            Lorsque ``False``, retourne l'instance non sauvegardée.
            Par défaut ``True``.

        Returns
        -------
        User
            L'instance utilisateur sauvegardée (ou préparée).
        """
        user = super().save(commit=False)
        password = self.cleaned_data.get("password")
        is_creation = not (self.instance and self.instance.pk)

        if password:
            # Hache le mot de passe en clair ; ne le stocke jamais en clair.
            user.set_password(password)
            if is_creation:
                # Force les nouveaux utilisateurs à définir leur propre mot de passe à la première connexion.
                user.must_change_password = True

        if commit:
            user.save()
        return user
