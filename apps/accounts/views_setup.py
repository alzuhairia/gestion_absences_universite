"""
Vue de configuration initiale du système de comptes UniAbsences.

Ce module fournit une page de configuration unique accessible uniquement
lorsque la base de données ne contient aucun utilisateur ADMIN.  Elle rend un
formulaire qui collecte les identifiants du premier administrateur, les
valide avec les validateurs de mot de passe intégrés de Django, et crée le
compte administrateur dans une transaction de base de données.

Dès qu'au moins un compte ADMIN existe, la vue lève ``Http404``, rendant
l'URL de configuration définitivement inaccessible sans modification
manuelle de la base de données.

Vues
----
``initial_setup``
    GET  — rend le formulaire de création de compte.
    POST — valide le formulaire et crée le compte superadmin.
    Lève ``Http404`` si un ADMIN existe déjà (vérifié avant **et** à
    l'intérieur de la transaction pour se prémunir contre une condition de course).

``setup_complete``
    Page de confirmation GET uniquement affichée après la création du compte
    administrateur.  Lève ``Http404`` si aucun ADMIN n'existe (empêche l'accès
    direct à l'URL avant la fin de la configuration).

Fait partie du système de comptes UniAbsences.
"""

from django import forms
from django.contrib.auth.password_validation import validate_password
from django.db import transaction
from django.http import Http404
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from apps.audits.utils import log_action

from .models import User


def _admin_exists():
    """
    Retourne ``True`` si au moins un utilisateur de rôle ADMIN existe dans la base de données.

    Utilisé comme garde dans ``initial_setup`` et ``setup_complete`` pour
    déterminer si le flux de configuration doit être accessible.

    Retourne :
        bool : ``True`` si un compte ADMIN existe, ``False`` sinon.
    """
    return User.objects.filter(role=User.Role.ADMIN).exists()


class InitialAdminForm(forms.Form):
    """
    Formulaire de collecte des identifiants de l'administrateur initial.

    Champs
    ------
    prenom
        Prénom de l'administrateur.
    nom
        Nom de famille de l'administrateur.
    email
        Adresse email utilisée comme identifiant de connexion.  Doit être
        unique parmi tous les comptes utilisateurs existants.
    password
        Mot de passe en clair (minimum 8 caractères).  Validé contre le
        pipeline complet ``AUTH_PASSWORD_VALIDATORS`` de Django dans ``clean``.
    password_confirm
        Champ de confirmation — doit correspondre exactement à ``password``.

    Validation
    ----------
    - ``clean_email`` vérifie l'unicité dans la table ``User``.
    - ``clean`` vérifie que ``password == password_confirm`` puis appelle
      ``validate_password`` qui exécute tous les validateurs configurés.
    """

    prenom = forms.CharField(
        max_length=100,
        label="Prénom",
        widget=forms.TextInput(
            attrs={"class": "form-control", "placeholder": "Prénom", "autofocus": True}
        ),
    )
    nom = forms.CharField(
        max_length=100,
        label="Nom",
        widget=forms.TextInput(
            attrs={"class": "form-control", "placeholder": "Nom"}
        ),
    )
    email = forms.EmailField(
        max_length=255,
        label="Adresse email",
        widget=forms.EmailInput(
            attrs={"class": "form-control", "placeholder": "admin@example.com"}
        ),
    )
    password = forms.CharField(
        min_length=8,
        max_length=128,
        label="Mot de passe",
        widget=forms.PasswordInput(
            attrs={"class": "form-control", "placeholder": "Minimum 8 caractères"}
        ),
    )
    password_confirm = forms.CharField(
        min_length=8,
        max_length=128,
        label="Confirmer le mot de passe",
        widget=forms.PasswordInput(
            attrs={"class": "form-control", "placeholder": "Retapez le mot de passe"}
        ),
    )

    def clean_email(self):
        """
        Valide qu'aucun utilisateur existant ne possède déjà cette adresse email.

        Retourne :
            str : L'adresse email normalisée si elle est unique.

        Lève :
            forms.ValidationError : Si l'email est déjà enregistré.
        """
        email = self.cleaned_data["email"]
        if User.objects.filter(email=email).exists():
            raise forms.ValidationError("Un utilisateur avec cet email existe déjà.")
        return email

    def clean(self):
        """
        Validation inter-champs : confirme la correspondance des mots de passe et exécute les validateurs Django.

        Vérifie que ``password`` et ``password_confirm`` sont identiques, puis
        appelle ``validate_password`` afin que ``SystemSettingsPasswordValidator``
        et tout autre validateur configuré soit appliqué.

        Retourne :
            dict : Les données nettoyées du formulaire.

        Lève :
            forms.ValidationError : Si les mots de passe ne correspondent pas
                                    ou si un validateur rejette le mot de passe choisi.
        """
        cleaned_data = super().clean()
        password = cleaned_data.get("password")
        password_confirm = cleaned_data.get("password_confirm")
        # Confirmer que les deux champs de mot de passe concordent avant d'exécuter les validateurs.
        if password and password_confirm and password != password_confirm:
            raise forms.ValidationError("Les mots de passe ne correspondent pas.")
        if password:
            validate_password(password)
        return cleaned_data


