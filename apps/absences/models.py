"""
Hub — re-exporte tous les modèles absences depuis leurs sous-fichiers.
  models_absence.py : Absence, Justification
  models_qr.py      : QRAttendanceToken, QRScanRecord, QRScanLog
"""
from apps.absences.models_absence import Absence, Justification  # noqa: F401
from apps.absences.models_qr import QRAttendanceToken, QRScanLog, QRScanRecord  # noqa: F401
