"""
Modèle de journal d'audit pour le système UniAbsences.

Ce module définit ``LogAudit``, la piste d'audit immuable en append-only
utilisée à travers l'application pour enregistrer les actions de sécurité
et critiques sur le plan métier.

``LogAudit``
    Chaque enregistrement capture : l'utilisateur agissant (nullable —
    préservé lorsque le compte est supprimé), le type d'action, le type
    et l'identifiant de l'objet ciblé, un niveau de gravité (INFO /
    WARNING / CRITIQUE), l'adresse IP du client et un horodatage UTC.

    Les enregistrements sont volontairement en écriture unique : il
    n'existe aucune voie ``update()`` ou ``delete()`` dans la couche
    applicative. Le niveau ``CRITIQUE`` est réservé aux événements tels
    que les blocages d'éligibilité à l'examen et les suppressions
    massives d'utilisateurs.

Appelé par ``apps.audits.utils.log_action`` à travers le code source.

Fait partie du système d'audit UniAbsences.
"""

from django.conf import settings
from django.db import models


class LogAudit(models.Model):
    """
    Entrée immuable du journal d'audit enregistrant une action utilisateur unique.

    Chaque enregistrement capture l'utilisateur agissant, une description
    textuelle libre de l'action, l'adresse IP du client, un horodatage UTC
    (défini automatiquement à la création), un niveau de gravité et des
    références optionnelles à l'objet affecté (``objet_type`` + ``objet_id``).

    Décisions de conception
    -----------------------
    - ``id_utilisateur`` utilise ``SET_NULL`` afin que les entrées de
      journal soient préservées même après la suppression du compte
      utilisateur (piste d'audit conforme au RGPD).
    - Il n'existe aucune voie ``update()`` ou ``delete()`` dans la couche
      applicative. L'administration Django désactive également la
      suppression (voir ``LogAuditAdmin.has_delete_permission``).
    - Le niveau ``CRITIQUE`` est réservé aux événements à fort impact tels
      que les blocages d'éligibilité à l'examen et les suppressions
      massives d'utilisateurs.

    Attributs
    ---------
    id_log : int
        Clé primaire auto-incrémentée.
    id_utilisateur : User or None
        L'utilisateur ayant effectué l'action. ``None`` si le compte a
        depuis été supprimé.
    action : str
        Description textuelle libre de l'action (max 500 caractères après
        nettoyage dans ``log_action``).
    date_action : datetime
        Horodatage UTC défini automatiquement à la création de l'enregistrement.
    adresse_ip : str
        Adresse IP du client capturée au moment de l'action.
    niveau : str
        Niveau de gravité : ``"INFO"``, ``"WARNING"`` ou ``"CRITIQUE"``.
    objet_type : str or None
        Catégorie de l'objet affecté (l'une de ``OBJET_TYPE_CHOICES``).
    objet_id : int or None
        Clé primaire de l'objet affecté.
    """

    NIVEAU_CHOICES = [
        ("INFO", "Information"),
        ("WARNING", "Avertissement"),
        ("CRITIQUE", "Critique"),
    ]

    OBJET_TYPE_CHOICES = [
        ("USER", "Utilisateur"),
        ("COURS", "Cours"),
        ("FACULTE", "Faculté"),
        ("DEPARTEMENT", "Département"),
        ("INSCRIPTION", "Inscription"),
        ("ABSENCE", "Absence"),
        ("JUSTIFICATION", "Justification"),
        ("SEANCE", "Séance"),
        ("EXPORT", "Export"),
        ("SYSTEM", "Système"),
        ("AUTRE", "Autre"),
    ]

    id_log = models.AutoField(primary_key=True, db_column="id_log")

    id_utilisateur = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        models.SET_NULL,  # Préserve le log si l'utilisateur est supprimé (RGPD)
        db_column="id_utilisateur",
        verbose_name="Utilisateur",
        related_name="audit_logs",
        null=True,
        blank=True,
    )
    action = models.TextField(
        verbose_name="Action effectuée", help_text="Description détaillée de l'action"
    )
    date_action = models.DateTimeField(
        auto_now_add=True,
        db_column="date_action",
        verbose_name="Date et heure",
        db_index=True,
    )
    adresse_ip = models.GenericIPAddressField(
        db_column="adresse_ip",
        verbose_name="Adresse IP",
        help_text="Adresse IP de l'utilisateur ayant effectué l'action",
    )
    niveau = models.CharField(
        max_length=20,
        choices=NIVEAU_CHOICES,
        default="INFO",
        verbose_name="Niveau",
        db_index=True,
        help_text="Niveau de criticité de l'action",
    )
    objet_type = models.CharField(
        max_length=50,
        choices=OBJET_TYPE_CHOICES,
        null=True,
        blank=True,
        verbose_name="Type d'objet",
        db_index=True,
        help_text="Type d'objet affecté par l'action",
    )
    objet_id = models.IntegerField(
        null=True,
        blank=True,
        verbose_name="ID de l'objet",
        db_index=True,
        help_text="Identifiant de l'objet affecté",
    )

    class Meta:
        """Métadonnées Django : table ``log_audit``, tri chronologique inverse et index d'audit."""

        managed = True
        db_table = "log_audit"
        app_label = "audits"
        verbose_name = "Journal d'audit"
        verbose_name_plural = "Journaux d'audit"
        ordering = ["-date_action"]
        indexes = [
            models.Index(fields=["date_action", "niveau"]),
            models.Index(fields=["objet_type", "objet_id"]),
            models.Index(fields=["id_utilisateur", "date_action"]),
            models.Index(fields=["niveau", "date_action"]),
        ]

    def __str__(self):
        """Retourne un résumé concis : horodatage, acteur et les 50 premiers caractères de l'action."""
        return f"{self.date_action} - {self.id_utilisateur} : {self.action[:50]}"
