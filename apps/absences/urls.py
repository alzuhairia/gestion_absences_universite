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
                 API d'historique des absences, encodage direct d'absence.
  - Admin/Sec  : modification directe d'absence.

Fait partie du système d'absences UniAbsences.
"""
from django.urls import path

from . import views

app_name = "absences"

urlpatterns = [
    # Détails des absences pour un cours spécifique (Vue Étudiant)
    path("details/<int:id_inscription>/", views.absence_details, name="details"),
    # Upload d'un justificatif (Action Étudiant)
    path("upload/<int:absence_id>/", views.upload_justification, name="upload"),
    # --- Actions Secrétariat / Admin ---
    path("validation/", views.validation_list, name="validation_list"),
    path(
        "process/<int:pk>/",
        views.process_justification,
        name="process_justification",
    ),
    path(
        "create-justified/",
        views.create_justified_absence,
        name="create_justified_absence",
    ),
    path(
        "justified-list/",
        views.justified_absences_list,
        name="justified_absences_list",
    ),
    path(
        "api/student-history/",
        views.student_absence_history_api,
        name="student_absence_history_api",
    ),
    # Modification/Surcharge d'absence
    path("edit/<int:pk>/", views.edit_absence, name="edit_absence"),
    # Telecharger un justificatif (acces controle)
    path(
        "justification/<int:justification_id>/download/",
        views.download_justification,
        name="download_justification",
    ),
    # --- Actions Professeur ---
    path("session/create/<int:course_id>/", views.session_create, name="session_create"),
    path("mark/<int:course_id>/", views.mark_absence, name="mark_absence"),
    path("mark/<int:course_id>/htmx/", views.mark_absence_htmx, name="mark_absence_htmx"),
    path(
        "review/<int:absence_id>/",
        views.review_justification,
        name="review_justification",
    ),
    path(
        "validate-session/<int:seance_id>/",
        views.validate_session,
        name="validate_session",
    ),
    # --- Présence par QR Code ---
    path("qr/generate/<int:course_id>/", views.qr_generate, name="qr_generate"),
    path("qr/dashboard/<uuid:token>/", views.qr_dashboard, name="qr_dashboard"),
    path("qr/refresh/<uuid:token>/", views.qr_refresh_token, name="qr_refresh_token"),
    path("qr/finalize/<uuid:token>/", views.qr_finalize, name="qr_finalize"),
    path("qr/scan/<uuid:token>/", views.qr_scan, name="qr_scan"),
]
