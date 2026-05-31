"""
Hub public de ré-export pour tous les modèles liés aux absences.

Ce module fournit un point d'import unique pour tous les modèles définis dans
l'application absences. Le code interne est réparti en deux sous-modules :

  models_absence.py — Absence, Justification (modèles métier principaux)
  models_qr.py      — QRAttendanceToken, QRScanRecord, QRScanLog (présence QR)

Tous les modèles restent importables depuis ``apps.absences.models`` pour la
compatibilité avec les conventions ORM standard de Django et les outils tiers.

Responsabilités :
  - Ré-exporter chaque modèle absences sous un namespace canonique unique.

Fait partie du système de gestion des absences UniAbsences.
"""
from apps.absences.models_absence import Absence, Justification  # noqa: F401
from apps.absences.models_qr import QRAttendanceToken, QRScanLog, QRScanRecord  # noqa: F401
