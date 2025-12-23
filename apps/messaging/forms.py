from django import forms
from .models import Message
from apps.accounts.models import User

class MessageForm(forms.ModelForm):
    destinataire = forms.ModelChoiceField(
        queryset=User.objects.all(),
        widget=forms.Select(attrs={'class': 'form-select'}),
        label="Destinataire"
    )
    objet = forms.CharField(
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Sujet du message'}),
        label="Objet"
    )
    contenu = forms.CharField(
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 5, 'placeholder': 'Votre message...'}),
        label="Message"
    )

    class Meta:
        model = Message
        fields = ['destinataire', 'objet', 'contenu']

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super(MessageForm, self).__init__(*args, **kwargs)
        if user:
            # Exclude self from recipient list
            self.fields['destinataire'].queryset = User.objects.exclude(pk=user.pk)
            # Label improvement
            self.fields['destinataire'].label_from_instance = lambda obj: f"{obj.prenom} {obj.nom} ({obj.role})"
