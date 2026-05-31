"""
Modèles de la structure académique pour le système UniAbsences.

Ce module définit la hiérarchie académique à trois niveaux utilisée dans
tout le système ainsi que le motif partagé de suppression logique appliqué
à chaque entité.

Modèles
-------
``Faculte``
    Regroupement de plus haut niveau (faculté / école). Supprimé logiquement
    via ``actif``.

``Departement``
    Regroupement de niveau intermédiaire appartenant à une faculté. Supprimé
    logiquement via ``actif``.

``Cours``
    Un cours unique enseigné, appartenant à un département. Comporte :
    - un seuil d'absence optionnel propre au cours (revient au seuil par
      défaut du système provenant de ``SystemSettings`` lorsque
      ``seuil_absence`` vaut None) ;
    - une auto-référence ManyToMany pour les cours prérequis (filtrée par
      niveau d'étude afin d'éviter les prérequis circulaires ou incohérents) ;
    - ``nombre_total_periodes`` — total des heures planifiées, utilisé comme
      dénominateur pour les calculs de taux d'absence ;
    - suppression logique via ``actif``.

Partie de la structure académique d'UniAbsences.
"""

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


class Faculte(models.Model):
    """
    Unité organisationnelle de plus haut niveau représentant une faculté ou
    école universitaire.

    Une faculté regroupe un ou plusieurs départements et agit comme la racine
    de la hiérarchie académique à trois niveaux (faculté → département → cours).

    Attributs
    ---------
    id_faculte : int
        Clé primaire auto-incrémentée.
    nom_faculte : str
        Nom de la faculté unique et lisible par l'humain
        (par ex. "Sciences & Technology").
    actif : bool
        Drapeau de suppression logique. Les facultés inactives sont masquées
        des widgets de sélection mais leurs données historiques sont
        entièrement préservées.
    """

    id_faculte = models.AutoField(primary_key=True)
    nom_faculte = models.CharField(
        unique=True, max_length=200, verbose_name="Nom de la faculté", db_index=True
    )
    actif = models.BooleanField(
        default=True,
        verbose_name="Actif",
        db_index=True,
        help_text="Désactiver une faculté la masque sans la supprimer",
    )

    class Meta:
        """Métadonnées Django : table ``faculte``, libellés français et tri alphabétique."""

        managed = True
        db_table = "faculte"
        app_label = "academics"
        verbose_name = "Faculté"
        verbose_name_plural = "Facultés"
        ordering = ["nom_faculte"]

    def __str__(self):
        """Retourne le nom de la faculté comme représentation lisible par l'humain."""
        return self.nom_faculte


