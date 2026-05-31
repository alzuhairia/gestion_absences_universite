"""
Modèles de présence par QR code : token, enregistrement de scan validé et journal d'audit.

Ce module définit les trois modèles qui alimentent la fonctionnalité de
check-in autonome par QR code. Un professeur génère un QRAttendanceToken à
durée limitée qui est encodé dans une image QR affichée. Les étudiants scannent
le QR avec leur téléphone, et chaque présence validée est stockée comme
QRScanRecord. Chaque tentative de scan (réussie ou échouée) est également
écrite dans QRScanLog à des fins d'audit de sécurité.

Responsabilités :
  - QRAttendanceToken : token à durée limitée intégré dans l'image QR ;
    transporte des coordonnées GPS facultatives pour la vérification de
    localisation anti-fraude.
  - QRScanRecord : enregistrement persistant d'une présence étudiante validée ;
    rattaché à la Seance (et non au token) pour que les scans survivent aux
    rafraîchissements de token.
  - QRScanLog : piste d'audit immuable pour chaque tentative de scan avec
    statut GPS, code de résultat, token haché et métadonnées client.

Fait partie du système de présence par QR UniAbsences.
"""
import uuid

from django.conf import settings
from django.db import models


class QRAttendanceToken(models.Model):
    """
    Token UUID à courte durée de vie intégré dans une image de QR code pour le scan de présence étudiant.

    Une Seance peut accumuler plusieurs tokens au fil du temps à mesure que le
    professeur les rafraîchit ; seul le dernier token actif et non expiré
    accepte de nouveaux scans. Lorsque verify_location vaut True, les étudiants
    doivent soumettre des coordonnées GPS situées dans un rayon de
    DISTANCE_THRESHOLD_METERS de la position enregistrée du professeur (ou
    du rayon GPS configuré de l'établissement) pour être marqués présents.

    Constantes de classe :
        TOKEN_LIFETIME_MINUTES : durée de vie suggérée par défaut (l'expiration
            réelle est définie par SystemSettings.qr_token_duration_seconds à
            la création).
        DISTANCE_THRESHOLD_METERS : limite de distance GPS de repli lorsqu'aucun
            rayon GPS au niveau système n'est configuré.
    """

    TOKEN_LIFETIME_MINUTES = 15
    DISTANCE_THRESHOLD_METERS = 100

    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False, db_index=True)
    seance = models.ForeignKey(
        "academic_sessions.Seance",
        on_delete=models.CASCADE,
        related_name="qr_tokens",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="qr_tokens_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    is_active = models.BooleanField(default=True, db_index=True)
    verify_location = models.BooleanField(
        default=False,
        help_text="Si activé, la géolocalisation est obligatoire pour valider la présence.",
    )
    # Anti-fraude GPS : position du professeur lors de la génération du QR
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)

    class Meta:
        """Métadonnées Django : table dédiée et tri par date de création décroissante."""

        db_table = "qr_attendance_token"
        app_label = "absences"
        ordering = ["-created_at"]

    def __str__(self):
        """Représentation lisible affichant les 8 premiers caractères du token et la séance."""
        return f"QR {self.token!s:.8} — {self.seance}"

    @property
    def is_expired(self):
        """Retourne True si l'horodatage d'expiration du token est dépassé."""
        from django.utils import timezone
        return timezone.now() > self.expires_at

    @property
    def is_usable(self):
        """Retourne True uniquement si le token est à la fois actif (non désactivé) et non encore expiré."""
        return self.is_active and not self.is_expired


