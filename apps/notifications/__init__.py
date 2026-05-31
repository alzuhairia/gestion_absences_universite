"""
Paquet d'application notifications pour le système UniAbsences.

Cette app gère deux canaux de notification distincts :

1. Notifications in-app (modèle ``Notification``) — stockées en base de données
   et affichées aux utilisateurs au sein de l'interface de la plateforme.

2. Notifications par email — envoyées via le backend mail de Django avec :
   - Des helpers d'envoi synchrone unitaire/en masse (``email_core``)
   - Un envoi asynchrone fire-and-forget via un pool de threads borné
   - Une garde de deduplication (``EmailLog``) pour empêcher les emails
     en doublon dans une fenêtre de cooldown configurable
   - Des constructeurs d'emails typés pour chaque scénario de notification
     (``email_builders``)

Appartient à : UniAbsences — système de gestion des absences universitaires.
"""
