"""
FICHIER : apps/dashboard/views_admin_users.py
RESPONSABILITE : Re-export hub — gestion des utilisateurs (admin)

Organisation :
  views_admin_users_list.py     — liste, création, modification, audit
  views_admin_users_security.py — reset mot de passe, réinitialisation 2FA
  views_admin_users_delete.py   — suppression unitaire et en lot
"""

from apps.dashboard.views_admin_users_list import (  # noqa: F401
    admin_users,
    admin_user_create,
    admin_user_edit,
    admin_user_audit,
)
from apps.dashboard.views_admin_users_security import (  # noqa: F401
    admin_user_reset_password,
    admin_user_reset_2fa,
)
from apps.dashboard.views_admin_users_delete import (  # noqa: F401
    admin_users_delete_multiple,
    admin_user_delete,
)