class Departement(models.Model):
    """
    Unité organisationnelle de niveau intermédiaire représentant un
    département académique.

    Chaque département appartient à exactement une faculté et possède un ou
    plusieurs cours. Les noms de département doivent être uniques au sein de
    leur faculté parente (imposé par une ``UniqueConstraint`` sur
    ``nom_departement + id_faculte``).

    Attributs
    ---------
    id_departement : int
        Clé primaire auto-incrémentée.
    nom_departement : str
        Nom du département lisible par l'humain ; unique par faculté.
    id_faculte : Faculte
        Clé étrangère vers la faculté parente (PROTECT — empêche la
        suppression de la faculté tant que des départements la référencent).
    actif : bool
        Drapeau de suppression logique. Les départements inactifs sont
        masqués des widgets de sélection mais leurs données historiques sont
        entièrement préservées.
    """

    id_departement = models.AutoField(primary_key=True)
    nom_departement = models.CharField(
        max_length=200, verbose_name="Nom du département", db_index=True
    )
    id_faculte = models.ForeignKey(
        Faculte,
        models.PROTECT,  # Empêche la suppression d'une faculté avec des départements
        db_column="id_faculte",
        verbose_name="Faculté de rattachement",
        related_name="departements",
    )
    actif = models.BooleanField(
        default=True,
        verbose_name="Actif",
        db_index=True,
        help_text="Désactiver un département le masque sans le supprimer",
    )

    class Meta:
        """Métadonnées Django : table ``departement``, index, et contrainte d'unicité (nom, faculté)."""

        managed = True
        db_table = "departement"
        app_label = "academics"
        verbose_name = "Département"
        verbose_name_plural = "Départements"
        ordering = ["id_faculte__nom_faculte", "nom_departement"]
        indexes = [
            models.Index(fields=["id_faculte", "actif"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["nom_departement", "id_faculte"],
                name="departement_unique_nom_per_faculte",
            ),
        ]

    def __str__(self):
        """Retourne le nom du département et celui de la faculté parente pour une identification facile."""
        return f"{self.nom_departement} ({self.id_faculte.nom_faculte})"


class Cours(models.Model):
    """
    Entité de niveau feuille représentant un cours unique enseigné au sein
    d'un département.

    Un cours appartient à un département, une année académique et un niveau
    d'étude (1–3). Il peut être assigné à un professeur et peut déclarer
    des cours prérequis que les étudiants doivent avoir validés avant de
    s'inscrire.

    Règles métier principales
    -------------------------
    - ``niveau`` détermine quels cours prérequis sont autorisés : un cours
      de niveau N ne peut lister que des cours de niveau < N comme
      prérequis. Cette contrainte est appliquée dans ``CoursForm``
      (``dashboard/forms_admin.py``).
    - ``seuil_absence`` est une surcharge propre au cours pour le seuil de
      taux d'absence. Lorsque ``None``, le seuil par défaut à l'échelle du
      système provenant de ``SystemSettings`` est utilisé
      (voir ``get_seuil_absence``).
    - ``id_annee`` est assigné automatiquement à l'année académique active
      lorsqu'un nouveau cours est créé via ``CoursForm.save()``.
    - Les cours supprimés logiquement (``actif=False``) sont masqués de la
      sélection dans l'interface mais toutes les données de présence
      associées sont préservées.

    Attributs
    ---------
    id_cours : int
        Clé primaire auto-incrémentée.
    code_cours : str
        Code court unique utilisé dans les rapports et exports
        (par ex. "INFO_01").
    nom_cours : str
        Titre complet du cours lisible par l'humain.
    nombre_total_periodes : int
        Nombre total d'heures planifiées ; utilisé comme dénominateur lors
        du calcul du taux d'absence de l'étudiant :
        ``(heures_absent / total_periodes) * 100``.
    seuil_absence : int ou None
        Seuil d'absence propre au cours (pourcentage). Revient au seuil par
        défaut du système lorsque ``None``.
    id_departement : Departement
        Département parent (PROTECT).
    professeur : User ou None
        Enseignant responsable (SET_NULL — le cours survit à la suppression
        de l'enseignant).
    id_annee : AnneeAcademique
        Année académique à laquelle le cours appartient (PROTECT).
    niveau : int
        Niveau d'étude : 1, 2 ou 3.
    prerequisites : ManyToMany[Cours]
        Auto-référence asymétrique listant les cours prérequis.
    actif : bool
        Drapeau de suppression logique.
    """

    # ============================================
    # IDENTIFIANT ET INFORMATIONS DE BASE
    # ============================================

    id_cours = models.AutoField(primary_key=True)
    # Clé primaire auto-incrémentée

    code_cours = models.CharField(
        unique=True, max_length=50, verbose_name="Code du cours", db_index=True
    )
    # Code unique du cours (ex: "INFO_01", "MATH_02")
    # Utilisé pour identifier rapidement un cours

    nom_cours = models.CharField(max_length=200, verbose_name="Intitulé du cours")
    # Nom complet du cours (ex: "Introduction à la programmation")

    nombre_total_periodes = models.IntegerField(
        verbose_name="Total périodes (h)",
        validators=[MinValueValidator(1), MaxValueValidator(1000)],
        help_text="Nombre total d'heures de cours",
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
        help_text="Seuil personnalisé pour ce cours. Si vide, utilise le seuil par défaut du système.",
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
        db_column="id_departement",
        verbose_name="Département",
        related_name="cours",
    )
    # Département auquel appartient le cours
    # PROTECT : empêche la suppression d'un département qui a des cours
    # Cela garantit l'intégrité référentielle

    professeur = models.ForeignKey(
        "accounts.User",
        models.SET_NULL,  # Si le professeur est supprimé, le champ devient NULL
        db_column="id_professeur",
        null=True,
        blank=True,
        verbose_name="Professeur responsable",
        limit_choices_to={"role": "PROFESSEUR"},
        related_name="cours_enseignes",
    )
    # Professeur assigné au cours
    # SET_NULL : si le professeur est supprimé, le champ devient NULL (le cours reste)
    # limit_choices_to : seuls les utilisateurs avec le rôle PROFESSEUR peuvent être assignés

    # ============================================
    # ORGANISATION ACADÉMIQUE
    # ============================================

    id_annee = models.ForeignKey(
        "academic_sessions.AnneeAcademique",
        models.PROTECT,  # Empêche la suppression d'une année avec des cours
        db_column="id_annee",
        verbose_name="Année Académique",
        related_name="cours",
        help_text="Année académique à laquelle ce cours appartient (assignée automatiquement)",
    )
    # Année académique à laquelle ce cours appartient
    # IMPORTANT : Assignée automatiquement à l'année académique active lors de la création
    # (voir CoursForm.save() dans apps/dashboard/forms_admin.py)
    # PROTECT : empêche la suppression d'une année qui a des cours

    niveau = models.IntegerField(
        choices=[(1, "Année 1"), (2, "Année 2"), (3, "Année 3")],
        verbose_name="Niveau d'étude",
        help_text="Niveau du cours (1, 2 ou 3). Détermine les prérequis autorisés.",
        db_index=True,
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
        "self",
        symmetrical=False,  # Si A est prérequis de B, B n'est pas automatiquement prérequis de A
        blank=True,
        verbose_name="Prérequis",
        related_name="required_by",
        help_text="Cours qui doivent être validés avant de s'inscrire à ce cours",
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
        help_text="Désactiver un cours le masque sans le supprimer",
    )

    class Meta:
        """Métadonnées Django : table ``cours``, index optimisés et contraintes métier (seuils, niveau)."""

        managed = True
        db_table = "cours"
        app_label = "academics"
        verbose_name = "Cours"
        verbose_name_plural = "Cours"
        ordering = ["code_cours"]
        indexes = [
            models.Index(fields=["id_departement", "actif"]),
            models.Index(fields=["professeur", "actif"]),
            models.Index(fields=["id_annee", "actif"]),
            models.Index(fields=["niveau", "actif"]),
            models.Index(
                fields=["code_cours"],
                condition=models.Q(actif=True),
                name="cours_code_active_idx",
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(nombre_total_periodes__gte=1)
                    & models.Q(nombre_total_periodes__lte=1000)
                ),
                name="cours_nombre_total_periodes_range",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(seuil_absence__isnull=True)
                    | (
                        models.Q(seuil_absence__gte=0)
                        & models.Q(seuil_absence__lte=100)
                    )
                ),
                name="cours_seuil_absence_range_or_null",
            ),
            models.CheckConstraint(
                condition=models.Q(niveau__in=[1, 2, 3]),
                name="cours_niveau_allowed_values",
            ),
        ]

    def __str__(self):
        """Retourne le code et le nom du cours pour une identification facile dans les listes déroulantes et les logs."""
        return f"[{self.code_cours}] {self.nom_cours}"

    def get_seuil_absence(self):
        """
        Retourne le seuil d'absence effectif pour ce cours.

        Si un seuil propre au cours a été défini (``seuil_absence`` n'est pas
        ``None``), cette valeur est retournée directement. Sinon, la méthode
        revient au seuil par défaut à l'échelle du système stocké dans
        ``SystemSettings``.

        L'import de ``SystemSettings`` est différé pour éviter une erreur
        d'import circulaire au moment du chargement du module (``dashboard``
        importe ``academics``).

        Retourne
        --------
        int
            Seuil d'absence en pourcentage (0–100).
        """
        if self.seuil_absence is not None:
            return self.seuil_absence
        # Import différé pour éviter une dépendance circulaire :
        # academics → dashboard → academics provoquerait une ImportError.
        from apps.dashboard.models import SystemSettings

        return SystemSettings.get_settings().default_absence_threshold
