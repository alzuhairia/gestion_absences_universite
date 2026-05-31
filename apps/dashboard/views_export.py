"""
Concentrateur des vues d'export du tableau de bord pour le système UniAbsences.

Ce module sert de concentrateur de ré-exports qui agrège les deux vues d'export
concrètes dans un seul espace de noms d'import stable pour ``dashboard/urls.py``.
Aucune logique ne réside ici — chaque vue est implémentée dans son propre
sous-module dédié.

Responsabilités des sous-modules
--------------------------------
``views_export_pdf.py``
    ``export_student_pdf`` — génère un rapport d'absences PDF par étudiant en
    utilisant ReportLab. Accessible aux étudiants (leurs propres données
    uniquement), aux administrateurs et aux secrétaires.

``views_export_excel.py``
    ``export_at_risk_excel`` — génère un classeur openpyxl listant chaque
    étudiant dont le taux d'absence dépasse le seuil du cours pour l'année
    académique active. Réservé aux rôles administrateur et secrétaire.

Fait partie du système de tableau de bord UniAbsences.
"""

from .views_export_pdf import export_student_pdf  # noqa: F401
from .views_export_excel import export_at_risk_excel  # noqa: F401
