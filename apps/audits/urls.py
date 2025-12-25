from django.urls import path
from . import views

app_name = 'audits'

urlpatterns = [
    path('logs/', views.audit_list, name='audit_list'),
]