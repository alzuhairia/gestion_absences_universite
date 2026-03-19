# Re-export all admin views from sub-modules for backward compatibility.
# New code should import from the specific sub-module directly.

from apps.dashboard.views_admin_stats import (  # noqa: F401
    admin_dashboard_main,
    admin_statistics,
    is_admin,
)

from apps.dashboard.views_admin_courses import (  # noqa: F401
    admin_academic_year_delete,
    admin_academic_year_set_active,
    admin_academic_years,
    admin_course_delete,
    admin_course_edit,
    admin_courses,
    admin_department_delete,
    admin_department_edit,
    admin_departments,
    admin_faculties,
    admin_faculty_delete,
    admin_faculty_edit,
    get_prerequisites_by_level,
)

from apps.dashboard.views_admin_users import (  # noqa: F401
    admin_user_audit,
    admin_user_create,
    admin_user_delete,
    admin_user_edit,
    admin_user_reset_password,
    admin_users,
    admin_users_delete_multiple,
)

from apps.dashboard.views_admin_settings import (  # noqa: F401
    admin_audit_logs,
    admin_export_audit_csv,
    admin_qr_scan_logs,
    admin_settings,
)
