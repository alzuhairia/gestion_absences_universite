"""
FICHIER : apps/messaging/forms.py
RESPONSABILITE : Formulaire de composition de message
FONCTIONNALITES PRINCIPALES :
  - MessageForm : filtrage destinataires par role
DEPENDANCES CLES : apps.accounts.models, apps.messaging.models
"""

from django import forms
from django.core.exceptions import ValidationError

from apps.accounts.models import User

from .models import Message


class MessageForm(forms.ModelForm):
    """Formulaire de composition d'un message interne avec filtrage des destinataires par rôle."""

    destinataire = forms.ModelChoiceField(
        queryset=User.objects.filter(actif=True),
        widget=forms.Select(attrs={"class": "form-select"}),
        label="Destinataire",
    )
    objet = forms.CharField(
        max_length=200,
        widget=forms.TextInput(
            attrs={"class": "form-control", "placeholder": "Sujet du message"}
        ),
        label="Objet",
    )
    contenu = forms.CharField(
        max_length=10000,
        widget=forms.Textarea(
            attrs={
                "class": "form-control",
                "rows": 5,
                "placeholder": "Votre message...",
                "maxlength": "10000",
            }
        ),
        label="Message",
    )

    class Meta:
        """Configuration ModelForm : modèle ``Message`` et trois champs métier exposés."""

        model = Message
        fields = ["destinataire", "objet", "contenu"]

    def __init__(self, *args, **kwargs):
        """Restreint la liste des destinataires en fonction du rôle de l'expéditeur."""
        user = kwargs.pop("user", None)
        super(MessageForm, self).__init__(*args, **kwargs)
        if user:
            # Filtrage des destinataires basé sur le rôle
            qs = User.objects.filter(actif=True).exclude(pk=user.pk)
            if user.role == User.Role.ETUDIANT:
                # Les étudiants ne peuvent écrire qu'aux professeurs et secrétaires
                qs = qs.filter(role__in=[User.Role.PROFESSEUR, User.Role.SECRETAIRE])
            # ADMIN, SECRETAIRE, PROFESSEUR peuvent écrire à tout utilisateur actif
            self.fields["destinataire"].queryset = qs
            # Amélioration du label
            self.fields["destinataire"].label_from_instance = (
                lambda obj: f"{obj.prenom} {obj.nom} ({obj.role})"
            )

    def clean_destinataire(self):
        """Refuse un destinataire désactivé (cas de race condition entre affichage et soumission)."""
        dest = self.cleaned_data.get("destinataire")
        if dest and not dest.actif:
            raise ValidationError("Ce destinataire n'est plus actif.")
        return dest
