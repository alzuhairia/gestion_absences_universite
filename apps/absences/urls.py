"""
Configuration des URL du système d'absences UniAbsences.

Tous les motifs d'URL de ce fichier sont montés sous le préfixe ``absences/``
défini dans le ``config/urls.py`` racine.  L'espace de noms
``app_name = "absences"`` permet aux autres parties du projet de résoudre
ces URL en utilisant le préfixe ``absences:``.

Regroupés par rôle :
  - Étudiant   : page de détails d'absence, upload/téléchargement de justificatif.
  - Professeur : création de séance, marquage manuel de présence (formulaire + HTMX).
  - Système QR : génération QR, tableau de bord, rafraîchissement du jeton, finalisation, scan étudiant.
  - Secrétaire : examen des justificatifs, traitement (approbation/rejet), liste encodée,
                 API d'historique des absences, encodage direct d'absence,
                 édition directe d'un enregistrement d'absence.

Repérage rapide du code source
------------------------------
Chaque route est précédée d'un commentaire ``# → views/<fichier>.py``
indiquant le sous-module qui définit réellement la vue.  ``views.<nom>``
masque le fichier source par la ré-exportation effectuée dans
``views/__init__.py`` ; ces commentaires évitent toute recherche.

Fait partie du système d'absences UniAbsences.
"""
from django.urls import path

from . import views

app_name = "absences"

urlpatterns = [
    # ------------------------------------------------------------------ #
    # Étudiant                                                           #
    # ------------------------------------------------------------------ #

    # → views/student_views.py
    # Détails des absences pour un cours spécifique.
    path("details/<int:id_inscription>/", views.absence_details, name="details"),

    # → views/student_views.py
    # Upload d'un justificatif par l'étudiant.
    path("upload/<int:absence_id>/", views.upload_justification, name="upload"),

    # → views/student_views.py
    # Téléchargement d'un justificatif (accès contrôlé).
    path(
        "justification/<int:justification_id>/download/",
        views.download_justification,
        name="download_justification",
    ),

    # ------------------------------------------------------------------ #
    # Secrétariat — traitement des justificatifs                         #
    # ------------------------------------------------------------------ #

    # → views/secretary_justification.py
    path("validation/", views.validation_list, name="validation_list"),

    # → views/secretary_justification.py
    path(
        "process/<int:pk>/",
        views.process_justification,
        name="process_justification",
    ),

    # → views/secretary_justification.py
    path(
        "justified-list/",
        views.justified_absences_list,
        name="justified_absences_list",
    ),

    # → views/secretary_justification.py
    path(
        "review/<int:absence_id>/",
        views.review_justification,
        name="review_justification",
    ),

    # ------------------------------------------------------------------ #
    # Secrétariat — encodage et édition directe                          #
    # ------------------------------------------------------------------ #

    # → views/secretary_absence_encoding.py
    path(
        "create-justified/",
        views.create_justified_absence,
        name="create_justified_absence",
    ),

    # → views/secretary_absence_encoding.py
    # API JSON appelée par la page d'encodage du secrétariat pour afficher
    # l'historique récent de l'étudiant sélectionné.
    path(
        "api/student-history/",
        views.secretary_student_history_api,
        name="secretary_student_history_api",
    ),

    # → views/secretary_absence_edit.py
    # Modification directe d'un enregistrement d'absence (motif d'audit obligatoire).
    path("edit/<int:pk>/", views.edit_absence, name="edit_absence"),

    # ------------------------------------------------------------------ #
    # Professeur                                                         #
    # ------------------------------------------------------------------ #

    # → views/professor_session.py
    path("session/create/<int:course_id>/", views.session_create, name="session_create"),

    # → views/professor_attendance_form.py
    path("mark/<int:course_id>/", views.mark_absence, name="mark_absence"),

    # → views/professor_attendance_htmx.py
    path("mark/<int:course_id>/htmx/", views.mark_absence_htmx, name="mark_absence_htmx"),

    # → views/professor_session.py
    path(
        "validate-session/<int:seance_id>/",
        views.validate_session,
        name="validate_session",
    ),

    # ------------------------------------------------------------------ #
    # Présence par QR Code                                               #
    # ------------------------------------------------------------------ #

    # → views/qr_professor.py
    path("qr/generate/<int:course_id>/", views.qr_generate, name="qr_generate"),

    # → views/qr_professor.py
    path("qr/dashboard/<uuid:token>/", views.qr_dashboard, name="qr_dashboard"),

    # → views/qr_professor.py
    path("qr/refresh/<uuid:token>/", views.qr_refresh_token, name="qr_refresh_token"),

    # → views/qr_professor.py
    path("qr/finalize/<uuid:token>/", views.qr_finalize, name="qr_finalize"),

    # → views/qr_student.py
    path("qr/scan/<uuid:token>/", views.qr_scan, name="qr_scan"),
]
