"""
Utilitaires internes du système QR code.

Fonctions :
  - Calcul GPS (Haversine) et validation de coordonnées
  - Génération du QR code en data-URI base64
  - Hachage SHA-256 du token QR pour les logs d'audit
  - Journalisation des tentatives de scan (QRScanLog)

Ces helpers sont importés par qr_professor.py et qr_student.py.
"""
import base64
import hashlib
import io
import math

import qrcode

from apps.audits.utils import get_client_ip

from ..models import QRScanLog


# ── GPS ───────────────────────────────────────────────────────────────────────


def _haversine(lat1, lon1, lat2, lon2):
    """Distance en mètres entre deux points GPS (formule de Haversine)."""
    R = 6_371_000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _is_valid_coordinate(coord):
    """
    False si coord est None ou proche de Null Island (0,0).
    Empêche le spoofing GPS avec des coordonnées nulles.
    """
    if coord is None:
        return False
    return abs(coord) >= 0.01


def _get_establishment_gps():
    """Retourne (latitude, longitude, radius) depuis SystemSettings."""
    from apps.dashboard.models import SystemSettings
    s = SystemSettings.get_settings()
    return s.gps_latitude, s.gps_longitude, s.gps_radius_meters


# ── QR ───────────────────────────────────────────────────────────────────────


def _generate_qr_data_uri(url):
    """Génère un QR code PNG encodé en data-URI base64 (pas de fichier disque)."""
    qr = qrcode.QRCode(version=1, box_size=10, border=4)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, "PNG")
    buf.seek(0)
    return f"data:image/png;base64,{base64.b64encode(buf.getvalue()).decode()}"


def _hash_qr_token(raw_token):
    """
    Retourne sha256:<hex> du token QR, ou '' si absent.
    Le log d'audit ne stocke jamais le token brut (replay attack).
    """
    if not raw_token:
        return ""
    digest = hashlib.sha256(str(raw_token).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


# ── Journalisation ────────────────────────────────────────────────────────────


def _log_scan_attempt(request, seance, qr_token, gps_status, scan_result,
                      latitude=None, longitude=None, distance=None):
    """Journalise chaque tentative de scan QR (token haché SHA-256)."""
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
