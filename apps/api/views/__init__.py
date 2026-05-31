"""
Package des vues de l'API REST pour le système de gestion des absences universitaires UniAbsences.

Ce package regroupe tous les ViewSets DRF et les vues d'API basées sur des
fonctions par module de domaine. Chaque sous-module possède la logique de vue
pour un seul type de ressource ou domaine fonctionnel, gardant chaque fichier
ciblé et testable indépendamment.

Disposition des modules :
  student_viewset.py       — StudentViewSet : CRUD pour les comptes utilisateur
                             étudiants (ETUDIANT) avec prise en charge de la
                             suppression douce.
  course_viewset.py        — CoursViewSet : CRUD pour les cours ; retourne une
                             réponse de détail enrichie (séances + prérequis)
                             lors du retrieve.
  enrollment_viewset.py    — InscriptionViewSet : CRUD pour les inscriptions
                             des étudiants avec filtrage du queryset selon le
                             rôle.
  absence_viewset.py       — AbsenceViewSet : CRUD pour les enregistrements
                             d'absence ; les opérations d'écriture sont limitées
                             en débit et restreintes au professeur.
  justification_viewset.py — JustificationViewSet : soumission de justification
                             par l'étudiant plus le flux d'approbation
                             admin/secrétaire avec notifications par email.
  notification_viewset.py  — NotificationViewSet : opérations de liste et de
                             marquage comme lu sur les notifications de
                             l'utilisateur.
  analytics_views.py       — dashboard_analytics et statistics_analytics :
                             endpoints JSON réservés aux administrateurs pour
                             les KPIs du tableau de bord et les données de
                             graphiques.
  export_views.py          — export_student_pdf_api et
                             export_at_risk_excel_api : génération à la volée
                             de fichiers PDF/Excel pour les rapports d'absences.

Tous les symboles sont ré-exportés depuis ce ``__init__.py`` afin que
``urls.py`` puisse tout importer via une seule instruction
``from . import views``.

Partie de l'API REST UniAbsences.
"""

from .student_viewset import StudentViewSet  # noqa: F401
from .course_viewset import CoursViewSet  # noqa: F401
from .enrollment_viewset import InscriptionViewSet  # noqa: F401
from .absence_viewset import AbsenceViewSet  # noqa: F401
from .justification_viewset import JustificationViewSet  # noqa: F401
from .notification_viewset import NotificationViewSet  # noqa: F401
from .analytics_views import dashboard_analytics, statistics_analytics  # noqa: F401
from .export_views import export_student_pdf_api, export_at_risk_excel_api  # noqa: F401
