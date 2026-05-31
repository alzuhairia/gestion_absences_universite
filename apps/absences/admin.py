"""
Configuration de l'admin Django pour les modèles de l'application absences.

Enregistre tous les modèles liés aux absences auprès du site d'administration
Django et personnalise les affichages de liste, filtres, champs de recherche
et la protection en lecture seule au niveau des champs.

Modèles enregistrés :
  - Absence : enregistrement d'absence par inscription étudiante et séance.
  - Justification : document justificatif soumis par un étudiant.
  - QRAttendanceToken : token QR à durée limitée généré par les professeurs.
  - QRScanRecord : présence étudiante validée enregistrée via scan QR.
  - QRScanLog : journal d'audit immuable de chaque tentative de scan QR.

QRScanLog est enregistré en lecture seule : les permissions d'ajout, de
modification et de suppression sont toutes révoquées afin de préserver
l'intégrité de la piste d'audit.

Fait partie du système de gestion des absences UniAbsences.
"""
from django.contrib import admin

from .models import Absence, Justification, QRAttendanceToken, QRScanLog, QRScanRecord


@admin.register(Absence)
class AbsenceAdmin(admin.ModelAdmin):
    """
    Vue d'administration pour le modèle Absence.

    Fournit une vue liste compacte filtrée par statut de justification et type
    d'absence, avec chargement anticipé de l'Inscription liée pour éviter les
    requêtes N+1.
    """

    list_display = ("id_absence", "id_inscription", "type_absence", "statut")
    list_filter = ("statut", "type_absence")
    list_select_related = ("id_inscription",)


@admin.register(Justification)
class JustificationAdmin(admin.ModelAdmin):
    """
    Vue d'administration pour le modèle Justification.

    Affiche la clé primaire, l'absence liée et l'état d'approbation actuel.
    L'Absence liée est pré-chargée pour éviter les requêtes BDD répétées dans
    la vue liste.
    """

    list_display = ("id_justification", "id_absence", "state")
    list_select_related = ("id_absence",)


@admin.register(QRAttendanceToken)
class QRAttendanceTokenAdmin(admin.ModelAdmin):
    """
    Vue d'administration pour le modèle QRAttendanceToken.

    Tous les champs du token sont en lecture seule pour empêcher toute
    modification accidentelle via l'interface d'administration ; les tokens
    ne doivent être créés et gérés que via les vues de génération QR
    destinées aux professeurs.
    """

    list_display = ("token", "seance", "created_by", "expires_at", "is_active", "verify_location")
    list_filter = ("is_active", "verify_location")
    search_fields = ("token", "created_by__nom", "created_by__prenom")
    list_select_related = ("seance", "created_by")
    # Tous les champs du token sont en lecture seule : les tokens doivent être gérés via les vues de l'application.
    readonly_fields = ("token", "seance", "created_by", "expires_at", "is_active",
                       "verify_location", "latitude", "longitude", "created_at")
    ordering = ("-created_at",)


@admin.register(QRScanRecord)
class QRScanRecordAdmin(admin.ModelAdmin):
    """
    Vue d'administration pour le modèle QRScanRecord.

    Les enregistrements QRScanRecord sont écrits exclusivement par la vue
    qr_scan ; tous les champs sont donc en lecture seule dans l'admin afin
    d'éviter toute incohérence entre les enregistrements de présence et les
    données d'absence/justification sous-jacentes.
    """

    list_display = ("inscription", "seance", "scanned_at", "ip_address")
    search_fields = ("inscription__id_etudiant__nom", "inscription__id_etudiant__prenom")
    list_select_related = ("inscription", "seance")
    # Tous les champs des enregistrements de scan sont en lecture seule : les enregistrements sont créés uniquement par la vue qr_scan.
    readonly_fields = ("inscription", "seance", "scanned_at", "ip_address",
                       "latitude", "longitude", "distance_meters", "is_suspicious")
    ordering = ("-scanned_at",)


@admin.register(QRScanLog)
class QRScanLogAdmin(admin.ModelAdmin):
    """
    Vue d'administration en lecture seule pour le modèle d'audit QRScanLog.

    Chaque tentative de scan QR (réussie ou rejetée) est écrite ici par la
    vue qr_scan. Afin de préserver l'intégrité de la piste d'audit, toutes
    les permissions d'écriture (ajout, modification, suppression) sont
    désactivées en permanence.

    Le drill-down ``date_hierarchy`` sur ``timestamp`` permet aux
    administrateurs de naviguer rapidement dans le journal par jour, mois
    ou année.
    """

    list_display = ("etudiant", "seance", "ip_address", "gps_status", "scan_result", "timestamp")
    list_filter = ("gps_status", "scan_result", "timestamp")
    search_fields = ("etudiant__nom", "etudiant__prenom", "etudiant__email", "ip_address")
    list_select_related = ("etudiant", "seance")
    # Chaque colonne est en lecture seule : le journal d'audit ne doit jamais être altéré via l'admin.
    readonly_fields = ("etudiant", "seance", "ip_address", "latitude", "longitude",
                       "distance_meters", "gps_status", "scan_result", "qr_token_used",
                       "user_agent", "timestamp")
    ordering = ("-timestamp",)
    # Permet la navigation par drill-down temporel dans le journal d'audit.
    date_hierarchy = "timestamp"

    def has_add_permission(self, request):
        """Empêche la création manuelle d'entrées du journal d'audit via l'admin."""
        return False

    def has_change_permission(self, request, obj=None):
        """Empêche la modification des entrées du journal d'audit via l'admin."""
        return False

    def has_delete_permission(self, request, obj=None):
        """Empêche la suppression des entrées du journal d'audit afin de préserver la piste d'audit."""
        return False
