"""
URL configuration for the enrollments application.

Mounts enrollment management views and AJAX API endpoints under the
``enrollments`` namespace so they can be referenced in templates and
redirects as ``enrollments:<name>``.

Route map
---------
manager/                  — enrollment landing dashboard (secretary)
enroll/                   — enrollment form (GET + POST)
api/departments/          — AJAX: departments for a given faculty
api/courses/              — AJAX: active courses for a department
api/courses-by-year/      — AJAX: all active courses for an academic year
api/courses-by-student/   — AJAX: courses a student is enrolled in
rules/                    — absence threshold rules list (secretary)
rules/toggle/<pk>/        — grant or revoke an exemption (POST)

Belongs to: UniAbsences — enrollments app.
"""
from django.urls import path

from . import views, views_rules

app_name = "enrollments"

urlpatterns = [
    # ------------------------------------------------------------------ #
    # Enrollment management views                                          #
    # ------------------------------------------------------------------ #
    path("manager/", views.enrollment_manager, name="manager"),
    path("enroll/", views.enroll_student, name="enroll_student"),

    # ------------------------------------------------------------------ #
    # AJAX API endpoints (JSON, GET only)                                  #
    # ------------------------------------------------------------------ #
    path("api/departments/", views.get_departments, name="get_departments"),
    path("api/courses/", views.get_courses, name="get_courses"),
    path("api/courses-by-year/", views.get_courses_by_year, name="get_courses_by_year"),
    path(
        "api/courses-by-student/",
        views.get_courses_by_student,
        name="get_courses_by_student",
    ),

    # ------------------------------------------------------------------ #
    # Absence threshold rules & exemption management                       #
    # ------------------------------------------------------------------ #
    path("rules/", views_rules.rules_management, name="rules_management"),
    path(
        "rules/toggle/<int:pk>/", views_rules.toggle_exemption, name="toggle_exemption"
    ),
]
