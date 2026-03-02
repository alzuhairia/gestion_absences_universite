import django
from django.conf import settings


def pytest_configure(config):
    """Ensure Django is set up before test collection."""
    settings.LOGGING["handlers"]["file"]["class"] = "logging.NullHandler"
