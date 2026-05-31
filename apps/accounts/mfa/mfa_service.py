"""
MFA business-logic service for the UniAbsences accounts system.

This module is the HTTP-independent layer for TOTP two-factor authentication.
It contains no Django view or request logic and can be called from views,
management commands, or tests alike.

Responsibilities
----------------
- Define the session-key constants used by ``TwoFactorMiddleware`` and the
  2FA views to track setup state and verification status.
- Expose ``_normalize_token`` — strips whitespace and non-digits from a
  user-submitted TOTP token to support copy-paste from authenticator apps.
- Expose ``_normalize_backup_code`` — normalises a raw backup code string
  to the canonical upper-case alphanumeric form used for hash comparison.
- Expose ``_format_backup_code`` — formats a 10-character code as two 5-char
  groups separated by a hyphen for display purposes (e.g. ``ABCDE-FGHIJ``).
- Expose ``_generate_backup_codes`` — creates a new batch of backup codes,
  deletes any existing codes atomically, and returns the plaintext values so
  the caller can display them exactly once.
- Expose ``_consume_backup_code`` — verifies and consumes a single backup
  code atomically using ``select_for_update`` to prevent concurrent double-use.
- Re-export ``_generate_qr_data_uri`` from ``apps.utils`` under the
  ``_generate_qr_data_uri`` alias for backward compatibility with callers
  that import it from this module.

Part of the UniAbsences accounts / MFA system.
"""

import logging
import secrets

from django.contrib.auth.hashers import check_password, make_password
from django.db import transaction
from django.utils import timezone

from apps.utils import generate_qr_data_uri as _generate_qr_data_uri  # noqa: F401

from ..models import TwoFactorBackupCode

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Session-key constants
# ---------------------------------------------------------------------------

#: Key under which the temporary TOTP secret is stored in the session during
#: the 2FA enrollment wizard.  Cleared once enrollment is confirmed.
SETUP_SECRET_SESSION_KEY = "_2fa_setup_secret"

#: Key set to ``True`` in the session once the user has passed the TOTP gate
#: for the current session.  Read by ``TwoFactorMiddleware`` on every request.
VERIFIED_SESSION_KEY = "2fa_verified"

#: Key tracking the number of failed TOTP verification attempts in the current
#: session.  The user is logged out when this reaches ``MAX_VERIFY_ATTEMPTS``.
ATTEMPTS_SESSION_KEY = "_2fa_attempts"

#: Maximum number of consecutive failed TOTP verification attempts before the
#: session is forcibly terminated.
MAX_VERIFY_ATTEMPTS = 5

#: Issuer name embedded in the TOTP provisioning URI and displayed by
#: authenticator apps (Google Authenticator, Authy, etc.).
TOTP_ISSUER = "UniAbsences"

#: Session key under which the newly generated backup codes (plaintext) are
#: stored for a single round-trip to the one-shot display page.  The key is
#: removed immediately after the page renders so the codes cannot be revisited.
BACKUP_CODES_SESSION_KEY = "_2fa_new_backup_codes"

#: Number of characters in each backup code.  The code is split into two
#: 5-character groups for display: ``ABCDE-FGHIJ``.
BACKUP_CODE_LENGTH = 10


# ---------------------------------------------------------------------------
# TOTP helpers
# ---------------------------------------------------------------------------


def _normalize_token(raw: str) -> str:
    """
    Normalise a raw TOTP token string for comparison.

    Strips all whitespace and non-digit characters then truncates to 6
    digits.  This makes the function tolerant of user input that includes
    spaces (e.g. "123 456" from an authenticator app that adds a space for
    readability).

    Parameters:
        raw (str): The raw string submitted by the user.

    Returns:
        str: A string of at most 6 digits, or an empty string if ``raw``
             is falsy.
    """
    if not raw:
        return ""
    return "".join(ch for ch in raw if ch.isdigit())[:6]


# ---------------------------------------------------------------------------
# Backup-code helpers
# ---------------------------------------------------------------------------


