"""
Configuration des URL pour l'application academics d'UniAbsences.

Aucune vue n'est servie directement depuis cette application ; toute la
gestion de la structure académique (facultés, départements, cours) est
prise en charge par les vues de l'application ``dashboard`` montées sous
``dashboard/``. Ce fichier existe pour satisfaire l'appel ``include()``
de Django et enregistrer l'espace de noms app_name ``academics``.

Partie de la structure académique d'UniAbsences.
"""

app_name = "academics"

urlpatterns = []
