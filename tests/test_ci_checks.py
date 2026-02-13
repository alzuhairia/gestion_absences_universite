from io import StringIO

from django.core.management import call_command
from django.test import SimpleTestCase


class MigrationCheckTests(SimpleTestCase):
    databases = {'default'}

    def test_makemigrations_check_dry_run(self):
        stdout = StringIO()
        stderr = StringIO()

        call_command(
            'makemigrations',
            check=True,
            dry_run=True,
            stdout=stdout,
            stderr=stderr,
        )

        combined_output = f"{stdout.getvalue()}\n{stderr.getvalue()}"
        self.assertIn('No changes detected', combined_output)

    def test_check_deploy(self):
        stdout = StringIO()
        stderr = StringIO()

        call_command(
            'check',
            deploy=True,
            stdout=stdout,
            stderr=stderr,
        )

        combined_output = f"{stdout.getvalue()}\n{stderr.getvalue()}".lower()
        self.assertNotIn('warning', combined_output)
