"""
Configuration des URL de l'application « enrollments ».

Monte les vues de gestion des inscriptions ainsi que les points d'API AJAX
sous l'espace de noms ``enrollments`` afin qu'ils puissent être référencés
dans les templates et les redirections via ``enrollments:<nom>``.

Carte des routes
----------------
manager/                  — tableau de bord des inscriptions (secrétariat)
enroll/                   — formulaire d'inscription (GET + POST)
api/departments/          — AJAX : départements d'une faculté donnée
api/courses/              — AJAX : cours actifs d'un département
api/courses-by-year/      — AJAX : tous les cours actifs d'une année académique
api/courses-by-student/   — AJAX : cours auxquels un étudiant est inscrit
rules/                    — liste des règles de seuil d'absences (secrétariat)
rules/toggle/<pk>/        — accorder ou retirer une exemption (POST)

Repérage rapide du code source
------------------------------
Chaque route est précédée d'un commentaire ``# → <fichier>.py`` indiquant
le sous-module qui définit réellement la vue.  ``views.<nom>`` masque le
fichier source par la ré-exportation effectuée dans ``views.py`` ; ces
commentaires évitent toute recherche.

Appartient à : UniAbsences — application « enrollments ».
"""
from django.urls import path

from . import views, views_rules

app_name = "enrollments"

urlpatterns = [
    # ------------------------------------------------------------------ #
    # Vues de gestion des inscriptions                                     #
    # ------------------------------------------------------------------ #

    # → enrollment_views.py
    path("manager/", views.enrollment_manager, name="manager"),

    # → enrollment_views.py
    path("enroll/", views.enroll_student, name="enroll_student"),

    # ------------------------------------------------------------------ #
    # Points d'API AJAX (JSON, GET uniquement)                             #
    # ------------------------------------------------------------------ #

    # → enrollment_api.py
    path("api/departments/", views.get_departments, name="get_departments"),

    # → enrollment_api.py
    path("api/courses/", views.get_courses, name="get_courses"),

    # → enrollment_api.py
    path("api/courses-by-year/", views.get_courses_by_year, name="get_courses_by_year"),

    # → enrollment_api.py
    path(
        "api/courses-by-student/",
        views.get_courses_by_student,
        name="get_courses_by_student",
    ),

    # ------------------------------------------------------------------ #
    # Règles de seuil d'absences et gestion des exemptions                 #
    # ------------------------------------------------------------------ #

    # → views_rules.py
    path("rules/", views_rules.rules_management, name="rules_management"),

    # → views_rules.py
    path(
        "rules/toggle/<int:pk>/", views_rules.toggle_exemption, name="toggle_exemption"
    ),
]
