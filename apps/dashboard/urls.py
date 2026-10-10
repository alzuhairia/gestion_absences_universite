"""
Configuration des URL pour le tableau de bord UniAbsences.

Tous les motifs d'URL de ce fichier sont montés sous le préfixe
``dashboard/`` défini dans le ``config/urls.py`` racine.  L'espace de
noms ``app_name = "dashboard"`` permet la résolution inverse avec le
préfixe ``dashboard:``.

Les URL sont regroupées par rôle :
  - Partagé    : index (redirection de répartition selon le rôle).
  - Admin      : tableau de bord principal, statistiques, utilisateurs,
                 facultés, départements, cours, années académiques,
                 prérequis, paramètres, audit.
  - Secrétaire : tableau de bord, cours actifs, inscriptions, seuils,
                 exports, CRUD facultés/départements, audit.
  - Professeur : tableau de bord, liste/détail des cours, séances.
  - Étudiant   : tableau de bord, statistiques, cours, absences, rapports PDF.
  - Exports    : rapport PDF (rendu via template), Excel des étudiants à risque.

Repérage rapide du code source
------------------------------
Chaque route est précédée d'un commentaire ``# → <fichier>.py`` indiquant
le sous-module qui définit réellement la vue.  Les quatre modules
``views``, ``views_admin``, ``views_export`` et ``views_secretary``
sont des hubs de ré-exportation ; ces commentaires évitent toute
recherche dans les hubs.

Fait partie du système de tableau de bord UniAbsences.
"""
from django.urls import path

from . import views, views_admin, views_export, views_secretary

app_name = "dashboard"  # C'est ce mot-clé qui crée le préfixe "dashboard:"

