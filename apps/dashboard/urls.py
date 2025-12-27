from django.urls import path
from . import views
from . import views_export
from . import views_admin
from . import views_secretary

app_name = 'dashboard' # C'est ce mot-clé qui crée le préfixe "dashboard:"

urlpatterns = [
    # Routes existantes
    path('', views.dashboard_redirect, name='index'),
    path('student/', views.student_dashboard, name='student_dashboard'),
    path('instructor/', views.instructor_dashboard, name='instructor_dashboard'),
    path('admin/', views.admin_dashboard, name='admin_dashboard'),
    path('secretary/', views.secretary_dashboard, name='secretary_dashboard'),
    path('secretary/enrollments/', views.secretary_enrollments, name='secretary_enrollments'),
    path('secretary/rules-40/', views.secretary_rules_40, name='secretary_rules_40'),
    path('secretary/exports/', views.secretary_exports, name='secretary_exports'),
    path('secretary/audit-logs/', views_secretary.secretary_audit_logs, name='secretary_audit_logs'),
    
    path('student/stats/', views.student_statistics, name='student_statistics'),
    path('student/courses/', views.student_courses, name='student_courses'),
    path('student/absences/', views.student_absences, name='student_absences'),
    path('student/reports/', views.student_reports, name='student_reports'),
    
    # Active Courses Management (read-only view - moved to avoid conflict with secretary_courses)
    path('secretary/active-courses/', views.active_courses, name='active_courses'),
    
    # Instructor Pages
    path('instructor/courses/', views.instructor_courses, name='instructor_courses'),
    path('instructor/sessions/', views.instructor_sessions, name='instructor_sessions'),
    path('instructor/statistics/', views.instructor_statistics, name='instructor_statistics'),
    path('instructor/course/<int:course_id>/', views.instructor_course_detail, name='instructor_course_detail'),
    
    # Student Course Details
    path('student/course/<int:inscription_id>/', views.student_course_detail, name='student_course_detail'),

    # Exports
    path('export/student/pdf/', views_export.export_student_pdf, name='export_student_pdf'),
    path('export/secretary/excel/', views_export.export_at_risk_excel, name='export_at_risk_excel'),
    
    # ========== ADMINISTRATOR DASHBOARD ROUTES ==========
    # Academic Structure Management
    path('admin/faculties/', views_admin.admin_faculties, name='admin_faculties'),
    path('admin/faculties/<int:faculte_id>/edit/', views_admin.admin_faculty_edit, name='admin_faculty_edit'),
    path('admin/faculties/<int:faculte_id>/delete/', views_admin.admin_faculty_delete, name='admin_faculty_delete'),
    path('admin/departments/', views_admin.admin_departments, name='admin_departments'),
    path('admin/departments/<int:dept_id>/edit/', views_admin.admin_department_edit, name='admin_department_edit'),
    path('admin/departments/<int:dept_id>/delete/', views_admin.admin_department_delete, name='admin_department_delete'),
    path('admin/courses/', views_admin.admin_courses, name='admin_courses'),
    path('admin/courses/<int:course_id>/edit/', views_admin.admin_course_edit, name='admin_course_edit'),
    path('admin/courses/<int:course_id>/delete/', views_admin.admin_course_delete, name='admin_course_delete'),
    
    # User Management
    path('admin/users/', views_admin.admin_users, name='admin_users'),
    path('admin/users/create/', views_admin.admin_user_create, name='admin_user_create'),
    path('admin/users/delete-multiple/', views_admin.admin_users_delete_multiple, name='admin_users_delete_multiple'),
    path('admin/users/<int:user_id>/edit/', views_admin.admin_user_edit, name='admin_user_edit'),
    path('admin/users/<int:user_id>/delete/', views_admin.admin_user_delete, name='admin_user_delete'),
    path('admin/users/<int:user_id>/reset-password/', views_admin.admin_user_reset_password, name='admin_user_reset_password'),
    path('admin/users/<int:user_id>/audit/', views_admin.admin_user_audit, name='admin_user_audit'),
    
    # System Settings
    path('admin/settings/', views_admin.admin_settings, name='admin_settings'),
    
    # Academic Year Management
    path('admin/academic-years/', views_admin.admin_academic_years, name='admin_academic_years'),
    path('admin/academic-years/<int:year_id>/set-active/', views_admin.admin_academic_year_set_active, name='admin_academic_year_set_active'),
    path('admin/academic-years/<int:year_id>/delete/', views_admin.admin_academic_year_delete, name='admin_academic_year_delete'),
    
    # Audit Logs
    path('admin/audit-logs/', views_admin.admin_audit_logs, name='admin_audit_logs'),
    path('admin/audit-logs/export-csv/', views_admin.admin_export_audit_csv, name='admin_export_audit_csv'),
    
    # API pour les prérequis selon le niveau
    path('api/prerequisites-by-level/', views_admin.get_prerequisites_by_level, name='get_prerequisites_by_level'),
    
    # ========== SECRETARY ACADEMIC STRUCTURE MANAGEMENT ==========
    # Academic Structure Management (same as admin but for secretary)
    path('secretary/faculties/', views_secretary.secretary_faculties, name='secretary_faculties'),
    path('secretary/faculties/<int:faculte_id>/edit/', views_secretary.secretary_faculty_edit, name='secretary_faculty_edit'),
    path('secretary/faculties/<int:faculte_id>/delete/', views_secretary.secretary_faculty_delete, name='secretary_faculty_delete'),
    path('secretary/departments/', views_secretary.secretary_departments, name='secretary_departments'),
    path('secretary/departments/<int:dept_id>/edit/', views_secretary.secretary_department_edit, name='secretary_department_edit'),
    path('secretary/departments/<int:dept_id>/delete/', views_secretary.secretary_department_delete, name='secretary_department_delete'),
    path('secretary/courses/', views_secretary.secretary_courses, name='secretary_courses'),
    path('secretary/courses/<int:course_id>/edit/', views_secretary.secretary_course_edit, name='secretary_course_edit'),
    path('secretary/courses/<int:course_id>/delete/', views_secretary.secretary_course_delete, name='secretary_course_delete'),
    path('secretary/academic-years/', views_secretary.secretary_academic_years, name='secretary_academic_years'),
    path('secretary/academic-years/<int:year_id>/set-active/', views_secretary.secretary_academic_year_set_active, name='secretary_academic_year_set_active'),
    path('secretary/academic-years/<int:year_id>/delete/', views_secretary.secretary_academic_year_delete, name='secretary_academic_year_delete'),
]