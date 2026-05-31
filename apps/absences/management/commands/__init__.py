"""Commandes ``manage.py`` propres à l'app absences.

Chaque module ici déclare une classe ``Command`` héritant de
``BaseCommand`` et devient invocable via ``python manage.py <nom_module>``.

Exemples actuels :
    - cleanup_qr_logs : purge des journaux QR expirés
    - migrate_justification_documents : migration des fichiers de
      justification vers le nouveau stockage
"""
