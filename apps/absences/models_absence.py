"""
Modèles métier principaux des absences : Absence et Justification.

Ce module définit les deux modèles métier centraux du système de gestion des
absences UniAbsences. Un enregistrement Absence relie une inscription d'étudiant
(Inscription) à une séance de cours spécifique (Seance) et enregistre le type,
la durée et le statut de justification actuel. Un enregistrement Justification
contient le document justificatif et l'état du workflow soumis par l'étudiant
pour examen par le secrétariat.

Responsabilités :
  - Définir le modèle Absence avec sa machine à états de statut
    (NON_JUSTIFIEE, EN_ATTENTE, JUSTIFIEE) et les règles de validation métier.
  - Définir le modèle Justification avec sa propre machine à états d'approbation
    (EN_ATTENTE, ACCEPTEE, REFUSEE).
  - Faire respecter les contraintes métier (durée positive, absence partielle
    < durée de séance) à la fois dans clean() et via la contrainte CHECK
    en base de données.

Fait partie du système de gestion des absences UniAbsences.
"""
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxLengthValidator, MinValueValidator
from django.db import models


class Absence(models.Model):
    """
    Représente l'absence d'un étudiant à une séance de cours unique (Seance).

    Chaque Absence est identifiée de façon unique par la paire
    (id_inscription, id_seance), garantie par une contrainte unique_together.
    Le champ statut pilote le workflow de justification :

      NON_JUSTIFIEE → (l'étudiant soumet un document) → EN_ATTENTE
                    → (le secrétariat approuve)        → JUSTIFIEE
                    → (le secrétariat refuse)          → NON_JUSTIFIEE

    Seules les absences NON_JUSTIFIEE comptent dans le calcul du seuil
    d'éligibilité ; les absences EN_ATTENTE ne pénalisent pas l'étudiant
    pendant que le document est en cours d'examen.
    """

    class TypeAbsence(models.TextChoices):
        """
        Énumération des types d'absence pris en charge par le système.

        ABSENT et PARTIEL sont les deux types actifs utilisés dans les nouveaux
        enregistrements. Les valeurs restantes (HEURE, SEANCE, JOURNEE, RETARD)
        sont des alias hérités conservés uniquement pour la rétrocompatibilité
        dans les requêtes de migration de données et ne doivent pas être
        utilisés dans le nouveau code applicatif.
        """

        ABSENT = "ABSENT", "Absent"
        PARTIEL = "PARTIEL", "Absence partielle"

        # Alias hérités conservés pour la rétrocompatibilité dans les requêtes de migration de données uniquement.
        # NE PAS utiliser dans le nouveau code.
        HEURE = "HEURE", "Heure (legacy)"
        SEANCE = "SEANCE", "Séance (legacy)"
        JOURNEE = "JOURNEE", "Journée (legacy)"
        RETARD = "RETARD", "Retard (legacy)"

    class Statut(models.TextChoices):
        """
        États du workflow de justification pour un enregistrement d'absence.

        NON_JUSTIFIEE : état par défaut — l'absence n'a pas de justification valide.
        EN_ATTENTE : un document justificatif a été soumis et attend l'examen du secrétariat.
        JUSTIFIEE : le secrétariat a accepté le document justificatif.
        """

        EN_ATTENTE = "EN_ATTENTE", "En attente"
        JUSTIFIEE = "JUSTIFIEE", "Justifiée"
        NON_JUSTIFIEE = "NON_JUSTIFIEE", "Non justifiée"

    # Alias de rétrocompatibilité pour le code qui référence l'ancienne liste de tuples.
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
        """Métadonnées Django : table ``absence``, index, contrainte de durée et unicité (inscription, séance)."""

        managed = True
        db_table = "absence"
        app_label = "absences"
        verbose_name = "Absence"
        verbose_name_plural = "Absences"
        # Ordre d'affichage par défaut : séance la plus récente en premier.
        ordering = ["-id_seance__date_seance", "-id_seance__heure_debut"]
        indexes = [
            # Accélère le listing des absences par étudiant filtré par statut.
            models.Index(fields=["id_inscription", "statut"]),
            # Accélère le listing des absences par séance filtré par statut.
            models.Index(fields=["id_seance", "statut"]),
            # Accélère les requêtes de seuil d'éligibilité filtrées par statut et type.
            models.Index(fields=["statut", "type_absence"]),
        ]
        constraints = [
            # Garde au niveau base de données qui reflète le MinValueValidator —
            # empêche l'écriture de durées nulles ou négatives même via SQL brut.
            models.CheckConstraint(
                condition=models.Q(duree_absence__gte=0.01),
                name="absence_duree_absence_positive",
            ),
        ]
        # Empêche d'enregistrer le même étudiant deux fois comme absent pour la même séance.
        unique_together = (("id_inscription", "id_seance"),)

    def clean(self):
        """
        Applique les règles de validation métier avant la sauvegarde.

        Valide :
        - duree_absence doit être strictement positive.
        - duree_absence ne doit pas dépasser la durée propre de la séance
          (empêche d'enregistrer plus d'heures d'absence que la séance n'a
          réellement duré).
        - Pour le type PARTIEL, duree_absence doit être strictement inférieure
          à la durée de la séance (une absence sur la séance complète doit
          utiliser le type ABSENT).
        - Les absences PARTIEL doivent avoir une durée explicite non nulle.

        Raises:
            ValidationError: si une règle est enfreinte, indexée par nom de champ.
        """
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
                    # L'absence enregistrée ne peut pas dépasser la durée totale de la séance.
                    if duree_f > duree_seance:
                        raise ValidationError(
                            {"duree_absence": f"La durée d'absence ({self.duree_absence}h) ne peut pas dépasser la durée de la séance ({duree_seance}h)."}
                        )
                    # Une absence PARTIEL couvrant la séance complète devrait plutôt être ABSENT.
                    if self.type_absence == self.TypeAbsence.PARTIEL and duree_f >= duree_seance:
                        raise ValidationError(
                            {"duree_absence": f"Une absence partielle ({self.duree_absence}h) doit être strictement inférieure à la durée de la séance ({duree_seance}h). Utilisez le type ABSENT pour une absence complète."}
                        )
            except (AttributeError, TypeError):
                pass  # séance pas encore chargée — validation ignorée

        if self.type_absence == self.TypeAbsence.PARTIEL:
            if self.duree_absence is None or self.duree_absence <= 0:
                raise ValidationError(
                    {"duree_absence": "La durée est obligatoire pour une absence partielle."}
                )

    def save(self, *args, **kwargs):
        """
        Sauvegarde l'absence en exécutant la validation appropriée avant l'écriture en BDD.

        À la création (pk vaut None) : exécute full_clean() qui inclut
        validate_unique() pour intercepter les paires (inscription, séance)
        doublons avant d'atteindre la contrainte BDD.

        En mise à jour : n'exécute que clean() pour éviter la requête
        validate_unique() supplémentaire. Note de performance : full_clean()
        exécute validate_unique(), ce qui coûte une requête BDD supplémentaire
        par save(). Pour les appels mark_absence en lot (30 étudiants), cela
        générerait 30+ requêtes inutiles. La contrainte CHECK BDD
        (duree_absence >= 0.01) et le décorateur @professor_required garantissent
        l'intégrité en mise à jour.
        """
        # FIX ORANGE #13 — full_clean() uniquement à la création, pas en mise à jour.
        if self.pk is None:
            self.full_clean()
        else:
            self.clean()
        super().save(*args, **kwargs)

    def __str__(self):
        """Retourne une représentation lisible identifiant l'étudiant et la date de la séance."""
        return f"Absence de {self.id_inscription.id_etudiant} - {self.id_seance.date_seance}"


