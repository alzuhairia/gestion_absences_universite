from django.contrib import admin

from .models import Absence, Justification, QRAttendanceToken, QRScanLog, QRScanRecord


@admin.register(Absence)
class AbsenceAdmin(admin.ModelAdmin):
    list_display = ("id_absence", "id_inscription", "type_absence", "statut")
    list_filter = ("statut", "type_absence")
    list_select_related = ("id_inscription",)


@admin.register(Justification)
class JustificationAdmin(admin.ModelAdmin):
    list_display = ("id_justification", "id_absence", "state")
    list_select_related = ("id_absence",)


@admin.register(QRAttendanceToken)
class QRAttendanceTokenAdmin(admin.ModelAdmin):
    list_display = ("token", "seance", "created_by", "expires_at", "is_active", "verify_location")
    list_filter = ("is_active", "verify_location")
    search_fields = ("token", "created_by__nom", "created_by__prenom")
    list_select_related = ("seance", "created_by")
    readonly_fields = ("token", "seance", "created_by", "expires_at", "is_active",
                       "verify_location", "latitude", "longitude", "created_at")
    ordering = ("-created_at",)


@admin.register(QRScanRecord)
class QRScanRecordAdmin(admin.ModelAdmin):
    list_display = ("inscription", "seance", "scanned_at", "ip_address")
    search_fields = ("inscription__id_etudiant__nom", "inscription__id_etudiant__prenom")
    list_select_related = ("inscription", "seance")
    readonly_fields = ("inscription", "seance", "scanned_at", "ip_address",
                       "latitude", "longitude", "distance_meters", "is_suspicious")
    ordering = ("-scanned_at",)


@admin.register(QRScanLog)
class QRScanLogAdmin(admin.ModelAdmin):
    list_display = ("etudiant", "seance", "ip_address", "gps_status", "scan_result", "timestamp")
    list_filter = ("gps_status", "scan_result", "timestamp")
    search_fields = ("etudiant__nom", "etudiant__prenom", "etudiant__email", "ip_address")
    list_select_related = ("etudiant", "seance")
    readonly_fields = ("etudiant", "seance", "ip_address", "latitude", "longitude",
                       "distance_meters", "gps_status", "scan_result", "qr_token_used",
                       "user_agent", "timestamp")
    ordering = ("-timestamp",)
    date_hierarchy = "timestamp"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
