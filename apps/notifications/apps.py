"""
Configuration de l'application Django pour l'app notifications.

Ce module définit la sous-classe ``AppConfig`` que Django utilise pour
initialiser l'application ``apps.notifications`` (envoi des emails
transactionnels — absence enregistrée, justification décidée, seuil
dépassé, résumé hebdomadaire, etc.).

Contrairement à d'autres apps du projet (ex. absences/accounts), aucun
module ``signals`` n'est branché ici : les emails sont déclenchés
explicitement par les services métier via ``email_core`` /
``email_builders``, donc aucun hook ``ready()`` n'est nécessaire.

Fait partie du système de gestion des absences UniAbsences.
"""
from django.apps import AppConfig


class NotificationsConfig(AppConfig):
    """AppConfig pour l'application notifications (emails transactionnels)."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.notifications"
