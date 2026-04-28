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
from .user_serializers import UserListSerializer, StudentSerializer
from .course_serializers import (
    SeanceSerializer,
    CoursListSerializer,
    CoursDetailSerializer,
    CoursWriteSerializer,
)
from .enrollment_serializers import InscriptionListSerializer, InscriptionWriteSerializer
from .absence_serializers import AbsenceListSerializer, AbsenceWriteSerializer
from .justification_serializers import (
    JustificationListSerializer,
    JustificationCreateSerializer,
    JustificationProcessSerializer,
)
from .notification_serializers import NotificationSerializer
from .analytics_serializers import DashboardAnalyticsSerializer, StatisticsAnalyticsSerializer
