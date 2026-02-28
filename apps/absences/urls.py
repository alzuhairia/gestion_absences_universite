from django.urls import path
from . import views
from . import views_validation
from . import views_manager

app_name = 'absences'

urlpatterns = [
    # Détails des absences pour un cours spécifique (Vue Étudiant)
    path('details/<int:id_inscription>/', views.absence_details, name='details'),
    
    # Upload d'un justificatif (Action Étudiant)
    path('upload/<int:absence_id>/', views.upload_justification, name='upload'),
    
    # --- Actions Secrétariat / Admin ---
    path('validation/', views_validation.validation_list, name='validation_list'),
    path('process/<int:pk>/', views_validation.process_justification, name='process_justification'),
    path('create-justified/', views_validation.create_justified_absence, name='create_justified_absence'),
    path('justified-list/', views_validation.justified_absences_list, name='justified_absences_list'),
    path('api/student-history/', views_validation.student_absence_history_api, name='student_absence_history_api'),
    
    # Edit/Override Absence
    path('edit/<int:pk>/', views_manager.edit_absence, name='edit_absence'),

    # Valider un justificatif (Passe l'absence en JUSTIFIEE)
    path('valider/<int:absence_id>/', views.valider_justificatif, name='valider_justification'),
    
    # Refuser un justificatif (Remet l'absence en NON_JUSTIFIEE)
    path('refuser/<int:absence_id>/', views.refuser_justificatif, name='refuser_justification'),

    # Telecharger un justificatif (acces controle)
    path('justification/<int:justification_id>/download/', views.download_justification, name='download_justification'),

    # --- Actions Professeur ---
    path('mark/<int:course_id>/', views.mark_absence, name='mark_absence'),
    path('review/<int:absence_id>/', views.review_justification, name='review_justification'),
]
