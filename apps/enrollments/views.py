"""
Module central de ré-export des vues de l'application « enrollments ».

Ce fichier existe uniquement pour assurer la compatibilité ascendante avec
``urls.py``. Au fil de la croissance du code, la logique d'inscription a été
scindée en trois modules afin d'en faciliter la maintenance :

- ``enrollment_handlers.py`` — logique métier d'inscription par niveau et par cours
- ``enrollment_views.py``    — vues Django pilotant l'interface d'inscription
- ``enrollment_api.py``      — points JSON AJAX pour le formulaire dynamique

Tous les symboles publics sont ré-exportés ici afin que ``urls.py`` (et tout
autre appelant) puissent continuer à importer depuis
``apps.enrollments.views`` sans avoir à connaître la structure interne des
modules.

Appartient à : UniAbsences — application « enrollments ».
"""

from .enrollment_views import (  # noqa: F401
    enrollment_manager,
    enroll_student,
    get_prerequisite_info,
)
from .enrollment_api import (  # noqa: F401
    get_courses,
    get_courses_by_student,
    get_courses_by_year,
    get_departments,
)
