import django
from django.conf import settings


def pytest_configure(config):
    """Ensure Django is set up before test collection."""
    settings.LOGGING["handlers"]["file"]["class"] = "logging.NullHandler"

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
