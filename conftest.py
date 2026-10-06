from django.conf import settings


def pytest_configure(config):
    """Ensure Django is set up before test collection."""
    settings.LOGGING["handlers"]["file"]["class"] = "logging.NullHandler"
    # Send e-mails inline so tests can assert on mail.outbox right away.
    settings.EMAIL_ASYNC = False
    # Never touch the shared production Redis from tests (cache.clear() would
    # FLUSHDB it): every test gets a per-process in-memory cache instead.
    settings.CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "unabsences-tests",
        }
    }

    # Kill stale connections to the test database before pytest-django tries to create/drop it.
    import psycopg2

    db = settings.DATABASES["default"]
    test_db_name = f"test_{db['NAME']}"
    try:
        conn = psycopg2.connect(
            dbname="postgres",
            user=db["USER"],
            password=db["PASSWORD"],
            host=db["HOST"],
            port=db["PORT"],
        )
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(
                "SELECT pg_terminate_backend(pid) "
                "FROM pg_stat_activity "
                "WHERE datname = %s AND pid <> pg_backend_pid()",
                [test_db_name],
            )
        conn.close()
    except Exception:
        pass  # If postgres is unreachable, let Django handle the error later
