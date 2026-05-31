"""
Paquet des serializers pour l'API REST UniAbsences.

Ce paquet regroupe les classes de serializer DRF par module métier afin que
chaque type de ressource ait un emplacement clair. La surface publique est
ré-exportée depuis ce ``__init__.py`` afin que les modules de vues puissent
tout importer via une seule instruction ``from ..serializers import …``.

Disposition des modules :
  user_serializers.py          — serializer de liste utilisateur en lecture seule
                                  et serializers de profil étudiant en écriture.
  course_serializers.py        — serializers de séance (Seance) et de cours (Cours)
                                  en variantes liste, détail et écriture.
  enrollment_serializers.py    — serializers de liste et d'écriture d'inscription
                                  (Inscription) avec validation des rôles.
  absence_serializers.py       — serializer de liste d'absences (avec champs dénormalisés)
                                  et serializer d'écriture avec validation des règles métier.
  justification_serializers.py — serializers de liste de justifications, création
                                  étudiant et traitement admin/secrétaire.
  notification_serializers.py  — serializer de notification en lecture seule.
  analytics_serializers.py     — classes Serializer simples (non liées à un modèle)
                                  utilisées pour valider et documenter les réponses d'analytiques.

Fait partie de l'API REST UniAbsences.
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
