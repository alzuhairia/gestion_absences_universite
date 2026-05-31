"""
Formulaires d'inscription des étudiants dans le système UniAbsences.

Deux formulaires sont définis :

- ``StudentCreationForm`` — crée un nouveau compte utilisateur étudiant avec
  un mot de passe temporaire. L'étudiant sera invité à changer le mot de
  passe à la première connexion (``must_change_password=True``).

- ``EnrollmentForm`` — pilote le workflow d'inscription. Supporte deux modes :
    - LEVEL  : inscrire à tous les cours actifs d'un niveau/département/année donné.
    - COURSE : inscrire à un ou plusieurs cours sélectionnés individuellement.

Appartient à : UniAbsences — application enrollments.
"""

from typing import Any, cast

from django import forms
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError

from apps.academic_sessions.models import AnneeAcademique
from apps.academics.models import Cours, Departement
from apps.accounts.models import User


class StudentCreationForm(forms.Form):
    """
    Formulaire de création d'un compte utilisateur étudiant durant le workflow d'inscription.

    Valide que l'adresse e-mail n'est pas déjà utilisée, que les deux champs
    mot de passe correspondent, et que le mot de passe choisi passe les
    validateurs de mot de passe configurés par Django (évalués contre une
    instance ``User`` provisoire afin que les vérifications de similarité
    des attributs utilisateur fonctionnent correctement).
    """

    nom = forms.CharField(
        max_length=100,
        label="Nom",
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )
    prenom = forms.CharField(
        max_length=100,
        label="Prénom",
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )
    email = forms.EmailField(
        label="Adresse e-mail", widget=forms.EmailInput(attrs={"class": "form-control"})
    )
    password = forms.CharField(
        label="Mot de passe temporaire",
        widget=forms.PasswordInput(attrs={"class": "form-control"}),
        min_length=8,
        help_text="L'étudiant devra changer ce mot de passe lors de sa première connexion.",
    )
    password_confirm = forms.CharField(
        label="Confirmation du mot de passe",
        max_length=128,
        widget=forms.PasswordInput(attrs={"class": "form-control"}),
    )

    def clean_email(self):
        """
        Valide qu'aucun utilisateur actif ne détient déjà l'adresse e-mail soumise.

        Returns
        -------
        str
            L'adresse e-mail normalisée si elle est unique.

        Raises
        ------
        ValidationError
            Si un utilisateur avec cet e-mail existe déjà dans le système.
        """
        email = self.cleaned_data.get("email")
        if User.objects.filter(email=email).exists():
            raise ValidationError("Un utilisateur avec cet e-mail existe déjà.")
        return email

    def clean(self):
        """
        Validation inter-champs : confirme la correspondance des mots de passe et exécute les validateurs Django.

        La vérification de la force du mot de passe est effectuée contre un
        objet ``User`` provisoire rempli avec les données du formulaire afin
        que ``UserAttributeSimilarityValidator`` de Django puisse comparer le
        mot de passe au nom et à l'e-mail de l'étudiant.

        Raises
        ------
        ValidationError
            Si les mots de passe ne correspondent pas ou échouent aux validateurs de Django.
        """
        cleaned_data = super().clean()
        password = cleaned_data.get("password")
        password_confirm = cleaned_data.get("password_confirm")

        if password and password_confirm and password != password_confirm:
            raise ValidationError(
                {"password_confirm": "Les mots de passe ne correspondent pas."}
            )

        if password:
            # Construire un User non persisté pour que les validateurs de similarité d'attributs
            # aient accès au nom et à l'e-mail de l'étudiant.
            tentative_user = User(
                email=cleaned_data.get("email", ""),
                nom=cleaned_data.get("nom", ""),
                prenom=cleaned_data.get("prenom", ""),
                role=User.Role.ETUDIANT,
            )
            try:
                validate_password(password, user=tentative_user)
            except ValidationError as exc:
                raise ValidationError({"password": cast(Any, exc.messages)})

        return cleaned_data

    def create_student(self, niveau=None):
        """
        Persiste le nouveau compte étudiant en utilisant les données validées du formulaire.

        Le compte est créé avec ``must_change_password=True`` afin que
        l'étudiant soit forcé de définir son propre mot de passe à la
        première connexion.

        Parameters
        ----------
        niveau : int or None
            Niveau académique déduit du contexte d'inscription (1, 2, ou 3).
            Passé à ``None`` lorsque le mode d'inscription est COURSE plutôt que LEVEL.

        Returns
        -------
        User
            L'instance utilisateur étudiant nouvellement créée.
        """
        student = User.objects.create_user(
            email=self.cleaned_data["email"],
            password=self.cleaned_data["password"],
            nom=self.cleaned_data["nom"],
            prenom=self.cleaned_data["prenom"],
            role=User.Role.ETUDIANT,
            actif=True,
            must_change_password=True,
            niveau=int(niveau) if niveau else None,
        )
        return student


