"""
Paquet de l'API REST pour le système de gestion des absences universitaires UniAbsences.

Ce paquet implémente la couche d'API REST publique construite sur
Django REST Framework (DRF). Il est monté sous le préfixe d'URL ``/api/``
défini dans ``config/urls.py`` et couvre tous les accès programmatiques aux
ressources principales du système.

Structure du paquet :
  __init__.py          — ce fichier ; marque le répertoire comme paquet Python.
  filters.py           — classes FilterSet django-filters pour le filtrage par
                         paramètre de requête sur chaque endpoint de ressource.
  pagination.py        — classe partagée StandardPagination utilisée par tous les ViewSets.
  permissions.py       — classes de permission DRF basées sur les rôles (IsAdmin,
                         IsSecretary, IsProfessor, IsStudent,
                         IsAdminOrSecretary, IsAdminOrSecretaryOrProfessor,
                         IsStaffOrReadOnly).
  throttles.py         — sous-classes UserRateThrottle par scope pour les endpoints
                         sensibles aux écritures (enregistrement d'absence, dépôt
                         de justification).
  urls.py              — configuration des URL : enregistrement du router DRF pour les
                         ViewSets CRUD plus les endpoints d'analytiques, d'export et
                         de notifications déclarés manuellement.
  serializers/         — sous-paquet regroupant les serializers DRF par module métier.
  views/               — sous-paquet regroupant les ViewSets DRF et les vues API par
                         module métier.

Fait partie du projet UniAbsences.
"""
