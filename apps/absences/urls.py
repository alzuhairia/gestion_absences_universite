from django.urls import path
from . import views

app_name = 'absences'

urlpatterns = [
    # Détails des absences pour un cours spécifique (Vue Étudiant)
    path('details/<int:id_inscription>/', views.absence_details, name='details'),
    
    # Upload d'un justificatif (Action Étudiant)
    path('upload/<int:absence_id>/', views.upload_justification, name='upload'),
    
    # --- Actions Secrétariat / Admin ---
    
    # Valider un justificatif (Passe l'absence en JUSTIFIEE)
    path('valider/<int:absence_id>/', views.valider_justificatif, name='valider_justification'),
    
    # Refuser un justificatif (Remet l'absence en NON_JUSTIFIEE)
    path('refuser/<int:absence_id>/', views.refuser_justificatif, name='refuser_justification'),
]