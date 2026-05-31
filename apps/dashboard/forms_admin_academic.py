"""
Formulaires de la structure académique pour le tableau de bord d'administration UniAbsences.

Classes ModelForm utilisées dans les vues CRUD d'administration pour la
hiérarchie académique.

Forms
-----
``FaculteForm``     — Crée / met à jour un enregistrement de faculté.
``DepartementForm`` — Crée / met à jour un département ; filtre les facultés actives.
``CoursForm``       — Crée / met à jour un cours : seuil d'absence, niveau,
                      assignation du professeur et sélection des prérequis.

Fait partie du système de tableau de bord UniAbsences.
"""

from django import forms

from apps.academic_sessions.models import AnneeAcademique
from apps.academics.models import Cours, Departement, Faculte
from apps.accounts.models import User


class FaculteForm(forms.ModelForm):
    """
    ModelForm pour la création et l'édition d'un enregistrement ``Faculte`` (faculté).

    N'expose que le champ de nom ``nom_faculte`` et le drapeau de
    suppression douce ``actif``.  Désactiver une faculté la masque des
    widgets de sélection sans supprimer aucun département ou cours
    dépendant de la base de données.
    """

    class Meta:
        """Configuration ModelForm : modèle ``Faculte``, widgets Bootstrap et libellés FR."""

        model = Faculte
        fields = ["nom_faculte", "actif"]
        widgets = {
            "nom_faculte": forms.TextInput(attrs={"class": "form-control"}),
            "actif": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }
        labels = {
            "nom_faculte": "Nom de la Faculté",
            "actif": "Actif",
        }
        help_texts = {
            "actif": "Désactiver une faculté la masque sans la supprimer",
        }


class DepartementForm(forms.ModelForm):
    """
    ModelForm pour la création et l'édition d'un enregistrement ``Departement`` (département).

    Liste uniquement les facultés actives dans le widget de sélection
    ``id_faculte`` de sorte que les départements ne puissent être
    rattachés à des facultés désactivées.  Le drapeau ``actif`` fournit
    un comportement de suppression douce cohérent avec ``FaculteForm``.
    """

    class Meta:
        """Configuration ModelForm : modèle ``Departement``, widgets Bootstrap et libellés FR."""

        model = Departement
        fields = ["nom_departement", "id_faculte", "actif"]
        widgets = {
            "nom_departement": forms.TextInput(attrs={"class": "form-control"}),
            "id_faculte": forms.Select(attrs={"class": "form-select"}),
            "actif": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }
        labels = {
            "nom_departement": "Nom du Département",
            "id_faculte": "Faculté de rattachement",
            "actif": "Actif",
        }
        help_texts = {
            "actif": "Désactiver un département le masque sans le supprimer",
        }


