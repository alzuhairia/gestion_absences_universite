"""
Paquet d'application de messagerie pour le système UniAbsences.

Cette app fournit une messagerie interne de personne à personne entre les
utilisateurs de la plateforme (étudiants, professeurs, secrétaires et
administrateurs). Elle inclut :
  - Des vues boîte de réception et messages envoyés avec pagination
  - La composition de message avec filtrage des destinataires par rôle
  - Un context processor pour le compteur de non-lus du badge de la barre de navigation
  - L'invalidation du compteur de non-lus en cache au moment de la sauvegarde

Appartient à : UniAbsences — système de gestion des absences universitaires.
"""
