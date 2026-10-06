from types import SimpleNamespace
from unittest.mock import patch

from django.core import mail
from django.test import SimpleTestCase, TestCase

from apps.notifications.email import send_notification_email, send_with_dedup

LOGGER = "apps.notifications.email"


def _user(email="etu@example.com", actif=True, pk=42):
    return SimpleNamespace(email=email, actif=actif, pk=pk)


class SendNotificationEmailLoggingTests(SimpleTestCase):
    def test_successful_send_is_logged(self):
        with self.assertLogs(LOGGER, level="INFO") as logs:
            self.assertTrue(send_notification_email(_user(), "Sujet test", "Corps"))
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Email sent to etu@example.com (user_id=42): Sujet test", logs.output[0])

    def test_inactive_user_skip_is_logged(self):
        with self.assertLogs(LOGGER, level="INFO") as logs:
            self.assertFalse(send_notification_email(_user(actif=False), "Sujet", "Corps"))
        self.assertEqual(len(mail.outbox), 0)
        self.assertIn("skipped (inactive user)", logs.output[0])

    def test_missing_address_skip_is_logged(self):
        with self.assertLogs(LOGGER, level="INFO") as logs:
            self.assertFalse(send_notification_email(_user(email=""), "Sujet", "Corps"))
        self.assertIn("skipped (no address)", logs.output[0])

    def test_failure_is_logged_as_error(self):
        with patch("apps.notifications.email.send_mail", side_effect=OSError("smtp down")):
            with self.assertLogs(LOGGER, level="ERROR") as logs:
                self.assertFalse(send_notification_email(_user(), "Sujet", "Corps"))
        self.assertIn("Failed to send email to etu@example.com", logs.output[0])


class SendWithDedupLoggingTests(TestCase):
    def test_dedup_skip_is_logged_at_info(self):
        user = _user()
        self.assertTrue(send_with_dedup(user, "Sujet", "Corps", None, "threshold", "k1"))
        with self.assertLogs(LOGGER, level="INFO") as logs:
            self.assertFalse(send_with_dedup(user, "Sujet", "Corps", None, "threshold", "k1"))
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Dedup: skipping threshold email to etu@example.com", logs.output[0])
