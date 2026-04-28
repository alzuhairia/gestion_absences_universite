"""
FICHIER : apps/absences/views/qr_views.py
RESPONSABILITE : Re-export centralisé du système QR code de présence.

Organisation :
  qr_utils.py    — helpers GPS, génération QR, logging (partagés par les deux fichiers)
  qr_professor.py — qr_generate, qr_dashboard, qr_refresh_token, qr_finalize
  qr_student.py  — qr_scan (scan étudiant avec anti-fraude GPS)
"""

from .qr_professor import (  # noqa: F401
    qr_dashboard,
    qr_finalize,
    qr_generate,
    qr_refresh_token,
)
from .qr_student import qr_scan  # noqa: F401