class Justification(models.Model):
    """
    Représente un document justificatif soumis par un étudiant pour une absence spécifique.

    Une Justification correspond à exactement une Absence (OneToOneField). Le
    secrétariat examine le document et fait évoluer l'état :

      EN_ATTENTE → ACCEPTEE : absence.statut devient JUSTIFIEE
      EN_ATTENTE → REFUSEE  : absence.statut redevient NON_JUSTIFIEE

    Si une justification est refusée, l'étudiant peut la resoumettre dans le
    délai imparti, ce qui réinitialise l'état à EN_ATTENTE.

    Un enregistrement Justification peut éventuellement contenir un fichier
    document (PDF/image) et un commentaire écrit par l'étudiant. Le secrétariat
    peut ajouter un commentaire de gestion interne.
    """

    class State(models.TextChoices):
        """
        États du workflow d'approbation pour un document justificatif soumis.

        EN_ATTENTE : soumis et en attente de décision du secrétariat.
        ACCEPTEE : le secrétariat a approuvé le document ; l'Absence liée passe
            à JUSTIFIEE via la vue process_justification.
        REFUSEE : le secrétariat a refusé le document ; l'Absence liée
            redevient NON_JUSTIFIEE et l'étudiant peut resoumettre dans le délai.
        """

        EN_ATTENTE = "EN_ATTENTE", "En attente"
        ACCEPTEE = "ACCEPTEE", "Acceptée"
        REFUSEE = "REFUSEE", "Refusée"

    # Alias de rétrocompatibilité pour l'ancien code qui référence la forme liste de tuples.
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
        # Seuls les secrétaires et administrateurs peuvent valider les justifications.
        limit_choices_to={"role__in": ["SECRETAIRE", "ADMIN"]},
    )
    date_validation = models.DateTimeField(
        blank=True,
        null=True,
        verbose_name="Date de validation",
        help_text="Date et heure de validation/refus de la justification",
    )

    class Meta:
        """Métadonnées Django : table ``justification``, tri par date de décision et index pour la file."""

        managed = True
        db_table = "justification"
        app_label = "absences"
        verbose_name = "Justification"
        verbose_name_plural = "Justifications"
        # Affiche les justifications les plus récemment décidées en premier dans les vues liste.
        ordering = ["-date_validation", "-id_justification"]
        indexes = [
            # Accélère la file de validation du secrétariat filtrée par état et date de décision.
            models.Index(fields=["state", "date_validation"]),
            # Accélère les requêtes d'historique par secrétaire.
            models.Index(fields=["validee_par", "state"]),
        ]

    def __str__(self):
        """Retourne une représentation lisible identifiant l'absence liée."""
        return f"Justification pour l'absence n°{self.id_absence.id_absence}"
