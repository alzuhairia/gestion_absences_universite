"""
FICHIER : apps/accounts/mfa/mfa_service.py
RESPONSABILITE : Logique metier MFA — constantes TOTP, generation/verification
                 des codes de secours, generation du QR code de provisioning.
                 Aucune dependance HTTP : utilisable independamment des vues.
"""
import logging
import secrets

from django.contrib.auth.hashers import check_password, make_password
from django.db import transaction
from django.utils import timezone

from apps.utils import generate_qr_data_uri as _generate_qr_data_uri  # noqa: F401

from ..models import TwoFactorBackupCode

logger = logging.getLogger(__name__)

# ─── Constants ──────────────────────────────────────────────────────────────

#: Cle de session ou est stocke le secret temporaire pendant l'enrolment.
SETUP_SECRET_SESSION_KEY = "_2fa_setup_secret"

#: Cle de session: True une fois le code TOTP verifie pour la session courante.
VERIFIED_SESSION_KEY = "2fa_verified"

#: Cle de session: nombre de tentatives de verification echouees.
ATTEMPTS_SESSION_KEY = "_2fa_attempts"

#: Nombre maximum d'essais avant deconnexion automatique.
MAX_VERIFY_ATTEMPTS = 5

#: Nom de l'emetteur affiche dans l'application TOTP (Google Authenticator, Authy).
TOTP_ISSUER = "UniAbsences"

#: Cle de session ou sont stockes temporairement les codes de secours en clair
#: (le temps d'un aller-retour vers la page d'affichage one-shot).
BACKUP_CODES_SESSION_KEY = "_2fa_new_backup_codes"

#: Nombre de caracteres de chaque code de secours (5+5 = 10).
BACKUP_CODE_LENGTH = 10


# ─── QR / TOTP helpers ──────────────────────────────────────────────────────


def _normalize_token(raw: str) -> str:
    """Strip whitespace and keep only digits — paste-friendly."""
    if not raw:
        return ""
    return "".join(ch for ch in raw if ch.isdigit())[:6]


# ─── Backup codes helpers ───────────────────────────────────────────────────


def _normalize_backup_code(raw: str) -> str:
    """Upper-case + keep only A-Z/0-9. Accepts 'ABCD-EFGH' or 'abcdefgh'."""
    if not raw:
        return ""
    return "".join(ch for ch in raw.upper() if ch.isalnum())[: BACKUP_CODE_LENGTH]


def _format_backup_code(raw: str) -> str:
    """Format a raw 10-char code as 5-5 groups for display: ABCDE-FGHIJ."""
    mid = BACKUP_CODE_LENGTH // 2
    return f"{raw[:mid]}-{raw[mid:]}"


def _generate_backup_codes(user, nb=TwoFactorBackupCode.CODES_PER_BATCH):
    """
    Create `nb` backup codes for this user, replacing any existing ones.

    Returns the plaintext codes (list of str) so the caller can display
    them ONCE. Only hashes are persisted.
    """
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # skip O/0/1/I
    plaintext = []
    with transaction.atomic():
        TwoFactorBackupCode.objects.filter(user=user).delete()
        rows = []
        for _ in range(nb):
            raw = "".join(secrets.choice(alphabet) for _ in range(BACKUP_CODE_LENGTH))
            plaintext.append(raw)
            rows.append(
                TwoFactorBackupCode(
                    user=user,
                    code_hash=make_password(raw),
                )
            )
        TwoFactorBackupCode.objects.bulk_create(rows)
    return plaintext


def _consume_backup_code(user, candidate: str) -> bool:
    """
    Check a user-submitted backup code against this user's unused codes.
    Returns True (and marks the code used) on match, False otherwise.
    Constant-time over the set of unused codes.
    """
    if not candidate or len(candidate) != BACKUP_CODE_LENGTH:
        return False
    with transaction.atomic():
        unused = list(
            TwoFactorBackupCode.objects.select_for_update()
            .filter(user=user, used=False)
        )
        for row in unused:
            if check_password(candidate, row.code_hash):
                row.used = True
                row.used_at = timezone.now()
                row.save(update_fields=["used", "used_at"])
                return True
    return False
