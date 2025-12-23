from django.urls import path
from . import views

app_name = 'dashboard' # C'est ce mot-clé qui crée le préfixe "dashboard:"

urlpatterns = [
    path('', views.dashboard_redirect, name='index'),
    path('statistics/', views.student_statistics, name='statistics'),
]