class CoursForm(forms.ModelForm):
    """
    ModelForm pour la création et l'édition d'un enregistrement ``Cours`` (cours).

    Comportements clés au-delà d'un ModelForm standard :

    - **Filtrage des prérequis** : le queryset ``prerequisites`` est
      restreint à l'initialisation de sorte que seuls les cours d'un
      niveau d'étude inférieur soient sélectionnables (les cours de
      niveau 1 n'ont pas de prérequis ; le niveau 2 peut sélectionner
      le niveau 1 ; le niveau 3 peut sélectionner le niveau 1 ou 2).
      Cette logique s'exécute aussi bien pour les instances existantes
      (où le niveau actuel est connu) que pour les soumissions de
      nouvelle instance (où le niveau provient des données POST).

    - **Année académique automatique** : lors de la création d'un
      nouveau cours, ``clean()`` résout l'``AnneeAcademique`` actuellement
      active et la stocke dans ``_resolved_year`` afin que ``save()``
      puisse l'assigner sans exposer le champ dans l'interface du
      formulaire.

    - **Queryset des professeurs** : restreint aux utilisateurs actifs
      ayant le rôle PROFESSEUR de sorte que les comptes inactifs ou
      non-professeurs ne soient jamais proposés dans la liste
      déroulante.
    """

    prerequisites = forms.ModelMultipleChoiceField(
        queryset=Cours.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple(attrs={"class": "form-check-input"}),
        help_text="Cochez les cours qui sont des prérequis pour ce cours. Laissez vide si aucun prérequis n'est requis.",
    )

    class Meta:
        """Configuration ModelForm : modèle ``Cours``, widgets Bootstrap et champs exposés."""

        model = Cours
        fields = [
            "code_cours",
            "nom_cours",
            "nombre_total_periodes",
            "seuil_absence",
            "id_departement",
            "niveau",
            "professeur",
            "prerequisites",
            "actif",
        ]
        widgets = {
            "code_cours": forms.TextInput(attrs={"class": "form-control"}),
            "nom_cours": forms.TextInput(attrs={"class": "form-control"}),
            "nombre_total_periodes": forms.NumberInput(attrs={"class": "form-control"}),
            "seuil_absence": forms.NumberInput(attrs={"class": "form-control"}),
            "id_departement": forms.Select(attrs={"class": "form-select"}),
            "niveau": forms.Select(attrs={"class": "form-select"}),
            "professeur": forms.Select(attrs={"class": "form-select"}),
            "actif": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def __init__(self, *args, **kwargs):
        """
        Initialise les querysets des champs et la liste des prérequis.

        Restreint ``id_departement`` aux départements actifs et
        ``professeur`` aux comptes de professeurs actifs.  Construit le
        bon queryset de prérequis selon qu'il s'agit d'une édition
        (l'instance a une PK) ou d'une soumission de nouveau cours
        (niveau lu dans les données POST).

        Parameters
        ----------
        *args, **kwargs
            Transmis à ``ModelForm.__init__``.
        """
        super().__init__(*args, **kwargs)
        # Espace réservé pour l'année académique résolue lors du clean().
        self._resolved_year = None
        self.fields["id_departement"].queryset = Departement.objects.filter(actif=True)
        self.fields["professeur"].queryset = User.objects.filter(
            role=User.Role.PROFESSEUR, actif=True
        )

        if "id_annee" in self.fields:
            self.fields["id_annee"].queryset = AnneeAcademique.objects.all().order_by(
                "-libelle"
            )
            self.fields["id_annee"].widget = forms.HiddenInput()

        self.fields["niveau"].required = True

        if self.instance and self.instance.pk:
            current_niveau = self.instance.niveau

            if current_niveau == 1:
                prerequisite_queryset = Cours.objects.none()
            elif current_niveau == 2:
                prerequisite_queryset = (
                    Cours.objects.filter(actif=True, niveau=1)
                    .exclude(id_cours=self.instance.id_cours)
                    .order_by("code_cours")
                )
            elif current_niveau == 3:
                prerequisite_queryset = (
                    Cours.objects.filter(actif=True, niveau__in=[1, 2])
                    .exclude(id_cours=self.instance.id_cours)
                    .order_by("niveau", "code_cours")
                )
            else:
                prerequisite_queryset = (
                    Cours.objects.filter(actif=True)
                    .exclude(id_cours=self.instance.id_cours)
                    .order_by("code_cours")
                )

            self.fields["prerequisites"].queryset = prerequisite_queryset
            self.fields["prerequisites"].initial = self.instance.prerequisites.all()
        else:
            submitted_niveau = self.data.get("niveau") if self.is_bound else None
            if submitted_niveau:
                try:
                    submitted_niveau = int(submitted_niveau)
                except (TypeError, ValueError):
                    submitted_niveau = None

            if submitted_niveau and submitted_niveau >= 2:
                self.fields["prerequisites"].queryset = Cours.objects.filter(
                    actif=True, niveau__lt=submitted_niveau
                ).order_by("niveau", "code_cours")
            else:
                self.fields["prerequisites"].queryset = Cours.objects.none()

        self.fields["code_cours"].label = "Code du Cours"
        self.fields["nom_cours"].label = "Intitulé du Cours"
        self.fields["nombre_total_periodes"].label = "Total Périodes (h)"
        self.fields["seuil_absence"].label = "Seuil d'Absence (%)"
        self.fields["id_departement"].label = "Département"
        self.fields["niveau"].label = "Niveau d'étude"
        if "id_annee" in self.fields:
            self.fields["id_annee"].label = "Année Académique"
        self.fields["professeur"].label = "Professeur Responsable"
        self.fields["prerequisites"].label = "Prérequis"
        self.fields["actif"].label = "Actif"

        self.fields["niveau"].help_text = (
            "Niveau du cours (1, 2 ou 3). Détermine les prérequis autorisés."
        )
        self.fields["seuil_absence"].help_text = (
            "Seuil personnalisé pour ce cours. Si vide, utilise le seuil par défaut du système."
        )
        self.fields["actif"].help_text = (
            "Désactiver un cours le masque sans le supprimer"
        )

    def clean(self):
        """
        Validation inter-champs et résolution de l'année académique.

        Pour la création d'un nouveau cours, résout l'``AnneeAcademique``
        active (avec repli sur l'année au libellé le plus récent si
        aucune année n'est marquée active) et la stocke dans
        ``self._resolved_year``.

        Raises
        ------
        forms.ValidationError
            Si aucune année académique n'existe en base de données, car
            un cours ne peut être créé sans année associée.

        Returns
        -------
        dict
            Les données du formulaire nettoyées et validées.
        """
        cleaned_data = super().clean()
        if not self.instance.pk:
            # Préfère l'année active ; repli sur la plus récente par libellé.
            active_year = AnneeAcademique.objects.filter(active=True).first()
            if not active_year:
                active_year = AnneeAcademique.objects.order_by("-libelle").first()
            if not active_year:
                raise forms.ValidationError(
                    "Impossible de créer un cours : aucune année académique n'est définie dans le système."
                )
            self._resolved_year = active_year
        return cleaned_data

    def save(self, commit=True):
        """
        Persiste l'instance du cours et met à jour la relation M2M des prérequis.

        Assigne l'année académique résolue aux nouvelles instances
        avant la sauvegarde.  Le champ many-to-many ``prerequisites`` est
        mis à jour via ``set()`` après le ``save()`` principal afin que
        l'instance dispose déjà d'une PK.

        Parameters
        ----------
        commit : bool, optional
            Lorsque ``False``, l'instance est préparée mais non
            sauvegardée en base (les prérequis ne sont pas non plus
            mis à jour).  Par défaut ``True``.

        Returns
        -------
        Cours
            L'instance de cours sauvegardée (ou préparée).
        """
        instance = super().save(commit=False)

        # Rattache l'année académique résolue uniquement aux nouveaux cours.
        if not instance.pk:
            instance.id_annee = self._resolved_year

        if commit:
            instance.save()
            # Met à jour les liens M2M des prérequis après la sauvegarde de l'instance.
            instance.prerequisites.set(self.cleaned_data["prerequisites"])
        return instance
