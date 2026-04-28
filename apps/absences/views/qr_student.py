"""
Scan QR code côté étudiant.

Fonctionnalité :
  - qr_scan : l'étudiant scanne le QR → confirmation (GET) → enregistrement (POST)

Contrôles de sécurité :
  1. Token actif et non expiré
  2. Séance non verrouillée
  3. Étudiant inscrit au cours
  4. Pas de double-scan (select_for_update)
  5. GPS : distance vérifiée si verify_location=True (formule de Haversine)

ANTI-FRAUDE :
  - Chaque tentative est loguée dans QRScanLog (token haché SHA-256)
  - Coordonnées nulles (Null Island) rejetées comme spoofing
"""
import logging

from django.contrib.auth.decorators import login_required
from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_http_methods

from ..models import QRAttendanceToken, QRScanLog, QRScanRecord
from .qr_utils import (
    _get_establishment_gps,
    _haversine,
    _is_valid_coordinate,
    _log_scan_attempt,
)
from apps.audits.utils import get_client_ip
from apps.dashboard.decorators import student_required
from apps.enrollments.models import Inscription

logger = logging.getLogger(__name__)


@login_required
@student_required
@require_http_methods(["GET", "POST"])
def qr_scan(request, token):
    """
    L'étudiant scanne le QR → page de confirmation (GET) → enregistrement (POST).
    """
    qr_token = get_object_or_404(QRAttendanceToken, token=token)
    seance = qr_token.seance
    course = seance.id_cours
    error_ctx = {"course": course, "seance": seance}

    if not qr_token.is_active:
        _log_scan_attempt(request, seance, qr_token,
                          QRScanLog.GPSStatus.NOT_REQUIRED, QRScanLog.ScanResult.REJECTED_INACTIVE)
        return render(request, "absences/qr_scan_result.html", {
            **error_ctx, "scan_status": "error",
            "message": "Ce QR code n'est plus actif.",
        })

    if qr_token.is_expired:
        _log_scan_attempt(request, seance, qr_token,
                          QRScanLog.GPSStatus.NOT_REQUIRED, QRScanLog.ScanResult.REJECTED_EXPIRED)
        return render(request, "absences/qr_scan_result.html", {
            **error_ctx, "scan_status": "expired",
            "message": "Ce QR code a expiré. Scannez le nouveau QR affiché par le professeur.",
        })

    if seance.validated:
        _log_scan_attempt(request, seance, qr_token,
                          QRScanLog.GPSStatus.NOT_REQUIRED, QRScanLog.ScanResult.REJECTED_LOCKED)
        return render(request, "absences/qr_scan_result.html", {
            **error_ctx, "scan_status": "error",
            "message": "Cette séance est déjà validée et verrouillée.",
        })

    inscription = Inscription.objects.filter(
        id_etudiant=request.user,
        id_cours=course,
        id_annee=seance.id_annee,
        status=Inscription.Status.EN_COURS,
    ).first()

    if not inscription:
        _log_scan_attempt(request, seance, qr_token,
                          QRScanLog.GPSStatus.NOT_REQUIRED, QRScanLog.ScanResult.REJECTED_NOT_ENROLLED)
        return render(request, "absences/qr_scan_result.html", {
            **error_ctx, "scan_status": "error",
            "message": "Vous n'êtes pas inscrit(e) à ce cours.",
        })

    existing = QRScanRecord.objects.filter(seance=seance, inscription=inscription).first()
    if existing:
        _log_scan_attempt(request, seance, qr_token,
                          QRScanLog.GPSStatus.NOT_REQUIRED, QRScanLog.ScanResult.REJECTED_DUPLICATE)
        return render(request, "absences/qr_scan_result.html", {
            **error_ctx, "scan_status": "duplicate",
            "message": "Votre présence a déjà été enregistrée.",
            "scanned_at": existing.scanned_at,
        })

    gps_required = qr_token.verify_location
    etab_lat, etab_lng, etab_radius = _get_establishment_gps()

    if request.method == "GET":
        return render(request, "absences/qr_scan.html", {
            "qr_token": qr_token,
            "course": course,
            "seance": seance,
            "gps_required": gps_required,
        })

    # --- POST : enregistrement de la présence ---
    stu_lat_raw = request.POST.get("latitude", "").strip()
    stu_lng_raw = request.POST.get("longitude", "").strip()
    gps_status_val = request.POST.get("gps_status", "")

    stu_lat_f = stu_lng_f = distance = None
    try:
        if stu_lat_raw and stu_lng_raw:
            stu_lat_f = float(stu_lat_raw)
            stu_lng_f = float(stu_lng_raw)
    except (ValueError, TypeError):
        stu_lat_f = stu_lng_f = None

    if gps_required:
        if gps_status_val == "refused":
            _log_scan_attempt(request, seance, qr_token,
                              QRScanLog.GPSStatus.REFUSED, QRScanLog.ScanResult.REJECTED_GPS)
            return render(request, "absences/qr_scan_result.html", {
                **error_ctx, "scan_status": "error",
                "message": "La localisation est obligatoire pour cette séance.",
            })

        if not _is_valid_coordinate(stu_lat_f) or not _is_valid_coordinate(stu_lng_f):
            _log_scan_attempt(request, seance, qr_token,
                              QRScanLog.GPSStatus.UNAVAILABLE, QRScanLog.ScanResult.REJECTED_GPS)
            return render(request, "absences/qr_scan_result.html", {
                **error_ctx, "scan_status": "error",
                "message": "Impossible d'obtenir votre position. Réessayez ou contactez le professeur.",
            })

        if _is_valid_coordinate(etab_lat) and _is_valid_coordinate(etab_lng):
            distance = _haversine(etab_lat, etab_lng, stu_lat_f, stu_lng_f)
            if distance > etab_radius:
                assert distance is not None
                _log_scan_attempt(request, seance, qr_token,
                                  QRScanLog.GPSStatus.ACCEPTED, QRScanLog.ScanResult.REJECTED_DISTANCE,
                                  stu_lat_f, stu_lng_f, distance)
                return render(request, "absences/qr_scan_result.html", {
                    **error_ctx, "scan_status": "error",
                    "message": f"Vous n'êtes pas dans la zone autorisée. Distance : {distance:.0f} m (max : {etab_radius} m).",
                    "distance": round(distance, 0),
                    "radius": etab_radius,
                })
        elif qr_token.latitude is not None and qr_token.longitude is not None:
            distance = _haversine(qr_token.latitude, qr_token.longitude, stu_lat_f, stu_lng_f)
            if distance > QRAttendanceToken.DISTANCE_THRESHOLD_METERS:
                assert distance is not None
                _log_scan_attempt(request, seance, qr_token,
                                  QRScanLog.GPSStatus.ACCEPTED, QRScanLog.ScanResult.REJECTED_DISTANCE,
                                  stu_lat_f, stu_lng_f, distance)
                return render(request, "absences/qr_scan_result.html", {
                    **error_ctx, "scan_status": "error",
                    "message": f"Vous n'êtes pas dans la zone autorisée. Distance : {distance:.0f} m.",
                    "distance": round(distance, 0),
                    "radius": QRAttendanceToken.DISTANCE_THRESHOLD_METERS,
                })
        else:
            logger.warning("GPS vérification activée mais aucune coordonnée de référence (séance %s)", seance.id_seance)
            return render(request, "absences/qr_scan_result.html", {
                **error_ctx, "scan_status": "error",
                "message": "Erreur de configuration GPS. Contactez le secrétariat ou le professeur.",
            })

    scan_kwargs = {
        "seance": seance,
        "student": request.user,
        "inscription": inscription,
        "ip_address": get_client_ip(request),
    }
    is_suspicious = False
    if stu_lat_f is not None and stu_lng_f is not None:
        scan_kwargs["latitude"] = stu_lat_f
        scan_kwargs["longitude"] = stu_lng_f
        if distance is None and qr_token.latitude is not None:
            distance = _haversine(qr_token.latitude, qr_token.longitude, stu_lat_f, stu_lng_f)
        if distance is not None:
            assert distance is not None
            scan_kwargs["distance_meters"] = round(distance, 1)
            is_suspicious = distance > QRAttendanceToken.DISTANCE_THRESHOLD_METERS
            scan_kwargs["is_suspicious"] = is_suspicious

    try:
        with transaction.atomic():
            dup = (
                QRScanRecord.objects
                .select_for_update()
                .filter(seance=seance, inscription=inscription)
                .first()
            )
            if dup:
                _log_scan_attempt(request, seance, qr_token,
                                  QRScanLog.GPSStatus.NOT_REQUIRED, QRScanLog.ScanResult.REJECTED_DUPLICATE)
                return render(request, "absences/qr_scan_result.html", {
                    **error_ctx, "scan_status": "duplicate",
                    "message": "Votre présence a déjà été enregistrée.",
                    "scanned_at": dup.scanned_at,
                })
            QRScanRecord.objects.create(**scan_kwargs)
    except IntegrityError:
        return render(request, "absences/qr_scan_result.html", {
            **error_ctx, "scan_status": "duplicate",
            "message": "Votre présence a déjà été enregistrée.",
        })

    gps_log_status = (
        QRScanLog.GPSStatus.ACCEPTED if stu_lat_f is not None
        else QRScanLog.GPSStatus.NOT_REQUIRED
    )
    _log_scan_attempt(request, seance, qr_token, gps_log_status,
                      QRScanLog.ScanResult.VALIDATED, stu_lat_f, stu_lng_f, distance)

    result_ctx = {**error_ctx, "scan_status": "success"}
    if is_suspicious:
        assert distance is not None
        result_ctx["message"] = "Présence enregistrée, mais votre position est éloignée de la salle."
        result_ctx["distance"] = round(distance, 0)
    else:
        result_ctx["message"] = "Présence enregistrée avec succès !"

    return render(request, "absences/qr_scan_result.html", result_ctx)
