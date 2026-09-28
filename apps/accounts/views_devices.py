"""
FICHIER : apps/accounts/views_devices.py
RESPONSABILITE : Gestion des appareils de confiance (anti-fraude présence par procuration)
FONCTIONNALITES PRINCIPALES :
  - verify_device : vérification d'un nouvel appareil par OTP e-mail (PENDING -> APPROVED)
  - my_devices    : liste des appareils de l'étudiant + révocation
  - secretariat_devices / secretariat_device_action : fallback d'approbation par le secrétariat
SECURITE :
  - Le backend est la seule autorité sur le statut (APPROVED/PENDING/REVOKED).
  - Limite d'appareils APPROVED configurable (SystemSettings.max_devices_per_student).
"""

import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods, require_POST
from django_ratelimit.core import get_usage

from apps.accounts.devices import (
    can_approve_more,
    ensure_device_cookie,
    get_or_enroll_device,
)
from apps.accounts.models import StudentDevice
from apps.audits.utils import log_action
from apps.dashboard.decorators import roles_required, student_required
from apps.dashboard.models import SystemSettings
from apps.notifications.email import (
    build_device_verification_email,
    send_notification_email,
)

logger = logging.getLogger(__name__)

#: Quotas d'émission d'OTP, comptés par UTILISATEUR et non par appareil : vider
#: ses cookies crée un nouvel appareil, ce qui remettrait un quota par appareil
#: à zéro. 10 codes/jour × 5 essais/code = 50 essais/jour sur 10^6 combinaisons.
OTP_SEND_RATES = ("3/h", "10/d")
#: Vérifications de code (bonnes ou mauvaises), par utilisateur.
OTP_VERIFY_RATE = "10/h"
_OTP_SEND_GROUP = "accounts.device_otp_send"
_OTP_VERIFY_GROUP = "accounts.device_otp_verify"
_OTP_QUOTA_MESSAGE = (
    "Trop de codes demandés. Réessayez plus tard ou contactez le secrétariat."
)


def _user_key(group, request):
    return str(request.user.pk)


def _consume_otp_send_quota(request):
    """
    True — et consomme une unité de chaque quota — si l'utilisateur est sous
    TOUTES les limites d'émission ; False (sans rien consommer) sinon.
    """
    for rate in OTP_SEND_RATES:
        usage = get_usage(request, group=_OTP_SEND_GROUP, key=_user_key, rate=rate)
        if usage is not None and usage["count"] >= usage["limit"]:
            log_action(
                request.user,
                f"Envoi d'OTP appareil refusé (limite {rate} atteinte)",
                request,
                niveau="WARNING",
                objet_type="AUTRE",
            )
            return False
    for rate in OTP_SEND_RATES:
        get_usage(request, group=_OTP_SEND_GROUP, key=_user_key, rate=rate, increment=True)
    return True


def _send_device_otp(user, code):
    """
    Envoie le code OTP de vérification d'appareil, via le même système de
    notification (template HTML + fallback texte) que les autres e-mails.
    """
    subject, body, html_body = build_device_verification_email(
        user, code, StudentDevice.OTP_TTL_SECONDS // 60
    )
    send_notification_email(user, subject, body, html_body)


@login_required
@student_required
@ensure_device_cookie
@require_http_methods(["GET", "POST"])
def verify_device(request):
    """
    Vérifie l'appareil courant via un OTP envoyé par e-mail.
    PENDING + code correct + sous la limite -> APPROVED.
    """
    device, device_id, is_new_cookie = get_or_enroll_device(request)
    if is_new_cookie:
        request._device_id_to_set = device_id

    sys_settings = SystemSettings.get_settings()

    if device.is_approved:
        messages.info(request, "Cet appareil est déjà approuvé.")
        return redirect("accounts:my_devices")

    if device.status == StudentDevice.Status.REVOKED:
        messages.error(
            request,
            "Cet appareil a été révoqué. Contactez le secrétariat pour le réactiver.",
        )
        return redirect("accounts:my_devices")

    # --- POST : soit renvoyer un code, soit vérifier le code saisi ---
    if request.method == "POST":
        if request.POST.get("action") == "resend":
            if not _consume_otp_send_quota(request):
                messages.error(request, _OTP_QUOTA_MESSAGE)
                return redirect("accounts:verify_device")
            code = device.set_otp()
            _send_device_otp(request.user, code)
            messages.success(request, "Un nouveau code vous a été envoyé par e-mail.")
            return redirect("accounts:verify_device")

        usage = get_usage(
            request, group=_OTP_VERIFY_GROUP, key=_user_key,
            rate=OTP_VERIFY_RATE, increment=True,
        )
        if usage is not None and usage["should_limit"]:
            log_action(
                request.user,
                "Vérification d'OTP appareil refusée (trop de tentatives)",
                request,
                niveau="WARNING",
                objet_type="AUTRE",
                objet_id=device.pk,
            )
            messages.error(
                request,
                "Trop de tentatives de vérification. Réessayez dans une heure "
                "ou contactez le secrétariat.",
            )
            return redirect("accounts:verify_device")

        submitted = request.POST.get("code", "").strip()
        if device.verify_otp(submitted):
            # Vérifie la limite d'appareils approuvés AVANT d'approuver.
            if not can_approve_more(request.user, sys_settings, exclude_pk=device.pk):
                limit = sys_settings.max_devices_per_student
                messages.error(
                    request,
                    f"Vous avez déjà {limit} appareils approuvés. Révoquez-en un "
                    f"depuis l'un de vos appareils approuvés (ou demandez au "
                    f"secrétariat) avant d'ajouter celui-ci.",
                )
                return redirect("accounts:my_devices")
            device.approve()
            log_action(
                request.user,
                "Appareil approuvé via OTP e-mail",
                request,
                niveau="INFO",
                objet_type="AUTRE",
                objet_id=device.pk,
            )
            messages.success(
                request,
                "Appareil vérifié et approuvé. Vous pouvez maintenant valider "
                "votre présence.",
            )
            return redirect("accounts:my_devices")
        messages.error(request, "Code incorrect ou expiré. Réessayez.")
        return redirect("accounts:verify_device")

    # --- GET : (re)génère un code si nécessaire et l'envoie ---
    from django.utils import timezone

    needs_code = (
        not device.otp_hash
        or device.otp_expires_at is None
        or timezone.now() > device.otp_expires_at
    )
    if needs_code and not _consume_otp_send_quota(request):
        messages.warning(request, _OTP_QUOTA_MESSAGE)
    elif needs_code:
        code = device.set_otp()
        try:
            _send_device_otp(request.user, code)
        except Exception:  # pragma: no cover - dépend du backend mail
            logger.exception("Envoi OTP appareil échoué pour %s", request.user.pk)
            messages.warning(
                request,
                "Le code n'a pas pu être envoyé. Réessayez ou contactez le secrétariat.",
            )

    masked = _mask_email(request.user.email)
    return render(request, "accounts/verify_device.html", {
        "device": device,
        "masked_email": masked,
    })


