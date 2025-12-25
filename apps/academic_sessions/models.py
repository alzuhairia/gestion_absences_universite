from django.db import models
from django.core.exceptions import ValidationError


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
        help_text="Format recommandé: AAAA-AAAA"
    )
    active = models.BooleanField(
        default=False, 
        verbose_name="Année en cours ?",
        db_index=True,
        help_text="Une seule année peut être active à la fois"
    )

    class Meta:
        managed = True
        db_table = 'annee_academique'
        app_label = 'academic_sessions'
        verbose_name = "Année Académique"
        verbose_name_plural = "Années Académiques"
        ordering = ['-libelle']
        # Contrainte unique partielle pour garantir une seule année active
        constraints = [
            models.UniqueConstraint(
                fields=['active'],
                condition=models.Q(active=True),
                name='unique_active_annee_academique'
            )
        ]

    def clean(self):
        """Validation: une seule année active"""
        if self.active:
            # Vérifier qu'aucune autre année n'est active
            other_active = AnneeAcademique.objects.filter(active=True).exclude(pk=self.pk)
            if other_active.exists():
                raise ValidationError(
                    "Une autre année académique est déjà active. "
                    "Désactivez-la avant d'activer celle-ci."
                )

    def save(self, *args, **kwargs):
        """S'assurer qu'une seule année est active"""
        if self.active:
            # Désactiver toutes les autres années
            AnneeAcademique.objects.exclude(pk=self.pk).update(active=False)
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.libelle


class Seance(models.Model):
    """
    Modèle représentant une séance de cours.
    """
    id_seance = models.AutoField(primary_key=True)
    date_seance = models.DateField(
        verbose_name="Date de la séance",
        db_index=True
    )
    heure_debut = models.TimeField(verbose_name="Heure début")
    heure_fin = models.TimeField(verbose_name="Heure fin")
    id_cours = models.ForeignKey(
        'academics.Cours', 
        models.PROTECT,  # Empêche la suppression d'un cours avec des séances
        db_column='id_cours',
        verbose_name="Cours",
        related_name='seances'
    )
    id_annee = models.ForeignKey(
        AnneeAcademique, 
        models.PROTECT,  # Empêche la suppression d'une année avec des séances
        db_column='id_annee',
        verbose_name="Année académique",
        related_name='seances'
    )

    class Meta:
        managed = True
        db_table = 'seance'
        app_label = 'academic_sessions'
        verbose_name = "Séance"
        verbose_name_plural = "Séances"
        ordering = ['-date_seance', '-heure_debut']
        indexes = [
            models.Index(fields=['id_cours', 'date_seance']),
            models.Index(fields=['id_annee', 'date_seance']),
        ]
        # Note: Les contraintes CHECK seront ajoutées via des migrations séparées

    def clean(self):
        """Validation: heure fin après heure début"""
        if self.heure_debut and self.heure_fin:
            if self.heure_fin <= self.heure_debut:
                raise ValidationError("L'heure de fin doit être après l'heure de début.")

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.id_cours.nom_cours} - {self.date_seance} ({self.heure_debut})"
