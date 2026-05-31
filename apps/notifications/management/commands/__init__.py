"""Commandes ``manage.py`` propres à l'app notifications.

Exemple : ``send_weekly_summary`` — agrège les évènements de la semaine
et envoie le résumé par email aux secrétariats. Conçu pour être appelé
par un planificateur (cron / Celery beat / Task Scheduler).
"""