urlpatterns = [
    # ------------------------------------------------------------------ #
    # Partagé — redirection par rôle                                     #
    # ------------------------------------------------------------------ #

    # → views.py (dashboard_redirect)
    path("", views.dashboard_redirect, name="index"),

    # ------------------------------------------------------------------ #
    # Étudiant                                                           #
    # ------------------------------------------------------------------ #

    # → views_student.py (via hub views.py)
    path("student/", views.student_dashboard, name="student_dashboard"),

    # → views_student.py (via hub views.py)
    path("student/stats/", views.student_statistics, name="student_statistics"),

    # → views_student.py (via hub views.py)
    path("student/courses/", views.student_courses, name="student_courses"),

    # → views_student.py (via hub views.py)
    path("student/absences/", views.student_absences, name="student_absences"),

    # → views_student.py (via hub views.py)
    path("student/reports/", views.student_reports, name="student_reports"),

    # → views_student.py (via hub views.py)
    path(
        "student/course/<int:inscription_id>/",
        views.student_course_detail,
        name="student_course_detail",
    ),

    # ------------------------------------------------------------------ #
    # Professeur                                                         #
    # ------------------------------------------------------------------ #

    # → views_professor.py (via hub views.py)
    path("instructor/", views.instructor_dashboard, name="instructor_dashboard"),

    # → views_professor.py (via hub views.py)
    path("instructor/courses/", views.instructor_courses, name="instructor_courses"),

    # → views_professor.py (via hub views.py)
    path("instructor/sessions/", views.instructor_sessions, name="instructor_sessions"),

    # → views_professor.py (via hub views.py)
    path(
        "instructor/statistics/",
        views.instructor_statistics,
        name="instructor_statistics",
    ),

    # → views_professor.py (via hub views.py)
    path(
        "instructor/course/<int:course_id>/",
        views.instructor_course_detail,
        name="instructor_course_detail",
    ),

    # ------------------------------------------------------------------ #
    # Secrétariat — accueil, inscriptions, seuils, exports               #
    # ------------------------------------------------------------------ #

    # → views_secretary_home.py (via hub views.py)
    path("secretary/", views.secretary_dashboard, name="secretary_dashboard"),

    # → views_secretary_home.py (via hub views.py)
    path(
        "secretary/enrollments/",
        views.secretary_enrollments,
        name="secretary_enrollments",
    ),

    # → views_secretary_home.py (via hub views.py)
    path(
        "secretary/seuils-absence/",
        views.secretary_seuils_absence,
        name="secretary_seuils_absence",
    ),

    # → views_secretary_home.py (via hub views.py)
    path("secretary/exports/", views.secretary_exports, name="secretary_exports"),

    # → views_secretary_home.py (via hub views.py)
    # Vue en lecture seule déplacée pour éviter le conflit avec secretary_courses.
    path("secretary/active-courses/", views.active_courses, name="active_courses"),

    # → views_secretary_audit.py (via hub views_secretary.py)
    path(
        "secretary/audit-logs/",
        views_secretary.secretary_audit_logs,
        name="secretary_audit_logs",
    ),

    # ------------------------------------------------------------------ #
    # Admin — tableau de bord principal (dispatch)                       #
    # ------------------------------------------------------------------ #

    # → views.py (admin_dashboard — dispatch vers admin_dashboard_main ou vue secrétariat)
    path("admin/", views.admin_dashboard, name="admin_dashboard"),

    # ------------------------------------------------------------------ #
    # Admin — statistiques avancées                                      #
    # ------------------------------------------------------------------ #

    # → views_admin_stats.py (via hub views_admin.py)
    path("admin/statistics/", views_admin.admin_statistics, name="admin_statistics"),

    # ------------------------------------------------------------------ #
    # Admin — gestion de la structure académique                         #
    # ------------------------------------------------------------------ #

    # → views_admin_faculties.py (via hub views_admin.py)
    path("admin/faculties/", views_admin.admin_faculties, name="admin_faculties"),

    # → views_admin_faculties.py (via hub views_admin.py)
    path(
        "admin/faculties/<int:faculte_id>/edit/",
        views_admin.admin_faculty_edit,
        name="admin_faculty_edit",
    ),

    # → views_admin_faculties.py (via hub views_admin.py)
    path(
        "admin/faculties/<int:faculte_id>/delete/",
        views_admin.admin_faculty_delete,
        name="admin_faculty_delete",
    ),

    # → views_admin_departments.py (via hub views_admin.py)
    path("admin/departments/", views_admin.admin_departments, name="admin_departments"),

    # → views_admin_departments.py (via hub views_admin.py)
    path(
        "admin/departments/<int:dept_id>/edit/",
        views_admin.admin_department_edit,
        name="admin_department_edit",
    ),

    # → views_admin_departments.py (via hub views_admin.py)
    path(
        "admin/departments/<int:dept_id>/delete/",
        views_admin.admin_department_delete,
        name="admin_department_delete",
    ),

    # → views_admin_courses.py (via hub views_admin.py)
    path("admin/courses/", views_admin.admin_courses, name="admin_courses"),

    # → views_admin_courses.py (via hub views_admin.py)
    path(
        "admin/courses/<int:course_id>/edit/",
        views_admin.admin_course_edit,
        name="admin_course_edit",
    ),

    # → views_admin_courses.py (via hub views_admin.py)
    path(
        "admin/courses/<int:course_id>/delete/",
        views_admin.admin_course_delete,
        name="admin_course_delete",
    ),

    # → views_admin_courses.py (via hub views_admin.py)
    path(
        "admin/courses/delete-multiple/",
        views_admin.admin_courses_delete_multiple,
        name="admin_courses_delete_multiple",
    ),

    # ------------------------------------------------------------------ #
    # Admin — gestion des utilisateurs                                   #
    # ------------------------------------------------------------------ #

    # → views_admin_users.py (via hub views_admin.py)
    path("admin/users/", views_admin.admin_users, name="admin_users"),

    # → views_admin_users.py (via hub views_admin.py)
    path(
        "admin/users/create/", views_admin.admin_user_create, name="admin_user_create"
    ),

    # → views_admin_users.py (via hub views_admin.py)
    path(
        "admin/users/delete-multiple/",
        views_admin.admin_users_delete_multiple,
        name="admin_users_delete_multiple",
    ),

    # → views_admin_users.py (via hub views_admin.py)
    path(
        "admin/users/<int:user_id>/edit/",
        views_admin.admin_user_edit,
        name="admin_user_edit",
    ),

    # → views_admin_users.py (via hub views_admin.py)
    path(
        "admin/users/<int:user_id>/delete/",
        views_admin.admin_user_delete,
        name="admin_user_delete",
    ),

    # → views_admin_users.py (via hub views_admin.py)
    path(
        "admin/users/<int:user_id>/reset-password/",
        views_admin.admin_user_reset_password,
        name="admin_user_reset_password",
    ),

    # → views_admin_users.py (via hub views_admin.py)
    path(
        "admin/users/<int:user_id>/reset-2fa/",
        views_admin.admin_user_reset_2fa,
        name="admin_user_reset_2fa",
    ),

    # → views_admin_users.py (via hub views_admin.py)
    path(
        "admin/users/<int:user_id>/audit/",
        views_admin.admin_user_audit,
        name="admin_user_audit",
    ),

    # ------------------------------------------------------------------ #
    # Admin — paramètres système                                         #
    # ------------------------------------------------------------------ #

    # → views_admin_settings.py (via hub views_admin.py)
    path("admin/settings/", views_admin.admin_settings, name="admin_settings"),

    # ------------------------------------------------------------------ #
    # Admin — années académiques                                         #
    # ------------------------------------------------------------------ #

    # → views_admin_academic_years.py (via hub views_admin.py)
    path(
        "admin/academic-years/",
        views_admin.admin_academic_years,
        name="admin_academic_years",
    ),

    # → views_admin_academic_years.py (via hub views_admin.py)
    path(
        "admin/academic-years/<int:year_id>/set-active/",
        views_admin.admin_academic_year_set_active,
        name="admin_academic_year_set_active",
    ),

    # → views_admin_academic_years.py (via hub views_admin.py)
    path(
        "admin/academic-years/<int:year_id>/delete/",
        views_admin.admin_academic_year_delete,
        name="admin_academic_year_delete",
    ),

    # ------------------------------------------------------------------ #
    # Admin — audit et logs                                              #
    # ------------------------------------------------------------------ #

    # → views_admin_settings.py (via hub views_admin.py)
    path("admin/audit-logs/", views_admin.admin_audit_logs, name="admin_audit_logs"),

    # → views_admin_settings.py (via hub views_admin.py)
    path(
        "admin/audit-logs/export-csv/",
        views_admin.admin_export_audit_csv,
        name="admin_export_audit_csv",
    ),

    # → views_admin_settings.py (via hub views_admin.py)
    path(
        "admin/qr-scan-logs/",
        views_admin.admin_qr_scan_logs,
        name="admin_qr_scan_logs",
    ),

    # ------------------------------------------------------------------ #
    # Admin — API prérequis par niveau                                   #
    # ------------------------------------------------------------------ #

    # → views_admin_prerequisites.py (via hub views_admin.py)
    path(
        "api/prerequisites-by-level/",
        views_admin.get_prerequisites_by_level,
        name="get_prerequisites_by_level",
    ),

    # ------------------------------------------------------------------ #
    # Secrétariat — gestion de la structure académique                   #
    # (CRUD identique à l'admin mais sous le préfixe secretary/)         #
    # ------------------------------------------------------------------ #

    # → views_secretary_faculties.py (via hub views_secretary.py)
    path(
        "secretary/faculties/",
        views_secretary.secretary_faculties,
        name="secretary_faculties",
    ),

    # → views_secretary_faculties.py (via hub views_secretary.py)
    path(
        "secretary/faculties/<int:faculte_id>/edit/",
        views_secretary.secretary_faculty_edit,
        name="secretary_faculty_edit",
    ),

    # → views_secretary_faculties.py (via hub views_secretary.py)
    path(
        "secretary/faculties/<int:faculte_id>/delete/",
        views_secretary.secretary_faculty_delete,
        name="secretary_faculty_delete",
    ),

    # → views_secretary_departments.py (via hub views_secretary.py)
    path(
        "secretary/departments/",
        views_secretary.secretary_departments,
        name="secretary_departments",
    ),

    # → views_secretary_departments.py (via hub views_secretary.py)
    path(
        "secretary/departments/<int:dept_id>/edit/",
        views_secretary.secretary_department_edit,
        name="secretary_department_edit",
    ),

    # → views_secretary_departments.py (via hub views_secretary.py)
    path(
        "secretary/departments/<int:dept_id>/delete/",
        views_secretary.secretary_department_delete,
        name="secretary_department_delete",
    ),

    # → views_secretary_courses.py (via hub views_secretary.py)
    path(
        "secretary/courses/",
        views_secretary.secretary_courses,
        name="secretary_courses",
    ),

    # → views_secretary_courses.py (via hub views_secretary.py)
    path(
        "secretary/courses/<int:course_id>/edit/",
        views_secretary.secretary_course_edit,
        name="secretary_course_edit",
    ),

    # → views_secretary_courses.py (via hub views_secretary.py)
    path(
        "secretary/courses/<int:course_id>/delete/",
        views_secretary.secretary_course_delete,
        name="secretary_course_delete",
    ),

    # → views_secretary_courses.py (via hub views_secretary.py)
    path(
        "secretary/courses/delete-multiple/",
        views_secretary.secretary_courses_delete_multiple,
        name="secretary_courses_delete_multiple",
    ),

    # → views_secretary_academic_years.py (via hub views_secretary.py)
    path(
        "secretary/academic-years/",
        views_secretary.secretary_academic_years,
        name="secretary_academic_years",
    ),

    # → views_secretary_academic_years.py (via hub views_secretary.py)
    path(
        "secretary/academic-years/<int:year_id>/set-active/",
        views_secretary.secretary_academic_year_set_active,
        name="secretary_academic_year_set_active",
    ),

    # → views_secretary_academic_years.py (via hub views_secretary.py)
    path(
        "secretary/academic-years/<int:year_id>/delete/",
        views_secretary.secretary_academic_year_delete,
        name="secretary_academic_year_delete",
    ),

    # ------------------------------------------------------------------ #
    # Exports — PDF (template) et Excel (étudiants à risque)             #
    # ------------------------------------------------------------------ #

    # → views_export_pdf.py (via hub views_export.py)
    path(
        "export/student/pdf/",
        views_export.export_student_pdf,
        name="export_student_pdf",
    ),

    # → views_export_excel.py (via hub views_export.py)
    path(
        "export/secretary/excel/",
        views_export.export_at_risk_excel,
        name="export_at_risk_excel",
    ),
]
