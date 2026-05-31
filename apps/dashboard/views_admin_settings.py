"""
Concentrateur des paramètres administrateur pour le tableau de bord UniAbsences.

Concentrateur de réexport qui agrège la vue du formulaire des paramètres système et les
vues du journal d'audit dans un seul espace de noms pour ``dashboard/urls.py``.

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
