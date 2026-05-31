"""
Configuration des URL pour l'application academic_sessions d'UniAbsences.

Aucune vue n'est servie directement depuis cette application ; la gestion
des années académiques et des séances est assurée par les vues de
l'application ``dashboard``. Ce fichier existe pour satisfaire l'appel
``include()`` de Django et enregistrer le namespace ``app_name``
``academic_sessions``.

Fait partie de la structure académique d'UniAbsences.
"""

app_name = "academic_sessions"

urlpatterns = []
