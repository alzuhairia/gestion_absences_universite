from django.contrib import admin
from django.urls import path, include
from django.shortcuts import redirect
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('admin/', admin.site.urls),
    
    # Endpoint de santé pour le monitoring (app health dédiée)
    path('api/', include('apps.health.urls')),
    
    # On utilise simplement include(). 
    # Le namespace sera géré par la variable app_name dans chaque dossier urls.py
    path('accounts/', include('apps.accounts.urls')),
    path('academics/', include('apps.academics.urls')),
    path('enrollments/', include('apps.enrollments.urls')),
    path('absences/', include('apps.absences.urls')),
    path('messaging/', include('apps.messaging.urls')),
    path('dashboard/', include('apps.dashboard.urls')),
    
    # N'oublie pas l'application qu'on a renommée pour éviter le conflit !
    # N'oublie pas l'application qu'on a renommée pour éviter le conflit !
    path('sessions/', include('apps.academic_sessions.urls')),
    path('audits/', include('apps.audits.urls')),
    path('', lambda request: redirect('dashboard/', permanent=False)),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)