@require_http_methods(["GET", "POST"])
def initial_setup(request):
    """
    Page de configuration unique de premier démarrage pour créer le compte administrateur initial.

    Cette vue n'est accessible que lorsqu'aucun utilisateur ADMIN n'existe
    dans la base de données.  Une fois le premier admin créé, l'URL renvoie
    définitivement 404.

    GET
        Rend le ``InitialAdminForm`` vierge.

    POST
        Valide le formulaire soumis.  En cas de succès :
        1. Revérifie l'existence d'un ADMIN dans une transaction
           ``select_for_update`` pour empêcher une condition de course où
           deux requêtes concurrentes passent toutes les deux la garde
           pré-transaction.
        2. Crée le superadmin via ``User.objects.create_superuser``.
        3. Journalise l'action via ``log_action`` au niveau de gravité CRITIQUE.
        4. Redirige vers ``setup_complete``.

    Paramètres :
        request : La requête HTTP entrante (GET ou POST).

    Retourne :
        HttpResponse : La page du formulaire de configuration, ou une
                       redirection vers ``setup_complete`` en cas de succès.

    Lève :
        Http404 : Si un compte ADMIN existe déjà au moment du contrôle.
    """
    if _admin_exists():
        raise Http404

    if request.method == "POST":
        form = InitialAdminForm(request.POST)
        if form.is_valid():
            with transaction.atomic():
                # Revérifier sous un verrou au niveau de la ligne pour éliminer la
                # course TOCTOU entre la garde ci-dessus et l'insertion réelle.
                if User.objects.select_for_update().filter(role=User.Role.ADMIN).exists():
                    raise Http404

                admin = User.objects.create_superuser(
                    email=form.cleaned_data["email"],
                    nom=form.cleaned_data["nom"],
                    prenom=form.cleaned_data["prenom"],
                    password=form.cleaned_data["password"],
                )
                # Journal d'audit à la plus haute gravité — la création initiale de
                # l'administrateur est un événement de sécurité critique.
                log_action(
                    admin,
                    f"CRITIQUE: Compte administrateur initial cree via setup ({admin.email})",
                    request,
                    niveau="CRITIQUE",
                    objet_type="USER",
                    objet_id=admin.id_utilisateur,
                )
            return redirect("setup_complete")
    else:
        form = InitialAdminForm()

    return render(request, "accounts/setup.html", {"form": form})


@require_http_methods(["GET"])
def setup_complete(request):
    """
    Page de succès affichée après la création du compte administrateur initial.

    Se prémunit contre l'accès direct à l'URL avant la fin de la configuration
    en levant ``Http404`` lorsqu'aucun ADMIN n'existe.

    Paramètres :
        request : La requête GET entrante.

    Retourne :
        HttpResponse : Le template ``accounts/setup_complete.html`` rendu.

    Lève :
        Http404 : Si aucun compte ADMIN n'existe (configuration pas encore terminée).
    """
    if not _admin_exists():
        raise Http404

    return render(request, "accounts/setup_complete.html")
