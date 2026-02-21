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
    
    IMPORTANT POUR LA SOUTENANCE :
    - Chaque cours appartient à un niveau (1, 2 ou 3) et une année académique
    - Les prérequis sont filtrés par niveau (un cours de niveau N ne peut avoir que des prérequis < N)
    - Le seuil d'absence peut être personnalisé par cours ou utiliser le seuil par défaut
    - L'année académique est assignée automatiquement à l'année active lors de la création
    """
    
    # ============================================
    # IDENTIFIANT ET INFORMATIONS DE BASE
    # ============================================
    
    id_cours = models.AutoField(primary_key=True)
    # Clé primaire auto-incrémentée
    
    code_cours = models.CharField(
        unique=True, 
        max_length=50, 
        verbose_name="Code du cours",
        db_index=True
    )
    # Code unique du cours (ex: "INFO_01", "MATH_02")
    # Utilisé pour identifier rapidement un cours
    
    nom_cours = models.CharField(
        max_length=200, 
        verbose_name="Intitulé du cours"
    )
    # Nom complet du cours (ex: "Introduction à la programmation")
    
    nombre_total_periodes = models.IntegerField(
        verbose_name="Total périodes (h)",
        validators=[MinValueValidator(1), MaxValueValidator(1000)],
        help_text="Nombre total d'heures de cours"
    )
    # Nombre total d'heures de cours pour ce cours
    # Utilisé pour calculer le taux d'absence : (heures absences / total périodes) * 100
    
    # ============================================
    # GESTION DES ABSENCES
    # ============================================
    
    seuil_absence = models.IntegerField(
        blank=True, 
        null=True, 
        default=None,
        verbose_name="Seuil d'absence (%)",
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="Seuil personnalisé pour ce cours. Si vide, utilise le seuil par défaut du système."
    )
    # Seuil d'absence personnalisé pour ce cours (en pourcentage)
    # Si None, utilise le seuil par défaut défini dans SystemSettings
    # Utilisé pour déterminer si un étudiant est bloqué (taux >= seuil)
    
    # ============================================
    # RATTACHEMENT ORGANISATIONNEL
    # ============================================
    
    id_departement = models.ForeignKey(
        Departement, 
        models.PROTECT,  # Empêche la suppression d'un département avec des cours
        db_column='id_departement',
        verbose_name="Département",
        related_name='cours'
    )
    # Département auquel appartient le cours
    # PROTECT : empêche la suppression d'un département qui a des cours
    # Cela garantit l'intégrité référentielle
    
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
    # Professeur assigné au cours
    # SET_NULL : si le professeur est supprimé, le champ devient NULL (le cours reste)
    # limit_choices_to : seuls les utilisateurs avec le rôle PROFESSEUR peuvent être assignés
    
    # ============================================
    # ORGANISATION ACADÉMIQUE
    # ============================================
    
    id_annee = models.ForeignKey(
        'academic_sessions.AnneeAcademique',
        models.PROTECT,  # Empêche la suppression d'une année avec des cours
        db_column='id_annee',
        verbose_name="Année Académique",
        related_name='cours',
        help_text="Année académique à laquelle ce cours appartient (assignée automatiquement)"
    )
    # Année académique à laquelle ce cours appartient
    # IMPORTANT : Assignée automatiquement à l'année académique active lors de la création
    # (voir CoursForm.save() dans apps/dashboard/forms_admin.py)
    # PROTECT : empêche la suppression d'une année qui a des cours
    
    niveau = models.IntegerField(
        choices=[(1, 'Année 1'), (2, 'Année 2'), (3, 'Année 3')],
        verbose_name="Niveau d'étude",
        help_text="Niveau du cours (1, 2 ou 3). Détermine les prérequis autorisés.",
        db_index=True
    )
    # Niveau académique du cours (1, 2 ou 3)
    # IMPORTANT POUR LA LOGIQUE MÉTIER :
    # - Un cours de niveau N ne peut avoir que des prérequis de niveau < N
    # - Lors de l'inscription à un niveau complet, seuls les cours de ce niveau sont inscrits
    # - Utilisé pour filtrer les cours disponibles lors de l'inscription
    
    # ============================================
    # PRÉREQUIS
    # ============================================
    
    prerequisites = models.ManyToManyField(
        'self', 
        symmetrical=False,  # Si A est prérequis de B, B n'est pas automatiquement prérequis de A
        blank=True, 
        verbose_name="Prérequis",
        related_name="required_by",
        help_text="Cours qui doivent être validés avant de s'inscrire à ce cours"
    )
    # Relation many-to-many avec lui-même pour les prérequis
    # IMPORTANT : Les prérequis sont filtrés par niveau dans le formulaire
    # (voir CoursForm.__init__ dans apps/dashboard/forms_admin.py)
    # Règle métier : un cours de niveau N ne peut avoir que des prérequis de niveau < N
    # Cette règle est appliquée dans le formulaire pour éviter les incohérences
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
            models.Index(
                fields=['code_cours'],
                condition=models.Q(actif=True),
                name='cours_code_active_idx',
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(nombre_total_periodes__gte=1)
                    & models.Q(nombre_total_periodes__lte=1000)
                ),
                name='cours_nombre_total_periodes_range',
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(seuil_absence__isnull=True)
                    | (
                        models.Q(seuil_absence__gte=0)
                        & models.Q(seuil_absence__lte=100)
                    )
                ),
                name='cours_seuil_absence_range_or_null',
            ),
            models.CheckConstraint(
                condition=models.Q(niveau__in=[1, 2, 3]),
                name='cours_niveau_allowed_values',
            ),
        ]

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

