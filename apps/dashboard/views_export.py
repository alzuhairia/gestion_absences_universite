"""
FICHIER : apps/dashboard/views_export.py
RESPONSABILITE : Re-export hub — compatibilité ascendante avec urls.py

  views_export_pdf.py   — export_student_pdf   (rapport PDF assiduité)
  views_export_excel.py — export_at_risk_excel (liste Excel à risque)
"""

from .views_export_pdf import export_student_pdf  # noqa: F401
from .views_export_excel import export_at_risk_excel  # noqa: F401
