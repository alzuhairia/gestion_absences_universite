from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class Inscription(models.Model):
    """
    Modèle représentant l'inscription d'un étudiant à un cours pour une année académique.
    """

    # --- CHOIX ---
    TYPE_CHOICES = [
        ("NORMALE", "Normale"),
        ("A_PART", "À part"),
    ]

    STATUS_CHOICES = [
        ("EN_COURS", "En cours"),
        ("VALIDE", "Validé"),
        ("NON_VALIDE", "Non validé"),
    ]

    # --- CHAMPS ---
    id_inscription = models.AutoField(primary_key=True)
    id_etudiant = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        models.PROTECT,  # Empêche la suppression d'un étudiant avec des inscriptions
        db_column="id_etudiant",
        verbose_name="Étudiant",
        related_name="inscriptions",
        limit_choices_to={"role": "ETUDIANT"},
    )
    id_cours = models.ForeignKey(
        "academics.Cours",
        models.PROTECT,  # Empêche la suppression d'un cours avec des inscriptions
        db_column="id_cours",
        verbose_name="Cours",
        related_name="inscriptions",
    )
    id_annee = models.ForeignKey(
        "academic_sessions.AnneeAcademique",
        models.PROTECT,  # Empêche la suppression d'une année avec des inscriptions
        db_column="id_annee",
        verbose_name="Année Académique",
        related_name="inscriptions",
    )
    type_inscription = models.CharField(
        max_length=20,
        choices=TYPE_CHOICES,
        default="NORMALE",
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
        choices=STATUS_CHOICES,
        default="EN_COURS",
        verbose_name="Statut",
        db_index=True,
    )

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

    class Meta:
        managed = True
        db_table = "inscription"
        app_label = "enrollments"
        unique_together = (("id_etudiant", "id_cours", "id_annee"),)
        verbose_name = "Inscription"
        verbose_name_plural = "Inscriptions"
        indexes = [
            models.Index(fields=["id_etudiant", "id_annee", "status"]),
            models.Index(fields=["id_cours", "id_annee", "status"]),
            models.Index(fields=["eligible_examen", "status"]),
        ]
        constraints = [
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
            models.CheckConstraint(
                condition=models.Q(status__in=["EN_COURS", "VALIDE", "NON_VALIDE"]),
                name="inscription_status_valid_values",
            ),
            models.CheckConstraint(
                condition=models.Q(type_inscription__in=["NORMALE", "A_PART"]),
                name="inscription_type_valid_values",
            ),
        ]

    def clean(self):
        """Validation: motif requis si exemption activée"""
        if self.exemption_40 and (
            not self.motif_exemption or not self.motif_exemption.strip()
        ):
            raise ValidationError(
                {
                    "motif_exemption": "Un motif est obligatoire lorsque l'exemption est activée."
                }
            )

    def save(self, *args, **kwargs):
        """Valider avant sauvegarde"""
        # Always run full_clean() (field validators + clean()) on both
        # create and update. Calling only clean() on update skipped
        # field-level validators, potentially allowing invalid data.
        if kwargs.get("update_fields"):
            # Partial update (e.g. cloture) — skip full validation
            self.clean()
        else:
            self.full_clean()
        super().save(*args, **kwargs)

    # FIX VERT #20 — Propriété de commodité : l'inscription est-elle en cours ?
    # Remplace les checks if inscription.status == 'EN_COURS' dispersés dans les vues.
    @property
    def is_active(self):
        return self.status == "EN_COURS"

    def cloture(self, valide: bool, save: bool = True):
        """
        FIX VERT #20 — Méthode officielle pour clôturer une inscription en fin d'année.
        Garantit la transition d'état : EN_COURS → VALIDE / NON_VALIDE.
        Lève ValueError si l'inscription n'est pas EN_COURS.
        """
        if self.status != "EN_COURS":
            raise ValueError(
                f"Impossible de cloturer une inscription au statut '{self.status}'."
            )
        self.status = "VALIDE" if valide else "NON_VALIDE"
        if save:
            self.save(update_fields=["status"])

    def __str__(self):
        return f"{self.id_etudiant.nom} {self.id_etudiant.prenom} -> {self.id_cours.nom_cours}"
