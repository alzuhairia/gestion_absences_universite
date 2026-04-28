"""
Package de serializers DRF pour l'API UniAbsences.

Organisation par domaine :
  user_serializers.py         — utilisateurs et etudiants
  course_serializers.py       — seances et cours
  enrollment_serializers.py   — inscriptions
  absence_serializers.py      — absences
  justification_serializers.py — justificatifs
  notification_serializers.py — notifications
  analytics_serializers.py    — donnees analytiques dashboard
"""

from .user_serializers import UserListSerializer, StudentSerializer  # noqa: F401
from .course_serializers import (  # noqa: F401
    SeanceSerializer,
    CoursListSerializer,
    CoursDetailSerializer,
    CoursWriteSerializer,
)
from .enrollment_serializers import (  # noqa: F401
    InscriptionListSerializer,
    InscriptionWriteSerializer,
)
from .absence_serializers import AbsenceListSerializer, AbsenceWriteSerializer  # noqa: F401
from .justification_serializers import (  # noqa: F401
    JustificationListSerializer,
    JustificationCreateSerializer,
    JustificationProcessSerializer,
)
from .notification_serializers import NotificationSerializer  # noqa: F401
from .analytics_serializers import (  # noqa: F401
    DashboardAnalyticsSerializer,
    StatisticsAnalyticsSerializer,
)
