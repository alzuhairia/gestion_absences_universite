"""
Package de vues API REST pour UniAbsences.

Organisation par domaine :
  student_viewset.py      — StudentViewSet (CRUD etudiants)
  course_viewset.py       — CoursViewSet (CRUD cours)
  enrollment_viewset.py   — InscriptionViewSet (CRUD inscriptions)
  absence_viewset.py      — AbsenceViewSet (CRUD absences)
  justification_viewset.py — JustificationViewSet (soumission + approbation)
  notification_viewset.py — NotificationViewSet (notifications utilisateur)
  analytics_views.py      — dashboard_analytics, statistics_analytics
  export_views.py         — export_student_pdf_api, export_at_risk_excel_api
"""
from .student_viewset import StudentViewSet
from .course_viewset import CoursViewSet
from .enrollment_viewset import InscriptionViewSet
from .absence_viewset import AbsenceViewSet
from .justification_viewset import JustificationViewSet
from .notification_viewset import NotificationViewSet
from .analytics_views import dashboard_analytics, statistics_analytics
from .export_views import export_student_pdf_api, export_at_risk_excel_api
