from django.urls import path
from . import views
from . import views_rules

app_name = 'enrollments'

urlpatterns = [
    path('manager/', views.enrollment_manager, name='manager'),
    path('enroll/', views.enroll_student, name='enroll_student'),
    path('api/departments/', views.get_departments, name='get_departments'),
    path('api/courses/', views.get_courses, name='get_courses'),
    
    # Rules Management
    path('rules/', views_rules.rules_management, name='rules_management'),
    path('rules/toggle/<int:pk>/', views_rules.toggle_exemption, name='toggle_exemption'),
]