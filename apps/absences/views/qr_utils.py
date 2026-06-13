"""
Utilitaires internes pour le système de présence par QR code.

Fonctions :
  - Calculs GPS (Haversine) et validation des coordonnées
  - Génération de QR code en data URI base64
  - Hashage SHA-256 des tokens QR pour les journaux d'audit
  - Journalisation des tentatives de scan (QRScanLog)

Ces helpers sont importés par qr_professor.py et qr_student.py.

Fait partie du système de présence UniAbsences.
"""
import hashlib
import math

from apps.audits.utils import get_client_ip
from apps.utils import generate_qr_data_uri as _generate_qr_data_uri  # noqa: F401

from ..models import QRScanLog


# ── GPS ───────────────────────────────────────────────────────────────────────


def _haversine(lat1, lon1, lat2, lon2):
    """
    Calcule la distance en mètres entre deux points GPS via la formule de Haversine.

    Paramètres :
        lat1 (float) : latitude du premier point, en degrés.
        lon1 (float) : longitude du premier point, en degrés.
        lat2 (float) : latitude du second point, en degrés.
        lon2 (float) : longitude du second point, en degrés.

    Retour :
        float : distance en mètres.
    """
    R = 6_371_000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _is_valid_coordinate(coord):
    """
    Vérifie qu'une coordonnée est valide (non None et non proche de Null Island).

    Empêche l'usurpation GPS avec des coordonnées nulles.

    Paramètres :
        coord (float ou None) : la coordonnée à valider.

    Retour :
        bool : True si valide, False sinon.
    """
    if coord is None:
        return False
    return abs(coord) >= 0.01


def _get_establishment_gps():
    """
    Récupère les paramètres GPS (latitude, longitude, rayon) depuis SystemSettings.

    Retour :
        tuple : (latitude, longitude, rayon_metres)
    """
    from apps.dashboard.models import SystemSettings
    s = SystemSettings.get_settings()
    return s.gps_latitude, s.gps_longitude, s.gps_radius_meters


def _hash_qr_token(raw_token):
    """
    Retourne un hash SHA-256 du token QR, ou une chaîne vide si absent.

    Les journaux d'audit ne stockent jamais les tokens bruts afin d'empêcher
    les attaques par rejeu.

    Paramètres :
        raw_token (str ou None) : le token QR brut.

    Retour :
        str : token haché au format 'sha256:<hex>' ou chaîne vide.
    """
    if not raw_token:
        return ""
    digest = hashlib.sha256(str(raw_token).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


# ── Journalisation ────────────────────────────────────────────────────────────


def _log_scan_attempt(request, seance, qr_token, gps_status, scan_result,
                      latitude=None, longitude=None, distance=None):
    """
    Journalise chaque tentative de scan QR avec le token haché à des fins d'audit.

    Paramètres :
        request : l'objet de requête HTTP.
        seance : l'instance du modèle Seance.
        qr_token : l'instance QRAttendanceToken ou None.
        gps_status (str) : statut de validation GPS.
        scan_result (str) : résultat de la tentative de scan.
        latitude (float, optionnel) : latitude relevée lors du scan.
        longitude (float, optionnel) : longitude relevée lors du scan.
        distance (float, optionnel) : distance en mètres par rapport à l'établissement.
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
