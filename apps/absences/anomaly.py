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
  - same_device_same_seance : même appareil (hash) ayant validé la présence d'un
    AUTRE compte dans la même séance — le signal le plus direct du « buddy
    punching » ; le scan antérieur est aussi marqué a posteriori.
  - device_churn       : ≥ 3 appareils APPROUVÉS en 30 jours sur le compte (cycles
    révocation → nouvel appareil → OTP).
  - geo_velocity        : déplacement physiquement impossible depuis le dernier scan.
  - new_ip             : adresse IP jamais vue pour ce compte.
  - low_gps_accuracy   : précision GPS annoncée trop faible pour être fiable.
  - recently_approved  : appareil APPROUVÉ très récemment (OTP ou secrétariat).
    Remplace ``new_device`` (basé sur la création : contourné en pré-enrôlant
    l'appareil la veille). Le libellé ``new_device`` reste pour les anciens logs.
"""

import math

from django.utils import timezone

# --- Drapeaux (valeurs stables : stockées en base et affichées dans l'UI) ---
FLAG_MULTI_ACCOUNT_DEVICE = "multi_account_device"
FLAG_SAME_DEVICE_SAME_SEANCE = "same_device_same_seance"
FLAG_DEVICE_CHURN = "device_churn"
FLAG_GEO_VELOCITY = "geo_velocity"
FLAG_NEW_IP = "new_ip"
FLAG_LOW_GPS_ACCURACY = "low_gps_accuracy"
FLAG_NEW_DEVICE = "new_device"  # historique : n'est plus émis
FLAG_RECENTLY_APPROVED = "recently_approved"

#: Poids de chaque drapeau dans le score de risque (0–100, plafonné).
FLAG_WEIGHTS = {
    FLAG_MULTI_ACCOUNT_DEVICE: 50,
    FLAG_SAME_DEVICE_SAME_SEANCE: 60,
    FLAG_DEVICE_CHURN: 20,
    FLAG_GEO_VELOCITY: 40,
    FLAG_NEW_IP: 15,
    FLAG_LOW_GPS_ACCURACY: 10,
    FLAG_RECENTLY_APPROVED: 30,
}

#: Libellés humains (pour l'UI prof/secrétariat).
FLAG_LABELS = {
    FLAG_MULTI_ACCOUNT_DEVICE: "Même appareil utilisé par plusieurs comptes",
    FLAG_SAME_DEVICE_SAME_SEANCE: "Même appareil a validé un autre étudiant dans cette séance",
    FLAG_DEVICE_CHURN: "Nombreux appareils approuvés récemment",
    FLAG_GEO_VELOCITY: "Déplacement incohérent depuis le dernier scan",
    FLAG_NEW_IP: "Nouvelle adresse IP",
    FLAG_LOW_GPS_ACCURACY: "Précision GPS faible",
    FLAG_NEW_DEVICE: "Appareil récemment enrôlé",
    FLAG_RECENTLY_APPROVED: "Appareil approuvé très récemment",
}

#: Un scan est marqué « suspect » au-delà de ce score.
SUSPICIOUS_THRESHOLD = 30
#: Un appareil est « récemment approuvé » s'il l'a été il y a moins de N heures.
#: Poids 30 = seuil suspect à lui seul : c'est la trace du scénario « mot de passe
#: + OTP transmis à un camarade », même depuis une fenêtre de navigation privée.
RECENTLY_APPROVED_MAX_AGE_HOURS = 24
#: device_churn : au moins N appareils approuvés (OTP ou secrétariat) sur la
#: fenêtre. On compte les APPROBATIONS, pas les créations : un navigateur qui
#: vide ses cookies crée des appareils PENDING sans que ce soit suspect.
DEVICE_CHURN_MIN_APPROVALS = 3
DEVICE_CHURN_WINDOW_DAYS = 30


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


def score_flags(flags):
    """Score de risque (0–100, plafonné) d'une liste de drapeaux."""
    return min(100, sum(FLAG_WEIGHTS.get(f, 0) for f in flags))


def evaluate_scan_risk(*, user, device, device_id_hash, ip_address,
                       latitude=None, longitude=None, accuracy=None,
                       settings_obj=None, seance=None):
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

    # 1b) Même appareil → un AUTRE compte validé dans la MÊME séance.
    if device_id_hash and seance is not None:
        if (
            QRScanLog.objects.filter(
                seance=seance,
                device_id_hash=device_id_hash,
                scan_result=QRScanLog.ScanResult.VALIDATED,
            )
            .exclude(etudiant=user)
            .exists()
        ):
            flags.append(FLAG_SAME_DEVICE_SAME_SEANCE)

    # 1c) Rotation d'appareils : approbations répétées sur le compte.
    churn_since = timezone.now() - timezone.timedelta(days=DEVICE_CHURN_WINDOW_DAYS)
    if (
        StudentDevice.objects.filter(user=user, approved_at__gte=churn_since).count()
        >= DEVICE_CHURN_MIN_APPROVALS
    ):
        flags.append(FLAG_DEVICE_CHURN)

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

    # 5) Appareil approuvé très récemment (date d'APPROBATION, pas de création).
    if device is not None and getattr(device, "approved_at", None) is not None:
        age_h = (timezone.now() - device.approved_at).total_seconds() / 3600.0
        if age_h < RECENTLY_APPROVED_MAX_AGE_HOURS:
            flags.append(FLAG_RECENTLY_APPROVED)

    return score_flags(flags), flags


def flag_earlier_same_device_scans(*, seance, device_id_hash, user):
    """
    Marque a posteriori les scans VALIDÉS antérieurs de la séance faits avec le
    même appareil par d'autres comptes : au moment où ils ont été enregistrés,
    rien ne permettait de savoir que l'appareil servirait à un second compte.
    Met à jour drapeaux, score et QRScanRecord.is_suspicious. Ne bloque rien.
    """
    from apps.absences.models import QRScanLog, QRScanRecord

    if not device_id_hash:
        return
    earlier = QRScanLog.objects.filter(
        seance=seance,
        device_id_hash=device_id_hash,
        scan_result=QRScanLog.ScanResult.VALIDATED,
    ).exclude(etudiant=user)
    for log in earlier:
        flags = list(log.anomaly_flags or [])
        if FLAG_SAME_DEVICE_SAME_SEANCE in flags:
            continue
        flags.append(FLAG_SAME_DEVICE_SAME_SEANCE)
        log.anomaly_flags = flags
        log.risk_score = score_flags(flags)
        log.save(update_fields=["anomaly_flags", "risk_score"])
        if log.risk_score >= SUSPICIOUS_THRESHOLD:
            QRScanRecord.objects.filter(seance=seance, student_id=log.etudiant_id).update(
                is_suspicious=True
            )
