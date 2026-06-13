"""
Configuration pytest pour le projet UniAbsences.

Ce fichier contient les hooks et fixtures pytest pour la mise en place et le
démontage des tests. Il garantit que Django est correctement configuré et gère
le nettoyage des connexions à la base pour les bases de tests PostgreSQL.

Fait partie de l'infrastructure de tests UniAbsences.
"""
import django
from django.conf import settings


def pytest_configure(config):
    """
    Garantit que Django est configuré avant la collecte des tests.

    Configure également la journalisation pour supprimer la sortie fichier
    pendant les tests et termine les connexions obsolètes à la base afin
    d'empêcher toute interférence entre tests.
    """
    settings.LOGGING["handlers"]["file"]["class"] = "logging.NullHandler"

    # Termine les connexions obsolètes vers la base de tests avant que pytest-django ne tente de la créer/supprimer.
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
        pass  # Si postgres est injoignable, laisser Django gérer l'erreur plus tard
