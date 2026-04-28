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

from .student_viewset import StudentViewSet  # noqa: F401
from .course_viewset import CoursViewSet  # noqa: F401
from .enrollment_viewset import InscriptionViewSet  # noqa: F401
from .absence_viewset import AbsenceViewSet  # noqa: F401
from .justification_viewset import JustificationViewSet  # noqa: F401
from .notification_viewset import NotificationViewSet  # noqa: F401
from .analytics_views import dashboard_analytics, statistics_analytics  # noqa: F401
from .export_views import export_student_pdf_api, export_at_risk_excel_api  # noqa: F401