def _normalize_backup_code(raw: str) -> str:
    """
    Normalise a raw backup code for hash comparison.

    Converts to upper case and retains only alphanumeric characters, then
    truncates to ``BACKUP_CODE_LENGTH`` (10).  This makes the function
    tolerant of input formatted with a hyphen separator (e.g. ``ABCDE-FGHIJ``
    becomes ``ABCDEFGHIJ``).

    Parameters:
        raw (str): The raw code string submitted by the user.

    Returns:
        str: The normalised code (up to 10 uppercase alphanumeric characters),
             or an empty string if ``raw`` is falsy.
    """
    if not raw:
        return ""
    return "".join(ch for ch in raw.upper() if ch.isalnum())[: BACKUP_CODE_LENGTH]


def _format_backup_code(raw: str) -> str:
    """
    Format a 10-character backup code as two 5-character hyphen-separated groups.

    Used when displaying newly generated codes to the user so they are
    easier to read and transcribe (e.g. ``ABCDE-FGHIJ``).

    Parameters:
        raw (str): A 10-character alphanumeric backup code.

    Returns:
        str: The code formatted as ``XXXXX-XXXXX``.
    """
    mid = BACKUP_CODE_LENGTH // 2
    return f"{raw[:mid]}-{raw[mid:]}"


def _generate_backup_codes(user, nb=TwoFactorBackupCode.CODES_PER_BATCH):
    """
    Generate a new batch of backup codes for a user, replacing all existing ones.

    All existing backup codes for the user (used or unused) are deleted inside
    an atomic transaction before the new batch is created.  Only the bcrypt
    hashes of the new codes are persisted; the plaintext values are returned
    to the caller so they can be displayed to the user exactly once.

    The character set deliberately excludes visually ambiguous characters
    (``O``, ``0``, ``1``, ``I``) to reduce transcription errors.

    Parameters:
        user: The ``User`` instance for which codes are generated.
        nb (int): Number of codes to generate.  Defaults to
                  ``TwoFactorBackupCode.CODES_PER_BATCH`` (8).

    Returns:
        list[str]: Plaintext codes of length ``BACKUP_CODE_LENGTH``.  These
                   are **not** stored; the caller must show them to the user
                   and then discard them.
    """
    # Unambiguous character set: no O/0/1/I to prevent transcription errors.
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    plaintext = []
    with transaction.atomic():
        # Delete all existing codes (used or not) to avoid ambiguity about
        # which codes are currently valid.
        TwoFactorBackupCode.objects.filter(user=user).delete()
        rows = []
        for _ in range(nb):
            raw = "".join(secrets.choice(alphabet) for _ in range(BACKUP_CODE_LENGTH))
            plaintext.append(raw)
            rows.append(
                TwoFactorBackupCode(
                    user=user,
                    # Store only the hash; plaintext is never persisted.
                    code_hash=make_password(raw),
                )
            )
        TwoFactorBackupCode.objects.bulk_create(rows)
    return plaintext


def _consume_backup_code(user, candidate: str) -> bool:
    """
    Verify and consume a backup code atomically.

    All unused backup codes for the user are fetched under a
    ``SELECT FOR UPDATE`` lock to prevent concurrent verification of the
    same code from two simultaneous requests (classic double-spend attack).

    Each hash is compared against ``candidate`` using ``check_password``
    (Django's constant-time wrapper around the configured hasher).  The loop
    does **not** break on a non-matching code, iterating all unused codes to
    avoid timing side-channels that could reveal the number of remaining codes.

    On a successful match the code is immediately marked ``used=True`` and
    ``used_at`` is recorded so it cannot be reused.

    Parameters:
        user: The ``User`` instance attempting backup-code login.
        candidate (str): The normalised (uppercase alphanumeric) backup code
                         submitted by the user.  Must be exactly
                         ``BACKUP_CODE_LENGTH`` characters.

    Returns:
        bool: ``True`` if a matching unused code was found and consumed,
              ``False`` otherwise.
    """
    # Reject trivially invalid inputs without hitting the database.
    if not candidate or len(candidate) != BACKUP_CODE_LENGTH:
        return False
    with transaction.atomic():
        # Lock all unused codes for this user for the duration of the
        # transaction to prevent concurrent consumption of the same code.
        unused = list(
            TwoFactorBackupCode.objects.select_for_update()
            .filter(user=user, used=False)
        )
        for row in unused:
            if check_password(candidate, row.code_hash):
                # Mark as used immediately so the code cannot be reused.
                row.used = True
                row.used_at = timezone.now()
                row.save(update_fields=["used", "used_at"])
                return True
    return False