class EnrollmentForm(forms.Form):
    """
    Formulaire pour inscrire un étudiant à des cours ou à un niveau académique complet.

    Les champs se comportent différemment selon ``enrollment_type`` :

    - LEVEL  : ``departement`` et ``niveau`` sont requis ; ``courses`` est ignoré.
    - COURSE : ``courses`` est requis ; ``departement`` et ``niveau`` sont ignorés.

    Soit ``student_email`` (compte existant), soit ``create_new_student``
    (création de compte à la volée) doit être fourni — mais pas les deux.
    """

    ENROLLMENT_TYPE_CHOICES = [
        ("LEVEL", "Inscription à un niveau complet (Année 1, 2 ou 3)"),
        ("COURSE", "Inscription à un ou plusieurs cours spécifiques"),
    ]

    enrollment_type = forms.ChoiceField(
        choices=ENROLLMENT_TYPE_CHOICES,
        label="Type d'inscription",
        widget=forms.RadioSelect(attrs={"class": "form-check-input"}),
        initial="COURSE",
    )

    # Département / filière utilisé uniquement pour le mode d'inscription LEVEL.
    departement = forms.ModelChoiceField(
        queryset=Departement.objects.filter(actif=True).order_by("nom_departement"),
        label="Département / Filière",
        required=False,
        widget=forms.Select(attrs={"class": "form-select"}),
        empty_label="Sélectionner un département",
        help_text="Seuls les cours de ce département seront inclus",
    )

    # Niveau académique (1, 2 ou 3) utilisé uniquement pour le mode d'inscription LEVEL.
    niveau = forms.ChoiceField(
        choices=[(1, "Année 1"), (2, "Année 2"), (3, "Année 3")],
        label="Niveau d'étude",
        required=False,
        widget=forms.Select(attrs={"class": "form-select"}),
        help_text="Sélectionnez le niveau pour l'inscription à un niveau complet",
    )

    # E-mail d'un compte étudiant existant.
    student_email = forms.EmailField(
        label="E-mail de l'étudiant (si compte existant)",
        required=False,
        widget=forms.EmailInput(
            attrs={"class": "form-control", "placeholder": "email@example.com"}
        ),
    )

    # Bascule pour créer un nouveau compte étudiant à la volée.
    create_new_student = forms.BooleanField(
        label="Créer un nouveau compte étudiant",
        required=False,
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
    )

    # Année académique cible pour l'inscription.
    academic_year = forms.ModelChoiceField(
        queryset=AnneeAcademique.objects.all().order_by("-libelle"),
        label="Année Académique",
        widget=forms.Select(attrs={"class": "form-select"}),
        empty_label="Sélectionner une année académique",
    )

    # Un ou plusieurs cours — utilisé uniquement pour le mode d'inscription COURSE.
    courses = forms.ModelMultipleChoiceField(
        queryset=Cours.objects.none(),
        label="Cours",
        required=False,
        widget=forms.CheckboxSelectMultiple(),
    )

    def __init__(self, *args, **kwargs):
        """
        Initialise le formulaire et remplit le queryset des cours.

        Le queryset par défaut inclut tous les cours actifs triés par
        département puis code de cours. La vue peut surcharger ce queryset
        après instanciation pour le restreindre à l'année académique
        actuellement active.
        """
        super().__init__(*args, **kwargs)
        self.fields["courses"].queryset = (
            Cours.objects.filter(actif=True)
            .select_related("id_annee", "id_departement")
            .order_by("id_departement__nom_departement", "code_cours")
        )

    def clean(self):
        """
        Validation inter-champs pour le type d'inscription et la sélection de l'étudiant.

        Règles appliquées :
        - Le mode LEVEL nécessite à la fois ``departement`` et ``niveau``.
        - Le mode COURSE nécessite au moins un cours sélectionné.
        - Exactement un de ``student_email`` ou ``create_new_student`` doit
          être fourni — fournir les deux ou aucun est une erreur.

        Raises
        ------
        ValidationError
            Avec des messages d'erreur au niveau du champ pour chaque règle violée.
        """
        cleaned_data = super().clean()
        enrollment_type = cleaned_data.get("enrollment_type")
        student_email = cleaned_data.get("student_email")
        create_new_student = cleaned_data.get("create_new_student")
        niveau = cleaned_data.get("niveau")

        # Valider les champs requis en fonction du mode d'inscription sélectionné.
        if enrollment_type == "LEVEL":
            if not cleaned_data.get("departement"):
                raise ValidationError(
                    {
                        "departement": "Vous devez sélectionner un département pour une inscription à un niveau complet."
                    }
                )
            if not niveau:
                raise ValidationError(
                    {
                        "niveau": "Vous devez sélectionner un niveau pour une inscription à un niveau complet."
                    }
                )
        elif enrollment_type == "COURSE":
            courses = cleaned_data.get("courses")
            if not courses:
                raise ValidationError(
                    {
                        "courses": "Vous devez sélectionner au moins un cours."
                    }
                )

        # S'assurer qu'exactement une méthode d'identification de l'étudiant est fournie.
        if not create_new_student and not student_email:
            raise ValidationError(
                {
                    "student_email": "Vous devez soit sélectionner un étudiant existant, soit créer un nouveau compte."
                }
            )

        # Fournir les deux est ambigu — rejeter pour éviter des problèmes de données silencieux.
        if create_new_student and student_email:
            raise ValidationError(
                {
                    "create_new_student": "Vous ne pouvez pas créer un nouveau compte et utiliser un e-mail existant en même temps."
                }
            )

        return cleaned_data
