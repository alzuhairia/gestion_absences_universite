"""
Point d'entrée WSGI pour le projet UniAbsences.

Expose le callable WSGI sous forme de variable ``application`` au niveau du
module, recherchée par les serveurs compatibles WSGI (Gunicorn, uWSGI,
mod_wsgi) lors du démarrage de l'application en mode synchrone.

Fait partie de la configuration de déploiement de UniAbsences.

Voir : https://docs.djangoproject.com/en/6.0/howto/deployment/wsgi/
"""

import os

from django.core.wsgi import get_wsgi_application

# Garantit que Django utilise le bon package settings avant le chargement du registre d'applications.
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

# Callable WSGI consommé par le serveur applicatif au démarrage.
application = get_wsgi_application()
