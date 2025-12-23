from django.urls import path
from . import views

app_name = 'messaging'

urlpatterns = [
    path('', views.inbox, name='index'), # Redirect default to inbox (or keep alias)
    path('inbox/', views.inbox, name='inbox'),
    path('sent/', views.sent_box, name='sent'),
    path('compose/', views.compose, name='compose'),
    path('message/<int:message_id>/', views.message_detail, name='detail'),
]