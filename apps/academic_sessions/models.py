"""
FICHIER : apps/academic_sessions/models.py
RESPONSABILITE : Gestion des annees academiques et des seances de cours
FONCTIONNALITES PRINCIPALES :
  - AnneeAcademique : une seule annee active a la fois (contrainte DB unique partielle)
  - Seance : seance de cours avec date/heure, validation et verrouillage
  - Calcul de duree en heures decimales et format lisible (2h30)
  - Contrainte unicite : une seule seance par cours par date
DEPENDANCES CLES : academics.Cours, accounts.User (validated_by)
"""

from datetime import datetime, timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction


# ========================================================================== #
#                          ANNEE ACADEMIQUE                                  #
# ========================================================================== #


class AnneeAcademique(models.Model):
    """
    Modèle représentant une année académique.
    Une seule année peut être active à la fois (contrainte DB).
    """

    id_annee = models.AutoField(primary_key=True)
    libelle = models.CharField(
        unique=True,
        max_length=20,
        verbose_name="Libellé (ex: 2023-2024)",
        db_index=True,
        help_text="Format recommandé: AAAA-AAAA",
    )
    active = models.BooleanField(
        default=False,
        verbose_name="Année en cours ?",
        db_index=True,
        help_text="Une seule année peut être active à la fois",
    )

    class Meta:
        managed = True
        db_table = "annee_academique"
        app_label = "academic_sessions"
        verbose_name = "Année Académique"
        verbose_name_plural = "Années Académiques"
        ordering = ["-libelle"]
        # Contrainte unique partielle pour garantir une seule année active
        constraints = [
            models.UniqueConstraint(
                fields=["active"],
                condition=models.Q(active=True),
                name="unique_active_annee_academique",
            )
        ]

    def clean(self):
        """Validation: une seule année active"""
        if self.active:
            # Vérifier qu'aucune autre année n'est active
            other_active = AnneeAcademique.objects.filter(active=True).exclude(
                pk=self.pk
            )
            if other_active.exists():
                raise ValidationError(
                    "Une autre année académique est déjà active. "
                    "Désactivez-la avant d'activer celle-ci."
                )

    def save(self, *args, **kwargs):
        """S'assurer qu'une seule année est active"""
        with transaction.atomic():
            if self.active:
                # Only deactivate others when active is newly set to True:
                # either the object is new (no pk) or active changed from False.
                activating = not self.pk
                if not activating and self.pk:
                    old_active = (
                        AnneeAcademique.objects.filter(pk=self.pk)
                        .values_list("active", flat=True)
                        .first()
                    )
                    activating = not old_active
                if activating:
                    # Deactivate others BEFORE full_clean so clean() won't reject
                    # the activation. Wrapped in atomic() so rolled back on error.
                    AnneeAcademique.objects.exclude(pk=self.pk).update(active=False)
            self.full_clean()
            super().save(*args, **kwargs)

    def __str__(self):
        return self.libelle


# ========================================================================== #
#                          SEANCE DE COURS                                   #
# ========================================================================== #


class Seance(models.Model):
    """
    Modèle représentant une séance de cours.
    """

    id_seance = models.AutoField(primary_key=True)
    date_seance = models.DateField(verbose_name="Date de la séance", db_index=True)
    heure_debut = models.TimeField(verbose_name="Heure début")
    heure_fin = models.TimeField(verbose_name="Heure fin")
    id_cours = models.ForeignKey(
        "academics.Cours",
        models.PROTECT,  # Empêche la suppression d'un cours avec des séances
        db_column="id_cours",
        verbose_name="Cours",
        related_name="seances",
    )
    id_annee = models.ForeignKey(
        AnneeAcademique,
        models.PROTECT,  # Empêche la suppression d'une année avec des séances
        db_column="id_annee",
        verbose_name="Année académique",
        related_name="seances",
    )
    validated = models.BooleanField(
        default=False,
        verbose_name="Séance validée",
        help_text="Une fois validée, la présence ne peut plus être modifiée par le professeur.",
    )
    validated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="Validée par",
        related_name="seances_validees",
    )
    date_validated = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Date de validation",
    )

    class Meta:
        managed = True
        db_table = "seance"
        app_label = "academic_sessions"
        verbose_name = "Séance"
        verbose_name_plural = "Séances"
        ordering = ["-date_seance", "-heure_debut"]
        indexes = [
            models.Index(fields=["id_cours", "date_seance"]),
            models.Index(fields=["id_annee", "date_seance"]),
            models.Index(
                fields=["id_cours", "id_annee", "date_seance", "heure_debut"],
                name="seance_cours_annee_dt_h_idx",
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["id_cours", "date_seance"],
                name="unique_seance_par_cours_date",
            ),
            models.CheckConstraint(
                condition=models.Q(heure_fin__gt=models.F("heure_debut")),
                name="seance_heure_fin_after_debut",
            ),
        ]

    def clean(self):
        """Validation: heure fin après heure début"""
        if self.heure_debut and self.heure_fin:
            if self.heure_fin <= self.heure_debut:
                raise ValidationError(
                    "L'heure de fin doit être après l'heure de début."
                )

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def duree_heures(self):
        """
        Calcule la durée de la séance en heures (avec décimales pour les minutes).
        Exemple: 08:30 à 10:30 = 2.0 heures
        """
        if not self.heure_debut or not self.heure_fin:
            return 0.0

        # Convertir les TimeField en datetime pour le calcul
        # On utilise une date arbitraire pour le calcul
        date_ref = datetime(2000, 1, 1)
        debut = datetime.combine(date_ref, self.heure_debut)
        fin = datetime.combine(date_ref, self.heure_fin)

        # Si l'heure de fin est avant l'heure de début, on suppose que c'est le lendemain
        if fin < debut:
            fin += timedelta(days=1)

        # Calculer la différence en heures
        delta = fin - debut
        duree_heures = delta.total_seconds() / 3600.0

        return round(duree_heures, 2)

    def duree_formatee(self):
        """
        Retourne la durée formatée de manière lisible.
        Exemples: "2h", "2h30", "1h45", "30min"
        """
        if not self.heure_debut or not self.heure_fin:
            return "0h"

        # Convertir les TimeField en datetime pour le calcul
        date_ref = datetime(2000, 1, 1)
        debut = datetime.combine(date_ref, self.heure_debut)
        fin = datetime.combine(date_ref, self.heure_fin)

        # Si l'heure de fin est avant l'heure de début, on suppose que c'est le lendemain
        if fin < debut:
            fin += timedelta(days=1)

        # Calculer la différence totale en minutes
        delta = fin - debut
        total_minutes = int(delta.total_seconds() / 60)

        # Extraire les heures et minutes
        heures = total_minutes // 60
        minutes = total_minutes % 60

        # Formater selon les cas
        if heures == 0:
            return f"{minutes}min"
        elif minutes == 0:
            return f"{heures}h"
        else:
            return f"{heures}h{minutes:02d}"

    def __str__(self):
        return f"{self.id_cours.nom_cours} - {self.date_seance} ({self.heure_debut})"