def _mask_email(email):
    """user@domain -> u***@domain (indice pour l'utilisateur sans tout révéler)."""
    try:
        local, domain = email.split("@", 1)
    except ValueError:
        return email
    if len(local) <= 1:
        return f"{local}***@{domain}"
    return f"{local[0]}***@{domain}"


@login_required
@student_required
@ensure_device_cookie
@require_http_methods(["GET", "POST"])
def my_devices(request):
    """Liste des appareils de l'étudiant + révocation."""
    device, device_id, is_new_cookie = get_or_enroll_device(request)
    if is_new_cookie:
        request._device_id_to_set = device_id

    if request.method == "POST" and request.POST.get("action") == "revoke":
        target = get_object_or_404(
            StudentDevice, pk=request.POST.get("device_pk"), user=request.user
        )
        # Only an APPROVED device may revoke an APPROVED one. Otherwise the
        # password alone (from a fresh PENDING browser) would be enough to evict
        # the owner's devices and free a slot for another device.
        if target.is_approved and not device.is_approved:
            log_action(
                request.user,
                "Révocation d'un appareil approuvé refusée (appareil courant non approuvé)",
                request,
                niveau="WARNING",
                objet_type="AUTRE",
                objet_id=target.pk,
            )
            messages.error(
                request,
                "Un appareil approuvé ne peut être révoqué que depuis un autre "
                "appareil approuvé. Si vous n'y avez plus accès (perte, vol), "
                "contactez le secrétariat.",
            )
            return redirect("accounts:my_devices")
        target.status = StudentDevice.Status.REVOKED
        target.save(update_fields=["status"])
        log_action(
            request.user,
            "Appareil révoqué par l'étudiant",
            request,
            niveau="INFO",
            objet_type="AUTRE",
            objet_id=target.pk,
        )
        messages.success(request, "Appareil révoqué.")
        return redirect("accounts:my_devices")

    sys_settings = SystemSettings.get_settings()
    devices = list(StudentDevice.objects.filter(user=request.user))
    return render(request, "accounts/my_devices.html", {
        "devices": devices,
        "current_device_pk": device.pk,
        "current_device_approved": device.is_approved,
        "max_devices": sys_settings.max_devices_per_student,
        "Status": StudentDevice.Status,
    })


@login_required
@roles_required("SECRETAIRE", "ADMIN")
@require_POST
def secretariat_device_action(request, device_pk):
    """Fallback : le secrétariat approuve/révoque un appareil (avec contrôle de limite)."""
    device = get_object_or_404(StudentDevice, pk=device_pk)
    action = request.POST.get("action")
    sys_settings = SystemSettings.get_settings()

    if action == "approve":
        if not can_approve_more(device.user, sys_settings, exclude_pk=device.pk):
            messages.error(
                request,
                f"{device.user.get_full_name()} a déjà atteint la limite "
                f"({sys_settings.max_devices_per_student}) d'appareils approuvés.",
            )
            return redirect("accounts:secretariat_devices")
        device.approve()
        log_action(request.user, f"Appareil approuvé (secrétariat) — {device.user.email}",
                   request, niveau="INFO", objet_type="AUTRE", objet_id=device.pk)
        messages.success(request, "Appareil approuvé.")
    elif action == "revoke":
        device.status = StudentDevice.Status.REVOKED
        device.save(update_fields=["status"])
        log_action(request.user, f"Appareil révoqué (secrétariat) — {device.user.email}",
                   request, niveau="INFO", objet_type="AUTRE", objet_id=device.pk)
        messages.success(request, "Appareil révoqué.")
    return redirect("accounts:secretariat_devices")


@login_required
@roles_required("SECRETAIRE", "ADMIN")
@require_http_methods(["GET"])
def secretariat_devices(request):
    """
    Appareils nécessitant une action du secrétariat : en attente (PENDING) ET
    révoqués (REVOKED), afin qu'un appareil révoqué puisse être réactivé
    (approuvé) — sinon le message « contactez le secrétariat » serait un cul-de-sac.
    """
    devices = list(
        StudentDevice.objects.filter(
            status__in=[StudentDevice.Status.PENDING, StudentDevice.Status.REVOKED]
        ).select_related("user")
    )
    return render(request, "accounts/secretariat_devices.html", {
        "devices": devices,
        "Status": StudentDevice.Status,
    })
