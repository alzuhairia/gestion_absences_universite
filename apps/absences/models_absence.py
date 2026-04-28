"""
Modèles cœur des absences : Absence et Justification.
"""
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxLengthValidator, MinValueValidator
from django.db import models


class Absence(models.Model):
    """
    Modèle représentant une absence d'un étudiant à une séance de cours.
    """

    class TypeAbsence(models.TextChoices):
        ABSENT = "ABSENT", "Absent"
        PARTIEL = "PARTIEL", "Absence partielle"

        # Legacy aliases kept for backward-compat in data migration queries only.
        # Do NOT use these in new code.
        HEURE = "HEURE", "Heure (legacy)"
        SEANCE = "SEANCE", "Séance (legacy)"
        JOURNEE = "JOURNEE", "Journée (legacy)"
        RETARD = "RETARD", "Retard (legacy)"

    class Statut(models.TextChoices):
        EN_ATTENTE = "EN_ATTENTE", "En attente"
        JUSTIFIEE = "JUSTIFIEE", "Justifiée"
        NON_JUSTIFIEE = "NON_JUSTIFIEE", "Non justifiée"

    # Backward-compat aliases for code that references the old list-of-tuples.
    TYPE_CHOICES = TypeAbsence.choices
    STATUT_CHOICES = Statut.choices

    id_absence = models.AutoField(primary_key=True)
    id_inscription = models.ForeignKey(
        "enrollments.Inscription",
        models.PROTECT,
        db_column="id_inscription",
        verbose_name="Inscription liée",
        related_name="absences",
    )
    id_seance = models.ForeignKey(
        "academic_sessions.Seance",
        models.PROTECT,
        db_column="id_seance",
        verbose_name="Séance concernée",
        related_name="absences",
    )
    type_absence = models.CharField(
        max_length=20,
        choices=TypeAbsence,
        default=TypeAbsence.ABSENT,
        verbose_name="Type d'absence",
        db_index=True,
    )
    duree_absence = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        verbose_name="Durée (h)",
        validators=[MinValueValidator(0.01)],
        help_text="Durée de l'absence en heures",
    )
    statut = models.CharField(
        max_length=20,
        choices=Statut,
        default=Statut.NON_JUSTIFIEE,
        verbose_name="Statut",
        db_index=True,
    )
    note_professeur = models.CharField(
        max_length=500,
        blank=True,
        default="",
        verbose_name="Note du professeur",
        help_text="Remarque ajoutée par le professeur lors de l'enregistrement",
    )
    encodee_par = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        models.PROTECT,
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
                condition=models.Q(duree_absence__gte=0.01),
                name="absence_duree_absence_positive",
            ),
        ]
        unique_together = (("id_inscription", "id_seance"),)

    def clean(self):
        """Validation métier de l'absence."""
        if self.duree_absence is not None and self.duree_absence <= 0:
            raise ValidationError(
                {"duree_absence": "La durée de l'absence doit être strictement positive."}
            )

        if self.id_seance is not None and self.duree_absence is not None:
            try:
                seance = self.id_seance
                duree_seance = seance.duree_heures()
                if duree_seance:
                    duree_f = float(self.duree_absence)
                    if duree_f > duree_seance:
                        raise ValidationError(
                            {"duree_absence": f"La durée d'absence ({self.duree_absence}h) ne peut pas dépasser la durée de la séance ({duree_seance}h)."}
                        )
                    if self.type_absence == self.TypeAbsence.PARTIEL and duree_f >= duree_seance:
                        raise ValidationError(
                            {"duree_absence": f"Une absence partielle ({self.duree_absence}h) doit être strictement inférieure à la durée de la séance ({duree_seance}h). Utilisez le type ABSENT pour une absence complète."}
                        )
            except (AttributeError, TypeError):
                pass  # seance not loaded yet — skip validation

        if self.type_absence == self.TypeAbsence.PARTIEL:
            if self.duree_absence is None or self.duree_absence <= 0:
                raise ValidationError(
                    {"duree_absence": "La durée est obligatoire pour une absence partielle."}
                )

    def save(self, *args, **kwargs):
        # FIX ORANGE #13 — full_clean() uniquement à la création, pas aux mises à jour.
        # Problème : full_clean() exécute validate_unique() = 1 requête DB supplémentaire
        # à chaque save(). Lors d'un appel mark_absence (30 étudiants), cela génère
        # 30+ requêtes DB inutiles. La contrainte DB CHECK (duree_absence >= 0)
        # et le décorateur @professor_required garantissent l'intégrité sur les updates.
        if self.pk is None:
            self.full_clean()
        else:
            self.clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Absence de {self.id_inscription.id_etudiant} - {self.id_seance.date_seance}"


class Justification(models.Model):
    """
    Modèle représentant une justification d'absence soumise par un étudiant.
    Workflow : EN_ATTENTE -> ACCEPTEE (absence passe a JUSTIFIEE)
                          -> REFUSEE (absence reste NON_JUSTIFIEE)
    """

    class State(models.TextChoices):
        EN_ATTENTE = "EN_ATTENTE", "En attente"
        ACCEPTEE = "ACCEPTEE", "Acceptée"
        REFUSEE = "REFUSEE", "Refusée"

    STATE_CHOICES = State.choices

    id_justification = models.AutoField(primary_key=True)
    id_absence = models.OneToOneField(
        Absence,
        models.PROTECT,
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
        validators=[MaxLengthValidator(2000)],
    )
    commentaire_gestion = models.TextField(
        blank=True,
        null=True,
        verbose_name="Commentaire Gestion",
        help_text="Commentaire interne du secrétariat",
        validators=[MaxLengthValidator(2000)],
    )
    date_soumission = models.DateTimeField(
        auto_now_add=True,
        blank=True,
        null=True,
        verbose_name="Date de soumission",
        help_text="Date et heure de soumission du justificatif par l'étudiant",
    )
    state = models.CharField(
        max_length=20,
        choices=State,
        default=State.EN_ATTENTE,
        verbose_name="État de la demande",
        db_index=True,
    )
    validee_par = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        models.SET_NULL,
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

    def __str__(self):
        return f"Justification pour l'absence n°{self.id_absence.id_absence}"
