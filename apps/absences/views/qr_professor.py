"""
FICHIER : apps/absences/views/qr_professor.py
RESPONSABILITE : Re-export hub — vues QR code côté professeur

Sous-modules :
  qr_professor_generate.py — qr_generate (créer séance + token QR)
  qr_professor_session.py  — qr_dashboard, qr_refresh_token, qr_finalize
"""

from .qr_professor_generate import qr_generate  # noqa: F401
from .qr_professor_session import (  # noqa: F401
    qr_dashboard,
    qr_finalize,
    qr_refresh_token,
)
