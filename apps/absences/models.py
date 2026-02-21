from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models


class Absence(models.Model):
    """
    Modèle représentant une absence d'un étudiant à une séance de cours.
    """

    # --- CHOIX POUR LE JURY ---
    TYPE_CHOICES = [
        ("HEURE", "Heure"),
        ("SEANCE", "Séance"),
        ("JOURNEE", "Journée"),
    ]

    STATUT_CHOICES = [
        ("EN_ATTENTE", "En attente"),
        ("JUSTIFIEE", "Justifiée"),
        ("NON_JUSTIFIEE", "Non justifiée"),
    ]

    # --- CHAMPS ---
    id_absence = models.AutoField(primary_key=True)
    id_inscription = models.ForeignKey(
        "enrollments.Inscription",
        models.PROTECT,  # Empêche la suppression d'une inscription avec des absences
        db_column="id_inscription",
        verbose_name="Inscription liée",
        related_name="absences",
    )
    id_seance = models.ForeignKey(
        "academic_sessions.Seance",
        models.PROTECT,  # Empêche la suppression d'une séance avec des absences
        db_column="id_seance",
        verbose_name="Séance concernée",
        related_name="absences",
    )
    type_absence = models.CharField(
        max_length=20,
        choices=TYPE_CHOICES,
        default="SEANCE",
        verbose_name="Type d'absence",
        db_index=True,
    )
    duree_absence = models.FloatField(
        verbose_name="Durée (h)",
        validators=[MinValueValidator(0.0)],
        help_text="Durée de l'absence en heures",
    )
    statut = models.CharField(
        max_length=20,
        choices=STATUT_CHOICES,
        default="EN_ATTENTE",
        verbose_name="Statut",
        db_index=True,
    )
    encodee_par = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        models.PROTECT,  # Empêche la suppression d'un utilisateur ayant encodé des absences
        db_column="encodee_par",
        verbose_name="Agent ayant encodé",
        related_name="absences_encodees",
    )

    class Meta:
        managed = True
        db_table = "absence"
        app_label = "absences"
        verbose_name = "Absence"
        verbose_name_plural = "Absences"
        ordering = ["-id_seance__date_seance", "-id_seance__heure_debut"]
        indexes = [
            models.Index(fields=["id_inscription", "statut"]),
            models.Index(fields=["id_seance", "statut"]),
            models.Index(fields=["statut", "type_absence"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(duree_absence__gte=0),
                name="absence_duree_absence_non_negative",
            ),
        ]
        unique_together = (("id_inscription", "id_seance"),)

    def clean(self):
        """Validation: durée positive"""
        if self.duree_absence < 0:
            raise ValidationError(
                {"duree_absence": "La durée de l'absence doit être positive."}
            )

    def save(self, *args, **kwargs):
        # FIX ORANGE #13 — full_clean() uniquement à la création, pas aux mises à jour.
        # Problème : full_clean() exécute validate_unique() = 1 requête DB supplémentaire
        # à chaque save(). Lors d'un appel mark_absence (30 étudiants), cela génère
        # 30+ requêtes DB inutiles. La contrainte DB CHECK (duree_absence >= 0)
        # et le décorateur @professor_required garantissent l'intégrité sur les updates.
        if self.pk is None:
            # Nouvelle absence : validation complète (champs + unicité + custom clean)
            self.full_clean()
        else:
            # Mise à jour existante : uniquement la validation métier custom
            # (évite les requêtes DB de validate_unique() déjà couvertes par la contrainte DB)
            self.clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Absence de {self.id_inscription.id_etudiant} - {self.id_seance.date_seance}"


class Justification(models.Model):
    """
    Modèle représentant une justification d'absence soumise par un étudiant.
    """

    STATE_CHOICES = [
        ("EN_ATTENTE", "En attente"),
        ("ACCEPTEE", "Acceptée"),
        ("REFUSEE", "Refusée"),
    ]

    id_justification = models.AutoField(primary_key=True)
    id_absence = models.OneToOneField(
        Absence,
        models.PROTECT,  # Empêche la suppression d'une absence avec une justification
        db_column="id_absence",
        verbose_name="Absence à justifier",
        related_name="justification",
    )
    document = models.FileField(
        upload_to="justifications/",
        blank=True,
        null=True,
        verbose_name="Fichier",
        help_text="Document justificatif (PDF, image, etc.)",
    )
    commentaire = models.TextField(
        blank=True,
        null=True,
        verbose_name="Commentaire Étudiant",
        help_text="Commentaire de l'étudiant expliquant l'absence",
    )
    commentaire_gestion = models.TextField(
        blank=True,
        null=True,
        verbose_name="Commentaire Gestion",
        help_text="Commentaire interne du secrétariat",
    )

    # DEPRECATED: Utiliser 'state' à la place
    validee = models.BooleanField(
        default=False,
        editable=False,
        help_text="DEPRECATED: Utiliser 'state' à la place. Conservé pour compatibilité.",
    )

    state = models.CharField(
        max_length=20,
        choices=STATE_CHOICES,
        default="EN_ATTENTE",
        verbose_name="État de la demande",
        db_index=True,
    )
    validee_par = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        models.SET_NULL,  # Si l'utilisateur est supprimé, le champ devient NULL
        db_column="validee_par",
        blank=True,
        null=True,
        verbose_name="Validée par",
        related_name="justifications_validees",
        limit_choices_to={"role__in": ["SECRETAIRE", "ADMIN"]},
    )
    date_validation = models.DateTimeField(
        blank=True,
        null=True,
        verbose_name="Date de validation",
        help_text="Date et heure de validation/refus de la justification",
    )

    class Meta:
        managed = True
        db_table = "justification"
        app_label = "absences"
        verbose_name = "Justification"
        verbose_name_plural = "Justifications"
        ordering = ["-date_validation", "-id_justification"]
        indexes = [
            models.Index(fields=["state", "date_validation"]),
            models.Index(fields=["validee_par", "state"]),
        ]

    def save(self, *args, **kwargs):
        """Synchroniser validee (deprecated) avec state"""
        # Synchroniser le champ deprecated avec state
        if self.state == "ACCEPTEE":
            self.validee = True
        elif self.state == "REFUSEE":
            self.validee = False
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Justification pour l'absence n°{self.id_absence.id_absence}"
