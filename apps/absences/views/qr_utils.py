"""
Internal utilities for the QR code attendance system.

Functions:
  - GPS calculations (Haversine) and coordinate validation
  - QR code generation as base64 data URI
  - SHA-256 hashing of QR tokens for audit logs
  - Logging of scan attempts (QRScanLog)

These helpers are imported by qr_professor.py and qr_student.py.

Part of the UniAbsences attendance system.
"""
import hashlib
import math

from apps.audits.utils import get_client_ip
from apps.utils import generate_qr_data_uri as _generate_qr_data_uri  # noqa: F401

from ..models import QRScanLog


# ── GPS ───────────────────────────────────────────────────────────────────────


def _haversine(lat1, lon1, lat2, lon2):
    """
    Calculate the distance in meters between two GPS points using the Haversine formula.
    
    Parameters:
        lat1 (float): Latitude of the first point in degrees.
        lon1 (float): Longitude of the first point in degrees.
        lat2 (float): Latitude of the second point in degrees.
        lon2 (float): Longitude of the second point in degrees.
    
    Returns:
        float: Distance in meters.
    """
    R = 6_371_000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _is_valid_coordinate(coord):
    """
    Check if a coordinate is valid (not None and not near Null Island).
    
    Prevents GPS spoofing with null coordinates.
    
    Parameters:
        coord (float or None): The coordinate to validate.
    
    Returns:
        bool: True if valid, False otherwise.
    """
    if coord is None:
        return False
    return abs(coord) >= 0.01


def _get_establishment_gps():
    """
    Retrieve GPS settings (latitude, longitude, radius) from SystemSettings.
    
    Returns:
        tuple: (latitude, longitude, radius_meters)
    """
    from apps.dashboard.models import SystemSettings
    s = SystemSettings.get_settings()
    return s.gps_latitude, s.gps_longitude, s.gps_radius_meters


def _hash_qr_token(raw_token):
    """
    Return a SHA-256 hash of the QR token, or empty string if absent.
    
    Audit logs never store raw tokens to prevent replay attacks.
    
    Parameters:
        raw_token (str or None): The raw QR token.
    
    Returns:
        str: Hashed token in format 'sha256:<hex>' or empty string.
    """
    if not raw_token:
        return ""
    digest = hashlib.sha256(str(raw_token).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


# ── Logging ───────────────────────────────────────────────────────────────────


def _log_scan_attempt(request, seance, qr_token, gps_status, scan_result,
                      latitude=None, longitude=None, distance=None):
    """
    Log each QR scan attempt with hashed token for audit purposes.
    
    Parameters:
        request: The HTTP request object.
        seance: The Seance model instance.
        qr_token: The QRAttendanceToken instance or None.
        gps_status (str): GPS validation status.
        scan_result (str): Result of the scan attempt.
        latitude (float, optional): Latitude from the scan.
        longitude (float, optional): Longitude from the scan.
        distance (float, optional): Distance in meters from establishment.
    """
    QRScanLog.objects.create(
        etudiant=request.user,
        seance=seance,
        ip_address=get_client_ip(request),
        latitude=latitude,
        longitude=longitude,
        distance_meters=round(distance, 1) if distance is not None else None,
        gps_status=gps_status,
        scan_result=scan_result,
        qr_token_used=_hash_qr_token(qr_token.token if qr_token else None),
        user_agent=request.META.get("HTTP_USER_AGENT", "")[:500],
    )