class QRScanRecord(models.Model):
    """
    Enregistrement persistant d'une présence étudiante validée via un scan QR.

    Rattaché à la Seance (et non à QRAttendanceToken) afin que les présences
    validées soient préservées même lorsque le professeur rafraîchit le token
    en cours de séance. La contrainte unique_together sur (seance, inscription)
    empêche le double enregistrement du même étudiant pour la même séance.

    Le drapeau is_suspicious est levé lorsque la distance GPS de l'étudiant
    dépasse DISTANCE_THRESHOLD_METERS ; la présence est tout de même
    enregistrée mais signalée à l'attention du professeur sur le tableau de bord.
    """

    seance = models.ForeignKey(
        "academic_sessions.Seance",
        on_delete=models.CASCADE,
        related_name="qr_scans",
    )
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="qr_scans",
        null=True,
        blank=True,
    )
    inscription = models.ForeignKey(
        "enrollments.Inscription",
        on_delete=models.SET_NULL,
        related_name="qr_scans",
        null=True,
        blank=True,
    )
    scanned_at = models.DateTimeField(auto_now_add=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    # Anti-fraude GPS : position de l'étudiant lors du scan
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    distance_meters = models.FloatField(null=True, blank=True)
    is_suspicious = models.BooleanField(default=False)

    class Meta:
        """Métadonnées Django : table dédiée et unicité (seance, inscription) anti-doublons."""

        db_table = "qr_scan_record"
        app_label = "absences"
        unique_together = (("seance", "inscription"),)

    def __str__(self):
        """Représentation lisible identifiant l'étudiant scanné et la date de la séance."""
        return f"Scan {self.student} — {self.seance.date_seance}"


class QRScanLog(models.Model):
    """
    Journal d'audit immuable pour chaque tentative de scan QR, qu'elle soit réussie ou refusée.

    Contrairement à QRScanRecord, qui ne stocke que les présences validées, ce
    modèle capture chaque tentative, y compris les scans refusés (token expiré,
    échec GPS, non inscrit, doublon, etc.) à des fins d'investigation de
    sécurité et de détection de fraude.

    Le champ qr_token_used stocke un hash SHA-256 de l'UUID brut du token
    plutôt que le token lui-même — cela empêche les attaques par rejeu si le
    journal est un jour exposé, tout en permettant la corrélation médico-légale.

    Ce modèle est en lecture seule : les permissions add/change/delete sont
    désactivées dans l'admin pour préserver l'intégrité de l'audit.
    """

    class GPSStatus(models.TextChoices):
        """État de la collecte GPS au moment du scan (accepté, refusé, indisponible, non requis)."""

        ACCEPTED = "accepted", "GPS accepté"
        REFUSED = "refused", "GPS refusé par l'étudiant"
        UNAVAILABLE = "unavailable", "GPS indisponible"
        NOT_REQUIRED = "not_required", "Vérification non activée"

    class ScanResult(models.TextChoices):
        """Résultat fonctionnel du scan : validé ou rejeté avec le motif précis."""
        VALIDATED = "validated", "Présence validée"
        REJECTED_GPS = "rejected_gps", "Refusé — pas de GPS"
        REJECTED_DISTANCE = "rejected_distance", "Refusé — hors zone"
        REJECTED_EXPIRED = "rejected_expired", "Refusé — QR expiré"
        REJECTED_NOT_ENROLLED = "rejected_not_enrolled", "Refusé — non inscrit"
        REJECTED_DUPLICATE = "rejected_duplicate", "Refusé — déjà scanné"
        REJECTED_LOCKED = "rejected_locked", "Refusé — séance verrouillée"
        REJECTED_INACTIVE = "rejected_inactive", "Refusé — QR inactif"

    etudiant = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="qr_scan_logs",
        null=True,
        blank=True,
    )
    seance = models.ForeignKey(
        "academic_sessions.Seance",
        on_delete=models.SET_NULL,
        related_name="qr_scan_logs",
        null=True,
        blank=True,
    )
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    distance_meters = models.FloatField(null=True, blank=True)
    gps_status = models.CharField(max_length=20, choices=GPSStatus.choices)
    scan_result = models.CharField(max_length=25, choices=ScanResult.choices)
    qr_token_used = models.CharField(max_length=255, blank=True, default="")
    user_agent = models.TextField(blank=True, default="")
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        """Métadonnées Django : tri chronologique inverse et index pour les requêtes d'audit."""

        db_table = "qr_scan_log"
        app_label = "absences"
        ordering = ["-timestamp"]
        indexes = [
            models.Index(fields=["seance", "etudiant", "-timestamp"]),
            models.Index(fields=["etudiant", "-timestamp"]),
            models.Index(fields=["scan_result"]),
        ]

    def __str__(self):
        """Représentation lisible identifiant l'étudiant, le résultat et l'horodatage."""
        return f"ScanLog {self.etudiant} — {self.scan_result} — {self.timestamp}"
