"""
Settings package for UniAbsences.

Sub-modules loaded in dependency order:
  env.py          — environment helpers, DEBUG, SECRET_KEY, network security primitives
  base.py         — installed apps, middleware, database, cache, auth, i18n
  third_party.py  — DRF, drf-spectacular, email backend
  logging_conf.py — rotating file + console logging
  security.py     — HTTPS/HSTS, session cookies, CSP, frame options

DJANGO_SETTINGS_MODULE=config.settings resolves to this __init__.py.
"""

from .env import *           # noqa: F401,F403
from .base import *          # noqa: F401,F403
from .third_party import *   # noqa: F401,F403
from .logging_conf import *  # noqa: F401,F403
from .security import *      # noqa: F401,F403
