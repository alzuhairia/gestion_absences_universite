"""
Point d'entrée ASGI pour le projet UniAbsences.

Expose le callable ASGI sous forme de variable ``application`` au niveau du
module, recherchée par les serveurs compatibles ASGI (Uvicorn, Daphne,
Hypercorn) lors du démarrage de l'application.

Fait partie de la configuration de déploiement de UniAbsences.

Voir : https://docs.djangoproject.com/en/6.0/howto/deployment/asgi/
"""

import os

from django.core.asgi import get_asgi_application

# Garantit que Django utilise le bon package settings avant le chargement du registre d'applications.
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

# Callable ASGI consommé par le serveur applicatif au démarrage.
application = get_asgi_application()
