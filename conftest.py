"""
Pytest configuration for the UniAbsences project.

This file contains pytest hooks and fixtures for test setup and teardown.
It ensures Django is properly configured and handles database connection cleanup
for PostgreSQL test databases.

Part of the UniAbsences test infrastructure.
"""
import django
from django.conf import settings


def pytest_configure(config):
    """
    Ensure Django is set up before test collection.
    
    Also configures logging to suppress file output during tests and
    terminates stale database connections to prevent test interference.
    """
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
