"""
FICHIER : apps/accounts/devices.py
RESPONSABILITE : Liaison d'appareil de confiance (anti-fraude présence par procuration)
FONCTIONNALITES PRINCIPALES :
  - Cookie signé identifiant le NAVIGATEUR (secret jamais stocké en clair côté serveur)
  - Enrôlement d'appareil : tout nouvel appareil (y compris le 1er) arrive en PENDING (OTP requis)
  - Résolution serveur du StudentDevice associé au compte connecté
SECURITE :
  - Le device_id (secret) vit UNIQUEMENT dans un cookie signé (HttpOnly/Secure/SameSite).
  - Seul son hash SHA-256 est persisté (StudentDevice.device_id_hash).
  - Le backend est la seule autorité sur le statut APPROVED/PENDING/REVOKED.
"""

import hashlib
import secrets
from functools import wraps

from django.conf import settings
from django.core import signing
from django.db import IntegrityError
from django.utils import timezone

from apps.accounts.models import StudentDevice
from apps.audits.utils import get_client_ip

#: Nom du cookie signé porté par le navigateur.
DEVICE_COOKIE_NAME = "device_token"
#: Durée de vie du cookie (≈ 180 jours).
DEVICE_COOKIE_MAX_AGE = 180 * 24 * 3600
#: Sel de signature (versionné pour permettre une rotation future).
_DEVICE_SALT = "accounts.device_token.v1"


def hash_device_id(device_id: str) -> str:
    """SHA-256 hex du secret d'appareil — ce qui est stocké en base."""
    return hashlib.sha256(device_id.encode("utf-8")).hexdigest()


def new_device_id() -> str:
    """Génère un secret d'appareil aléatoire à haute entropie."""
    return secrets.token_urlsafe(32)


def sign_device_id(device_id: str) -> str:
    """Signe le device_id pour le cookie (intégrité, non chiffré)."""
    return signing.dumps({"d": device_id}, salt=_DEVICE_SALT)


def read_device_id(request) -> str | None:
    """
    Lit et VÉRIFIE le device_id depuis le cookie signé.
    Retourne None si absent, altéré ou expiré : un cookie falsifié n'est jamais
    accepté (le backend ne fait pas confiance à un device_id brut du navigateur).
    """
    raw = request.COOKIES.get(DEVICE_COOKIE_NAME)
    if not raw:
        return None
    try:
        data = signing.loads(raw, salt=_DEVICE_SALT, max_age=DEVICE_COOKIE_MAX_AGE)
    except signing.BadSignature:
        return None
    device_id = data.get("d") if isinstance(data, dict) else None
    return device_id or None


def set_device_cookie(response, device_id: str) -> None:
    """Pose le cookie signé (HttpOnly + Secure + SameSite=Strict)."""
    response.set_cookie(
        DEVICE_COOKIE_NAME,
        sign_device_id(device_id),
        max_age=DEVICE_COOKIE_MAX_AGE,
        httponly=True,
        secure=getattr(settings, "SESSION_COOKIE_SECURE", not settings.DEBUG),
        samesite="Strict",
    )


def _default_label(user_agent: str) -> str:
    """Étiquette lisible par défaut, dérivée du User-Agent (best effort)."""
    ua = (user_agent or "").lower()
    if "android" in ua:
        return "Appareil Android"
    if "iphone" in ua:
        return "iPhone"
    if "ipad" in ua:
        return "iPad"
    if "windows" in ua:
        return "PC Windows"
    if "mac" in ua:
        return "Mac"
    if "linux" in ua:
        return "PC Linux"
    return "Appareil"


def get_or_enroll_device(request):
    """
    Résout — et au besoin enrôle — le StudentDevice du navigateur courant pour
    l'utilisateur connecté.

    Retourne ``(device, device_id, is_new_cookie)`` :
      - ``device`` : instance StudentDevice (jamais None pour un étudiant connecté).
      - ``device_id`` : secret courant (à reposer via cookie si is_new_cookie).
      - ``is_new_cookie`` : True si un nouveau secret a été généré (cookie à écrire).

    Politique d'enrôlement : tout appareil inconnu — y compris le tout premier
    de l'étudiant — arrive en PENDING et doit être vérifié par OTP e-mail (ou
    approuvé par le secrétariat). Pas d'auto-approbation : sinon, pour un compte
    sans appareil, quiconque connaît le mot de passe enrôlerait SON appareil.
    """
    user = request.user
    device_id = read_device_id(request)
    is_new_cookie = False
    if not device_id:
        device_id = new_device_id()
        is_new_cookie = True

    device_hash = hash_device_id(device_id)
    ua = request.META.get("HTTP_USER_AGENT", "")[:500]
    ip = get_client_ip(request)

    device = StudentDevice.objects.filter(user=user, device_id_hash=device_hash).first()
    if device is not None:
        # Appareil déjà connu : rafraîchit les métadonnées de dernière vue.
        device.last_seen_at = timezone.now()
        device.ip_address = ip
        if ua:
            device.user_agent = ua
        device.save(update_fields=["last_seen_at", "ip_address", "user_agent"])
        return device, device_id, is_new_cookie

    try:
        device = StudentDevice.objects.create(
            user=user,
            device_id_hash=device_hash,
            status=StudentDevice.Status.PENDING,
            user_agent=ua,
            ip_address=ip,
            label=_default_label(ua),
        )
    except IntegrityError:
        # Course entre deux requêtes concurrentes : on relit l'enregistrement.
        device = StudentDevice.objects.get(user=user, device_id_hash=device_hash)
    return device, device_id, is_new_cookie


def approved_device_count(user, exclude_pk=None) -> int:
    """Nombre d'appareils APPROVED (PENDING/REVOKED exclus) pour cet utilisateur."""
    qs = StudentDevice.objects.filter(user=user, status=StudentDevice.Status.APPROVED)
    if exclude_pk is not None:
        qs = qs.exclude(pk=exclude_pk)
    return qs.count()


def can_approve_more(user, settings_obj, exclude_pk=None) -> bool:
    """True si l'étudiant est sous la limite d'appareils approuvés configurée."""
    limit = getattr(settings_obj, "max_devices_per_student", 2)
    return approved_device_count(user, exclude_pk=exclude_pk) < limit


def ensure_device_cookie(view_func):
    """
    Décorateur : après l'exécution de la vue, pose le cookie d'appareil si la vue
    a demandé son écriture via ``request._device_id_to_set``. Centralise l'écriture
    du cookie quel que soit le point de sortie de la vue.
    """

    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        response = view_func(request, *args, **kwargs)
        device_id = getattr(request, "_device_id_to_set", None)
        if device_id:
            set_device_cookie(response, device_id)
        return response

    return _wrapped
