"""
Configuration des URL pour la messagerie interne UniAbsences.

Monte les vues de boîte de réception, boîte d'envoi, composition et
affichage détaillé d'un message sous le préfixe ``messaging/`` défini
dans ``config/urls.py``. L'espace de noms ``app_name = "messaging"``
permet la résolution inverse via ``messaging:<nom>``.

Repérage rapide du code source
------------------------------
Chaque route est précédée d'un commentaire ``# → <fichier>.py`` indiquant
le sous-module qui définit la vue.

Fait partie du système de messagerie UniAbsences.
"""
from django.urls import path

from . import views

app_name = "messaging"

urlpatterns = [
    # → views.py (inbox) — redirection par défaut vers la boîte de réception
    path("", views.inbox, name="index"),

    # → views.py (inbox)
    path("inbox/", views.inbox, name="inbox"),

    # → views.py (sent_box)
    path("sent/", views.sent_box, name="sent"),

    # → views.py (compose)
    path("compose/", views.compose, name="compose"),

    # → views.py (message_detail)
    path("message/<int:message_id>/", views.message_detail, name="detail"),
]
