# apps/academic_sessions/apps.py
from django.apps import AppConfig

class AcademicSessionsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.academic_sessions'
    label = 'academic_sessions'  # <--- C'est ce label qui règle le conflit
    verbose_name = 'Sessions Académiques'