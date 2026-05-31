"""
Modèle de données pour les inscriptions des étudiants aux cours.

Le modèle ``Inscription`` est l'enregistrement central qui relie un étudiant
(User), un cours (Cours) et une année académique (AnneeAcademique). Il
suit :

- Le type d'inscription (NORMALE ou À_PART)
- Le statut de l'inscription (EN_COURS / VALIDE / NON_VALIDE)
- L'éligibilité à l'examen, calculée automatiquement à partir du taux
  d'absences de l'étudiant par rapport au seuil du cours ou du système
- Une exemption optionnelle à la règle des 40 % qui relève le seuil
  effectif de blocage d'un nombre configurable de points de pourcentage
  (exemption_margin)

Des contraintes CHECK au niveau base de données reflètent la validation au
niveau du modèle afin que l'intégrité des données soit garantie même
lorsque des enregistrements sont écrits en dehors de Django.

Appartient à : UniAbsences — application enrollments.
"""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator
from django.db import models


class Inscription(models.Model):
    """
    Inscription d'un étudiant à un cours pour une année académique donnée.

    Le triplet (id_etudiant, id_cours, id_annee) est unique, empêchant les
    enregistrements en double. Les trois colonnes de clé étrangère
    utilisent ``PROTECT`` pour éviter les suppressions en cascade
    accidentelles.

    Exam eligibility
    ----------------
    ``eligible_examen`` est défini à ``True`` à la création et recalculé
    automatiquement par ``apps.absences.services.recalculer_eligibilite``
    chaque fois qu'une nouvelle absence est enregistrée ou qu'une
    justification est décidée. Ne pas le mettre à jour manuellement.

    Exemption mechanism
    -------------------
    Lorsque ``exemption_40`` vaut ``True``, le seuil effectif de blocage
    devient ``min(seuil + exemption_margin, 100)`` au lieu du ``seuil``
    brut. Un ``motif_exemption`` non vide est obligatoire chaque fois que
    l'exemption est active (appliqué à la fois au niveau du modèle et de la
    contrainte BD).
    """

    # --- Choix de type d'inscription ---
    class TypeInscription(models.TextChoices):
        """Décrit si l'inscription suit le parcours standard ou un arrangement particulier."""

        NORMALE = "NORMALE", "Normale"
        A_PART = "A_PART", "À part"

    # --- Choix de statut d'inscription ---
    class Status(models.TextChoices):
        """États du cycle de vie d'un enregistrement d'inscription."""

        EN_COURS = "EN_COURS", "En cours"    # Inscription active pendant l'année académique.
        VALIDE = "VALIDE", "Validé"           # Clôturée et validée en fin d'année.
        NON_VALIDE = "NON_VALIDE", "Non validé"  # Clôturée et invalidée en fin d'année.

    TYPE_CHOICES = TypeInscription.choices
    STATUS_CHOICES = Status.choices

    # --- Champs ---
    id_inscription = models.AutoField(primary_key=True)

    id_etudiant = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        models.PROTECT,  # Bloque la suppression d'un étudiant ayant des enregistrements d'inscription.
        db_column="id_etudiant",
        verbose_name="Étudiant",
        related_name="inscriptions",
        limit_choices_to={"role": "ETUDIANT"},
    )
    id_cours = models.ForeignKey(
        "academics.Cours",
        models.PROTECT,  # Bloque la suppression d'un cours ayant des enregistrements d'inscription.
        db_column="id_cours",
        verbose_name="Cours",
        related_name="inscriptions",
    )
    id_annee = models.ForeignKey(
        "academic_sessions.AnneeAcademique",
        models.PROTECT,  # Bloque la suppression d'une année académique ayant des enregistrements d'inscription.
        db_column="id_annee",
        verbose_name="Année Académique",
        related_name="inscriptions",
    )
    type_inscription = models.CharField(
        max_length=20,
        choices=TypeInscription,
        default=TypeInscription.NORMALE,
        verbose_name="Type d'inscription",
        db_index=True,
    )
    eligible_examen = models.BooleanField(
        default=True,
        verbose_name="Éligible examen ?",
        db_index=True,
        help_text="Calculé automatiquement selon le taux d'absences. Ne pas modifier manuellement.",
    )
    status = models.CharField(
        max_length=20,
        choices=Status,
        default=Status.EN_COURS,
        verbose_name="Statut",
        db_index=True,
    )

    # Champs d'exemption — permettent au secrétaire de surcharger le seuil par défaut.
    exemption_40 = models.BooleanField(
        default=False,
        verbose_name="Exemption 40%",
        help_text="Si activé, l'étudiant est exempté du seuil de 40% d'absences",
    )
    motif_exemption = models.TextField(
        blank=True,
        null=True,
        verbose_name="Motif de l'exemption",
        help_text="Raison de l'exemption (obligatoire si exemption activée)",
    )
    exemption_margin = models.PositiveIntegerField(
        default=10,
        validators=[MaxValueValidator(100)],
        verbose_name="Marge d'exemption (%)",
        help_text=(
            "Points de pourcentage ajoutés au seuil quand l'étudiant est exempté. "
            "Ex: seuil=40%, marge=10% → bloqué à 50%."
        ),
    )

    class Meta:
        """Métadonnées Django : table ``inscription`` et contrainte d'unicité (étudiant, cours, année)."""

        managed = True
        db_table = "inscription"
        app_label = "enrollments"
        # Chaque étudiant ne peut être inscrit qu'une seule fois par cours par année académique.
        unique_together = (("id_etudiant", "id_cours", "id_annee"),)
        verbose_name = "Inscription"
        verbose_name_plural = "Inscriptions"
        indexes = [
            # Optimise les requêtes filtrant par étudiant + année + statut (pattern le plus courant).
            models.Index(fields=["id_etudiant", "id_annee", "status"]),
            # Optimise les requêtes de recalcul d'absences filtrant par cours + année + statut.
            models.Index(fields=["id_cours", "id_annee", "status"]),
            # Optimise les requêtes du tableau de bord d'éligibilité.
            models.Index(fields=["eligible_examen", "status"]),
        ]
        constraints = [
            # L'exemption nécessite un texte de justification non vide.
            models.CheckConstraint(
                condition=(
                    models.Q(exemption_40=False)
                    | (
                        models.Q(motif_exemption__isnull=False)
                        & ~models.Q(motif_exemption="")
                    )
                ),
                name="inscription_exemption_requires_motif",
            ),
            # Protection contre les valeurs de statut arbitraires écrites en dehors de Django.
            models.CheckConstraint(
                condition=models.Q(status__in=["EN_COURS", "VALIDE", "NON_VALIDE"]),
                name="inscription_status_valid_values",
            ),
            # Protection contre les valeurs de type arbitraires écrites en dehors de Django.
            models.CheckConstraint(
                condition=models.Q(type_inscription__in=["NORMALE", "A_PART"]),
                name="inscription_type_valid_values",
            ),
            # S'assurer que la marge d'exemption est dans [0, 100] au niveau BD.
            models.CheckConstraint(
                condition=models.Q(exemption_margin__gte=0, exemption_margin__lte=100),
                name="inscription_exemption_margin_range",
            ),
        ]

    def clean(self):
        """
        Valide qu'un motif d'exemption est fourni lorsque le flag d'exemption est activé.

        Raises
        ------
        ValidationError
            Si ``exemption_40`` vaut True mais que ``motif_exemption`` est vide ou ne contient que des espaces.
        """
        if self.exemption_40 and (
            not self.motif_exemption or not self.motif_exemption.strip()
        ):
            raise ValidationError(
                {
                    "motif_exemption": "Un motif est obligatoire lorsque l'exemption est activée."
                }
            )

    def save(self, *args, **kwargs):
        """
        Exécute la validation complète avant de persister l'enregistrement.

        Pour les mises à jour partielles (par ex. clôture d'une inscription
        via ``update_fields``), seul ``clean()`` est appelé pour éviter de
        réexécuter les validateurs de champs sur des données inchangées.
        Pour les sauvegardes complètes, ``full_clean()`` est appelé afin que
        tous les validateurs de champs et la méthode ``clean()`` soient
        exécutés.

        Parameters
        ----------
        *args, **kwargs
            Transmis à la méthode ``Model.save()`` parente.
        """
        if kwargs.get("update_fields"):
            # Mise à jour partielle (par ex. écriture du seul statut lors de la clôture) —
            # exécute la validation des règles métier sans revérifier tous les validateurs de champs.
            self.clean()
        else:
            # Sauvegarde complète — exécute chaque validateur, y compris ceux au niveau des champs.
            self.full_clean()
        super().save(*args, **kwargs)

    @property
    def is_active(self):
        """
        Renvoie True si l'inscription est actuellement en cours (EN_COURS).

        Utiliser cette propriété au lieu de comparer directement les chaînes
        ``status`` afin que la vérification reste alignée sur les valeurs de
        l'enum ``Status``.
        """
        return self.status == self.Status.EN_COURS

    def cloture(self, valide: bool, save: bool = True):
        """
        Clôt l'inscription en fin d'année en la faisant sortir de EN_COURS.

        Parameters
        ----------
        valide : bool
            ``True`` pour marquer l'inscription comme VALIDE ; ``False`` pour NON_VALIDE.
        save : bool
            Indique s'il faut persister le changement de statut immédiatement
            (par défaut : True). Passer ``False`` pour différer la sauvegarde
            lors du traitement par lots de plusieurs clôtures.

        Raises
        ------
        ValueError
            Si l'inscription n'est pas actuellement EN_COURS (c'est-à-dire déjà clôturée).
        """
        if self.status != self.Status.EN_COURS:
            raise ValueError(
                f"Impossible de cloturer une inscription au statut '{self.status}'."
            )
        self.status = self.Status.VALIDE if valide else self.Status.NON_VALIDE
        if save:
            # Mise à jour partielle — n'écrit que la colonne status dans la base de données.
            self.save(update_fields=["status"])

    def __str__(self):
        return f"{self.id_etudiant.nom} {self.id_etudiant.prenom} -> {self.id_cours.nom_cours}"
