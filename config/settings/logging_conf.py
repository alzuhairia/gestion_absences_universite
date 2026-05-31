"""
Configuration du logging pour le projet UniAbsences.

Met en place deux handlers :
  - ``file``    — RotatingFileHandler écrivant dans ``logs/django.log``.
                  Tourne à 5 Mo, conserve 2 fichiers de sauvegarde.
                  Utilise le formateur verbose (niveau + timestamp + module + message).
  - ``console`` — StreamHandler écrivant sur stderr.
                  Utilise le formateur simple (niveau + message).
                  Niveau DEBUG lorsque DEBUG=True, INFO sinon.

Les deux handlers sont rattachés au logger racine ainsi qu'aux loggers
dédiés ``django`` et ``apps`` (propagation désactivée pour éviter les
entrées dupliquées).

Le logger ``apps`` couvre tout le code applicatif UniAbsences sous le
namespace ``apps.*``.

Note : ``conftest.py`` remplace la classe du handler ``file`` par
``logging.NullHandler`` pendant les tests pour supprimer les I/O fichier.

Fait partie du package settings de UniAbsences.
"""

from .env import BASE_DIR, DEBUG

# S'assure que le répertoire logs existe ; le crée si nécessaire.
LOGS_DIR = BASE_DIR / "logs"
LOGS_DIR.mkdir(exist_ok=True)

LOGGING = {
    "version": 1,
    # Conserve les loggers Django/bibliothèques existants actifs ; ne les supprime pas.
    "disable_existing_loggers": False,
    "formatters": {
        # Verbose : utilisé par le handler fichier pour les lignes de log structurées.
        "verbose": {
            "format": "{levelname} {asctime} {module} {message}",
            "style": "{",
        },
        # Simple : utilisé par le handler console pour une sortie lisible.
        "simple": {
            "format": "{levelname} {message}",
            "style": "{",
        },
    },
    "handlers": {
        "file": {
            "level": "INFO",
            # RotatingFileHandler empêche le fichier de log de croître sans limite.
            "class": "logging.handlers.RotatingFileHandler",
            "filename": LOGS_DIR / "django.log",
            "maxBytes": 5 * 1024 * 1024,  # 5 Mo par fichier
            "backupCount": 2,              # Conserve au plus 2 sauvegardes tournantes
            "formatter": "verbose",
        },
        "console": {
            # Abaisse le seuil console à DEBUG en développement pour une sortie détaillée.
            "level": "DEBUG" if DEBUG else "INFO",
            "class": "logging.StreamHandler",
            "formatter": "simple",
        },
    },
    # Logger racine : capture tout ce qui n'est pas géré par un logger nommé ci-dessous.
    "root": {
        "handlers": ["console", "file"],
        "level": "INFO",
    },
    "loggers": {
        # Messages propres au framework Django (requêtes, SQL, signaux, etc.).
        "django": {
            "handlers": ["console", "file"],
            "level": "INFO",
            # propagate=False empêche le double-logging via le logger racine.
            "propagate": False,
        },
        # Tout le code applicatif UniAbsences sous apps.*
        "apps": {
            "handlers": ["console", "file"],
            # Affiche les logs DEBUG du code applicatif en développement.
            "level": "DEBUG" if DEBUG else "INFO",
            "propagate": False,
        },
    },
}
