"""
FICHIER : apps/absences/anomaly.py
RESPONSABILITE : Détection d'anomalies de présence (couche détective, NON bloquante)
FONCTIONNALITES PRINCIPALES :
  - evaluate_scan_risk(...) : calcule un score de risque + des drapeaux explicables
    à partir de signaux déjà collectés (appareil, IP, géo-vélocité, précision GPS).
PRINCIPE :
  - Un appareil APPROVED + GPS OK n'est JAMAIS bloqué par une anomalie : on signale
    et on audite, sans créer de faux positifs empêchant un étudiant légitime de pointer.
  - Le blocage strict reste réservé aux appareils inconnus/PENDING/REVOKED (dans qr_scan).
SIGNAUX :
  - multi_account_device : un même appareil (hash) rattaché à ≥ 2 comptes distincts.
  - geo_velocity        : déplacement physiquement impossible depuis le dernier scan.
  - new_ip             : adresse IP jamais vue pour ce compte.
  - low_gps_accuracy   : précision GPS annoncée trop faible pour être fiable.
  - new_device         : appareil enrôlé très récemment (première utilisation).
"""

import math

from django.utils import timezone

# --- Drapeaux (valeurs stables : stockées en base et affichées dans l'UI) ---
FLAG_MULTI_ACCOUNT_DEVICE = "multi_account_device"
FLAG_GEO_VELOCITY = "geo_velocity"
FLAG_NEW_IP = "new_ip"
FLAG_LOW_GPS_ACCURACY = "low_gps_accuracy"
FLAG_NEW_DEVICE = "new_device"

#: Poids de chaque drapeau dans le score de risque (0–100, plafonné).
FLAG_WEIGHTS = {
    FLAG_MULTI_ACCOUNT_DEVICE: 50,
    FLAG_GEO_VELOCITY: 40,
    FLAG_NEW_IP: 15,
    FLAG_LOW_GPS_ACCURACY: 10,
    FLAG_NEW_DEVICE: 10,
}

#: Libellés humains (pour l'UI prof/secrétariat).
FLAG_LABELS = {
    FLAG_MULTI_ACCOUNT_DEVICE: "Même appareil utilisé par plusieurs comptes",
    FLAG_GEO_VELOCITY: "Déplacement incohérent depuis le dernier scan",
    FLAG_NEW_IP: "Nouvelle adresse IP",
    FLAG_LOW_GPS_ACCURACY: "Précision GPS faible",
    FLAG_NEW_DEVICE: "Appareil récemment enrôlé",
}

#: Un scan est marqué « suspect » au-delà de ce score.
SUSPICIOUS_THRESHOLD = 30
#: Un appareil est « récent » s'il a été créé il y a moins de N heures.
NEW_DEVICE_MAX_AGE_HOURS = 24


def flag_label(flag):
    return FLAG_LABELS.get(flag, flag)


def _haversine(lat1, lon1, lat2, lon2):
    """Distance en mètres entre deux points GPS (formule de Haversine)."""
    R = 6_371_000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def evaluate_scan_risk(*, user, device, device_id_hash, ip_address,
                       latitude=None, longitude=None, accuracy=None,
                       settings_obj=None):
    """
    Évalue le risque d'un scan qui va être validé. Retourne ``(risk_score, flags)``.

    Ne bloque jamais : le résultat est purement informatif (journalisé dans QRScanLog
    et reflété par QRScanRecord.is_suspicious pour l'affichage prof/secrétariat).
    """
    from apps.absences.models import QRScanLog
    from apps.accounts.models import StudentDevice

    flags = []

    # Réglages (avec valeurs de repli sûres).
    max_kmh = getattr(settings_obj, "geo_velocity_max_kmh", 900) or 900
    max_acc = getattr(settings_obj, "gps_accuracy_max_meters", 1000) or 1000

    # 1) Même appareil → plusieurs comptes (signal fort, clé de la soutenance).
    if device_id_hash:
        distinct_users = (
            StudentDevice.objects.filter(device_id_hash=device_id_hash)
            .values("user_id")
            .distinct()
            .count()
        )
        if distinct_users >= 2:
            flags.append(FLAG_MULTI_ACCOUNT_DEVICE)

    # 2) Nouvelle IP pour ce compte (par rapport aux scans validés précédents).
    if ip_address:
        prior = QRScanLog.objects.filter(
            etudiant=user, scan_result=QRScanLog.ScanResult.VALIDATED
        )
        if prior.exists() and not prior.filter(ip_address=ip_address).exists():
            flags.append(FLAG_NEW_IP)

    # 3) Géo-vélocité incohérente vs le dernier scan localisé.
    if latitude is not None and longitude is not None:
        last = (
            QRScanLog.objects.filter(
                etudiant=user,
                scan_result=QRScanLog.ScanResult.VALIDATED,
                latitude__isnull=False,
                longitude__isnull=False,
            )
            .order_by("-timestamp")
            .first()
        )
        if last is not None:
            dt_hours = (timezone.now() - last.timestamp).total_seconds() / 3600.0
            if dt_hours > 0:
                dist_km = _haversine(last.latitude, last.longitude, latitude, longitude) / 1000.0
                if dist_km / dt_hours > max_kmh:
                    flags.append(FLAG_GEO_VELOCITY)

    # 4) Précision GPS annoncée trop faible.
    if accuracy is not None:
        try:
            if float(accuracy) > max_acc:
                flags.append(FLAG_LOW_GPS_ACCURACY)
        except (TypeError, ValueError):
            pass

    # 5) Appareil enrôlé très récemment (première utilisation).
    if device is not None and getattr(device, "created_at", None) is not None:
        age_h = (timezone.now() - device.created_at).total_seconds() / 3600.0
        if age_h < NEW_DEVICE_MAX_AGE_HOURS:
            flags.append(FLAG_NEW_DEVICE)

    risk_score = min(100, sum(FLAG_WEIGHTS.get(f, 0) for f in flags))
    return risk_score, flags
