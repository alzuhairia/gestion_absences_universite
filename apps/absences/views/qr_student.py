"""
Student-side QR code scanning — apps/absences/views/qr_student.py

``qr_scan``
    Handles the full student QR attendance workflow in two phases:

    GET  — Confirmation page.  The student sees the course / session info and,
           if GPS verification is required, the browser requests the device
           location before the form can be submitted.

    POST — Attendance recording.  The view runs all security checks, records
           the attendance in ``QRScanRecord``, and logs the attempt to
           ``QRScanLog`` regardless of the outcome.

Security checks (in order)
---------------------------
1. Token is active (``QRAttendanceToken.is_active``).
2. Token has not expired (``QRAttendanceToken.is_expired``).
3. Session is not locked (``Seance.validated``).
4. Student is enrolled in the course for the current academic year.
5. No duplicate scan for this session (``QRScanRecord`` unique constraint,
   enforced both in the application layer and at the DB level via
   ``select_for_update()``).
6. GPS distance check (when ``verify_location=True`` on the token):
   - Student coordinates must be valid (not ``None`` and not near Null Island).
   - Distance must be within the allowed radius using either the establishment
     GPS from ``SystemSettings`` or the professor's token coordinates as the
     reference point.

Anti-fraud measures
-------------------
- Every scan attempt — successful or not — is written to ``QRScanLog`` with a
  SHA-256 hash of the token (raw token is never stored in logs).
- Null-Island coordinates (lat/lng ≈ 0.0) are explicitly rejected to prevent
  trivial GPS spoofing.
- The ``QRScanRecord`` has a database-level unique constraint on
  ``(seance, inscription)``; an ``IntegrityError`` on concurrent duplicate
  submissions is caught and surfaced as a "duplicate" result.

Part of the UniAbsences attendance system.
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
    Handle the student QR code scan: display confirmation (GET) or record attendance (POST).

    GET
        Render ``absences/qr_scan.html`` with course / session info and the
        ``gps_required`` flag so the template can request device location before
        form submission.

    POST
        Run all security and GPS checks, record attendance in ``QRScanRecord``,
        log the attempt in ``QRScanLog``, and render ``absences/qr_scan_result.html``
        with a status of ``"success"``, ``"duplicate"``, ``"expired"``, or
        ``"error"``.

    GPS verification flow (when ``qr_token.verify_location`` is ``True``)
    -----------------------------------------------------------------------
    Priority 1: Use the establishment GPS from ``SystemSettings`` as the
                reference point when both lat/lng are configured.
    Priority 2: Fall back to the professor's token coordinates.
    Fallback: Return a configuration error — GPS enforcement with no reference
              point is not possible.

    Suspicious scans
    ----------------
    When GPS is not required but the student's coordinates are still submitted,
    the distance from the token's reference point is calculated.  If it exceeds
    ``QRAttendanceToken.DISTANCE_THRESHOLD_METERS``, the record is flagged as
    suspicious (``QRScanRecord.is_suspicious = True``) and the student is warned.

    Parameters
    ----------
    request : HttpRequest
        The incoming HTTP request.
    token : UUID
        The ``QRAttendanceToken.token`` value from the URL (embedded in the QR).

    Returns
    -------
    HttpResponse
        Rendered ``qr_scan.html`` (GET) or ``qr_scan_result.html`` (POST).

    Raises
    ------
    Http404
        When no token with the given UUID exists.
    """
    qr_token = get_object_or_404(QRAttendanceToken, token=token)
    seance = qr_token.seance
    course = seance.id_cours
    # Shared context dict for all early-return error renders.
    error_ctx = {"course": course, "seance": seance}

    # Check 1: Token must be active (not manually deactivated by the professor).
    if not qr_token.is_active:
        _log_scan_attempt(request, seance, qr_token,
                          QRScanLog.GPSStatus.NOT_REQUIRED, QRScanLog.ScanResult.REJECTED_INACTIVE)
        return render(request, "absences/qr_scan_result.html", {
            **error_ctx, "scan_status": "error",
            "message": "This QR code is no longer active.",
        })

    # Check 2: Token must not be expired (time-based expiry).
    if qr_token.is_expired:
        _log_scan_attempt(request, seance, qr_token,
                          QRScanLog.GPSStatus.NOT_REQUIRED, QRScanLog.ScanResult.REJECTED_EXPIRED)
        return render(request, "absences/qr_scan_result.html", {
            **error_ctx, "scan_status": "expired",
            "message": "This QR code has expired. Scan the new QR displayed by the professor.",
        })

    # Check 3: Session must not be locked (finalized or manually validated).
    if seance.validated:
        _log_scan_attempt(request, seance, qr_token,
                          QRScanLog.GPSStatus.NOT_REQUIRED, QRScanLog.ScanResult.REJECTED_LOCKED)
        return render(request, "absences/qr_scan_result.html", {
            **error_ctx, "scan_status": "error",
            "message": "This session is already validated and locked.",
        })

    # Check 4: Student must be actively enrolled in this course for this year.
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
            "message": "You are not enrolled in this course.",
        })

    # Check 5 (pre-lock): Quick duplicate check before entering the transaction.
    # The definitive check happens inside the transaction to handle race conditions.
    existing = QRScanRecord.objects.filter(seance=seance, inscription=inscription).first()
    if existing:
        _log_scan_attempt(request, seance, qr_token,
                          QRScanLog.GPSStatus.NOT_REQUIRED, QRScanLog.ScanResult.REJECTED_DUPLICATE)
        return render(request, "absences/qr_scan_result.html", {
            **error_ctx, "scan_status": "duplicate",
            "message": "Your attendance has already been recorded.",
            "scanned_at": existing.scanned_at,
        })

    gps_required = qr_token.verify_location
    etab_lat, etab_lng, etab_radius = _get_establishment_gps()

    # GET: Render confirmation page; no attendance is recorded yet.
    if request.method == "GET":
        return render(request, "absences/qr_scan.html", {
            "qr_token": qr_token,
            "course": course,
            "seance": seance,
            "gps_required": gps_required,
        })

    # --- POST: Record attendance ---

    # Parse the GPS coordinates submitted by the student's browser.
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

    # GPS enforcement block — only executed when verify_location is enabled.
    if gps_required:
        if gps_status_val == "refused":
            # Student explicitly denied location access — cannot proceed.
            _log_scan_attempt(request, seance, qr_token,
                              QRScanLog.GPSStatus.REFUSED, QRScanLog.ScanResult.REJECTED_GPS)
            return render(request, "absences/qr_scan_result.html", {
                **error_ctx, "scan_status": "error",
                "message": "Location is required for this session.",
            })

        # Null-Island check — coordinates at or near (0,0) are likely spoofed.
        if not _is_valid_coordinate(stu_lat_f) or not _is_valid_coordinate(stu_lng_f):
            _log_scan_attempt(request, seance, qr_token,
                              QRScanLog.GPSStatus.UNAVAILABLE, QRScanLog.ScanResult.REJECTED_GPS)
            return render(request, "absences/qr_scan_result.html", {
                **error_ctx, "scan_status": "error",
                "message": "Unable to get your position. Try again or contact the professor.",
            })

        # Distance check — prefer the establishment GPS over the token's professor GPS.
        if _is_valid_coordinate(etab_lat) and _is_valid_coordinate(etab_lng):
            # Use the establishment-wide GPS reference configured in SystemSettings.
            distance = _haversine(etab_lat, etab_lng, stu_lat_f, stu_lng_f)
            if distance > etab_radius:
                assert distance is not None
                _log_scan_attempt(request, seance, qr_token,
                                  QRScanLog.GPSStatus.ACCEPTED, QRScanLog.ScanResult.REJECTED_DISTANCE,
                                  stu_lat_f, stu_lng_f, distance)
                return render(request, "absences/qr_scan_result.html", {
                    **error_ctx, "scan_status": "error",
                    "message": f"You are not in the authorized zone. Distance: {distance:.0f} m (max: {etab_radius} m).",
                    "distance": round(distance, 0),
                    "radius": etab_radius,
                })
        elif qr_token.latitude is not None and qr_token.longitude is not None:
            # Fall back to the professor's position stored on the token.
            distance = _haversine(qr_token.latitude, qr_token.longitude, stu_lat_f, stu_lng_f)
            if distance > QRAttendanceToken.DISTANCE_THRESHOLD_METERS:
                assert distance is not None
                _log_scan_attempt(request, seance, qr_token,
                                  QRScanLog.GPSStatus.ACCEPTED, QRScanLog.ScanResult.REJECTED_DISTANCE,
                                  stu_lat_f, stu_lng_f, distance)
                return render(request, "absences/qr_scan_result.html", {
                    **error_ctx, "scan_status": "error",
                    "message": f"You are not in the authorized zone. Distance: {distance:.0f} m.",
                    "distance": round(distance, 0),
                    "radius": QRAttendanceToken.DISTANCE_THRESHOLD_METERS,
                })
        else:
            # GPS is required but neither the establishment nor the token has valid
            # reference coordinates — this is a configuration error.
            logger.warning("GPS verification enabled but no reference coordinates (session %s)", seance.id_seance)
            return render(request, "absences/qr_scan_result.html", {
                **error_ctx, "scan_status": "error",
                "message": "GPS configuration error. Contact the secretary or professor.",
            })

    # Build the kwargs for the QRScanRecord.
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

        # Calculate distance from token origin even when GPS is not required,
        # so the professor can spot anomalously distant scans on the dashboard.
        if distance is None and qr_token.latitude is not None:
            distance = _haversine(qr_token.latitude, qr_token.longitude, stu_lat_f, stu_lng_f)
        if distance is not None:
            assert distance is not None
            scan_kwargs["distance_meters"] = round(distance, 1)
            # Flag as suspicious if student is beyond the threshold even when
            # GPS enforcement is not enabled (non-blocking, informational).
            is_suspicious = distance > QRAttendanceToken.DISTANCE_THRESHOLD_METERS
            scan_kwargs["is_suspicious"] = is_suspicious

    # Definitive duplicate check inside the transaction — handles the race
    # condition where two requests arrive at the same time for the same student.
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
                    "message": "Your attendance has already been recorded.",
                    "scanned_at": dup.scanned_at,
                })
            # All checks passed — record the attendance.
            QRScanRecord.objects.create(**scan_kwargs)
    except IntegrityError:
        # DB-level unique constraint caught a concurrent insert — treat as duplicate.
        return render(request, "absences/qr_scan_result.html", {
            **error_ctx, "scan_status": "duplicate",
            "message": "Your attendance has already been recorded.",
        })

    # Log the successful scan (GPS status reflects whether coordinates were provided).
    gps_log_status = (
        QRScanLog.GPSStatus.ACCEPTED if stu_lat_f is not None
        else QRScanLog.GPSStatus.NOT_REQUIRED
    )
    _log_scan_attempt(request, seance, qr_token, gps_log_status,
                      QRScanLog.ScanResult.VALIDATED, stu_lat_f, stu_lng_f, distance)

    # Build the success context — warn the student if their position was flagged.
    result_ctx = {**error_ctx, "scan_status": "success"}
    if is_suspicious:
        assert distance is not None
        result_ctx["message"] = "Attendance recorded, but your position is far from the classroom."
        result_ctx["distance"] = round(distance, 0)
    else:
        result_ctx["message"] = "Attendance recorded successfully!"

    return render(request, "absences/qr_scan_result.html", result_ctx)
