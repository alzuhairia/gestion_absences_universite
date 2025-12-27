from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator


class Faculte(models.Model):
    """
    Modèle représentant une faculté de l'université.
    """
    id_faculte = models.AutoField(primary_key=True)
    nom_faculte = models.CharField(
        unique=True, 
        max_length=200, 
        verbose_name="Nom de la faculté",
        db_index=True
    )
    actif = models.BooleanField(
        default=True,
        verbose_name="Actif",
        db_index=True,
        help_text="Désactiver une faculté la masque sans la supprimer"
    )

    class Meta:
        managed = True
        db_table = 'faculte'
        app_label = 'academics'
        verbose_name = "Faculté"
        verbose_name_plural = "Facultés"
        ordering = ['nom_faculte']

    def __str__(self):
        return self.nom_faculte


class Departement(models.Model):
    """
    Modèle représentant un département rattaché à une faculté.
    """
    id_departement = models.AutoField(primary_key=True)
    nom_departement = models.CharField(
        max_length=200, 
        verbose_name="Nom du département",
        db_index=True
    )
    id_faculte = models.ForeignKey(
        Faculte, 
        models.PROTECT,  # Empêche la suppression d'une faculté avec des départements
        db_column='id_faculte',
        verbose_name="Faculté de rattachement",
        related_name='departements'
    )
    actif = models.BooleanField(
        default=True,
        verbose_name="Actif",
        db_index=True,
        help_text="Désactiver un département le masque sans le supprimer"
    )

    class Meta:
        managed = True
        db_table = 'departement'
        app_label = 'academics'
        verbose_name = "Département"
        verbose_name_plural = "Départements"
        ordering = ['id_faculte__nom_faculte', 'nom_departement']
        indexes = [
            models.Index(fields=['id_faculte', 'actif']),
        ]

    def __str__(self):
        return f"{self.nom_departement} ({self.id_faculte.nom_faculte})"


class Cours(models.Model):
    """
    Modèle représentant un cours académique.
    """
    id_cours = models.AutoField(primary_key=True)
    code_cours = models.CharField(
        unique=True, 
        max_length=50, 
        verbose_name="Code du cours",
        db_index=True
    )
    nom_cours = models.CharField(
        max_length=200, 
        verbose_name="Intitulé du cours"
    )
    nombre_total_periodes = models.IntegerField(
        verbose_name="Total périodes (h)",
        validators=[MinValueValidator(1), MaxValueValidator(1000)],
        help_text="Nombre total d'heures de cours"
    )
    seuil_absence = models.IntegerField(
        blank=True, 
        null=True, 
        default=None,
        verbose_name="Seuil d'absence (%)",
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="Seuil personnalisé pour ce cours. Si vide, utilise le seuil par défaut du système."
    )
    id_departement = models.ForeignKey(
        Departement, 
        models.PROTECT,  # Empêche la suppression d'un département avec des cours
        db_column='id_departement',
        verbose_name="Département",
        related_name='cours'
    )
    professeur = models.ForeignKey(
        'accounts.User',
        models.SET_NULL,  # Si le professeur est supprimé, le champ devient NULL
        db_column='id_professeur',
        null=True,
        blank=True,
        verbose_name="Professeur responsable",
        limit_choices_to={'role': 'PROFESSEUR'},
        related_name='cours_enseignes'
    )
    id_annee = models.ForeignKey(
        'academic_sessions.AnneeAcademique',
        models.PROTECT,  # Empêche la suppression d'une année avec des cours
        db_column='id_annee',
        null=True,  # Temporairement nullable pour la migration
        blank=True,  # Temporairement blank pour la migration
        verbose_name="Année Académique",
        related_name='cours',
        help_text="Année académique à laquelle ce cours appartient (assignée automatiquement)"
    )
    niveau = models.IntegerField(
        choices=[(1, 'Année 1'), (2, 'Année 2'), (3, 'Année 3')],
        verbose_name="Niveau d'étude",
        help_text="Niveau du cours (1, 2 ou 3). Détermine les prérequis autorisés.",
        null=True,  # Temporairement nullable pour la migration
        blank=True,  # Temporairement blank pour la migration
        db_index=True
    )
    prerequisites = models.ManyToManyField(
        'self', 
        symmetrical=False, 
        blank=True, 
        verbose_name="Prérequis",
        related_name="required_by",
        help_text="Cours qui doivent être validés avant de s'inscrire à ce cours"
    )
    actif = models.BooleanField(
        default=True,
        verbose_name="Actif",
        db_index=True,
        help_text="Désactiver un cours le masque sans le supprimer"
    )

    class Meta:
        managed = True
        db_table = 'cours'
        app_label = 'academics'
        verbose_name = "Cours"
        verbose_name_plural = "Cours"
        ordering = ['code_cours']
        indexes = [
            models.Index(fields=['id_departement', 'actif']),
            models.Index(fields=['professeur', 'actif']),
            models.Index(fields=['id_annee', 'actif']),
            models.Index(fields=['niveau', 'actif']),
        ]
        # Note: Les contraintes CHECK seront ajoutées via des migrations séparées

    def __str__(self):
        return f"[{self.code_cours}] {self.nom_cours}"
    
    def get_seuil_absence(self):
        """
        Retourne le seuil d'absence du cours ou le seuil par défaut du système.
        """
        if self.seuil_absence is not None:
            return self.seuil_absence
        # Import ici pour éviter l'importation circulaire
        from apps.dashboard.models import SystemSettings
        return SystemSettings.get_settings().default_absence_threshold
