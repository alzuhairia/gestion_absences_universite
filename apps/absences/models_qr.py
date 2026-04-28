"""
Modèles QR code : token de présence, scan validé et log d'audit.
"""
import uuid

from django.conf import settings
from django.db import models


class QRAttendanceToken(models.Model):
    """
    Short-lived token embedded in a QR code for attendance scanning.
    One Seance may have several tokens over time (professor can refresh).
    Only the latest active token accepts scans.
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
    # GPS anti-fraud: professor's location when generating the QR
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)

    class Meta:
        db_table = "qr_attendance_token"
        app_label = "absences"
        ordering = ["-created_at"]

    def __str__(self):
        return f"QR {self.token!s:.8} — {self.seance}"

    @property
    def is_expired(self):
        from django.utils import timezone
        return timezone.now() > self.expires_at

    @property
    def is_usable(self):
        return self.is_active and not self.is_expired


class QRScanRecord(models.Model):
    """
    Records a student's QR scan for a given seance.
    Linked to seance (not token) so that scans survive token refreshes.
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
    # GPS anti-fraud: student's location when scanning
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    distance_meters = models.FloatField(null=True, blank=True)
    is_suspicious = models.BooleanField(default=False)

    class Meta:
        db_table = "qr_scan_record"
        app_label = "absences"
        unique_together = (("seance", "inscription"),)

    def __str__(self):
        return f"Scan {self.student} — {self.seance.date_seance}"


class QRScanLog(models.Model):
    """
    Audit log for EVERY QR scan attempt (successful or failed).
    Unlike QRScanRecord (which only stores validated presences),
    this logs all attempts for security auditing.
    """

    class GPSStatus(models.TextChoices):
        ACCEPTED = "accepted", "GPS accepté"
        REFUSED = "refused", "GPS refusé par l'étudiant"
        UNAVAILABLE = "unavailable", "GPS indisponible"
        NOT_REQUIRED = "not_required", "Vérification non activée"

    class ScanResult(models.TextChoices):
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
        db_table = "qr_scan_log"
        app_label = "absences"
        ordering = ["-timestamp"]
        indexes = [
            models.Index(fields=["seance", "etudiant", "-timestamp"]),
            models.Index(fields=["etudiant", "-timestamp"]),
            models.Index(fields=["scan_result"]),
        ]

    def __str__(self):
        return f"ScanLog {self.etudiant} — {self.scan_result} — {self.timestamp}"
