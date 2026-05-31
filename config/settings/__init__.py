"""
Package settings du projet UniAbsences.

Django résout ``DJANGO_SETTINGS_MODULE=config.settings`` vers ce
``__init__.py``. Le package est découpé en sous-modules ciblés, importés
dans un ordre de dépendance strict afin que les modules ultérieurs puissent
référencer en toute sécurité les noms définis dans les précédents.

Ordre de chargement des sous-modules :
  1. env.py          — chargement dotenv, DEBUG, SECRET_KEY, ALLOWED_HOSTS,
                       origines CSRF, confiance proxy, primitives de
                       limitation de débit, et tous les helpers de parsing
                       d'environnement (env_bool/int/list/cidr).
  2. base.py         — INSTALLED_APPS, MIDDLEWARE, templates, base de données
                       PostgreSQL, cache Redis/LocMem, validateurs de mot de
                       passe, internationalisation, chemins static/media, et
                       configuration des sessions et de l'authentification.
  3. third_party.py  — Django REST Framework, drf-spectacular (OpenAPI), et
                       détection automatique du backend email.
  4. logging_conf.py — handler de fichier rotatif + handler console ; le
                       niveau de log suit le drapeau DEBUG.
  5. security.py     — redirection HTTPS, HSTS, cookies sécurisés, Content
                       Security Policy (basée sur des nonces), options de
                       cadres, et politique de référent.

Tous les sous-modules utilisent ``from .xyz import *`` afin que leurs noms
arrivent directement dans le namespace ``config.settings`` attendu par
Django.
"""

from .env import *           # noqa: F401,F403
from .base import *          # noqa: F401,F403
from .third_party import *   # noqa: F401,F403
from .logging_conf import *  # noqa: F401,F403
from .security import *      # noqa: F401,F403
