"""
FICHIER : apps/dashboard/views_admin_settings.py
RESPONSABILITE : Re-export hub — paramètres système et journaux admin

Sous-modules :
  views_admin_settings_form.py — admin_settings (formulaire paramètres système)
  views_admin_audit.py         — admin_audit_logs, admin_export_audit_csv,
                                  admin_qr_scan_logs
"""

from apps.dashboard.views_admin_audit import (  # noqa: F401
    admin_audit_logs,
    admin_export_audit_csv,
    admin_qr_scan_logs,
)
from apps.dashboard.views_admin_settings_form import admin_settings  # noqa: F401
