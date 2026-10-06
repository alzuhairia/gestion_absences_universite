from unittest.mock import patch

from django.core import mail
from django.test import TestCase, TransactionTestCase
from django.urls import reverse

from apps.accounts.models import User
from apps.notifications import email as email_module
from apps.notifications.email import send_notification_email, send_with_dedup
from apps.notifications.models import EmailEnvoi

LOGGER = "apps.notifications.email"


def _make_user(email, role=User.Role.ETUDIANT, **extra):
    return User.objects.create_user(
        email=email, nom="Nom", prenom="Prenom", password="pass1234", role=role, **extra
    )


class SendNotificationEmailLoggingTests(TestCase):
    def setUp(self):
        self.student = _make_user("etu@example.com")

    def test_successful_send_is_logged_and_recorded(self):
        with self.assertLogs(LOGGER, level="INFO") as logs:
            self.assertTrue(send_notification_email(self.student, "Sujet test", "Corps"))
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(
            f"Email sent to etu@example.com (user_id={self.student.pk}): Sujet test",
            logs.output[0],
        )
        envoi = EmailEnvoi.objects.get()
        self.assertEqual(envoi.destinataire, self.student)
        self.assertEqual(envoi.destinataire_email, "etu@example.com")
        self.assertEqual(envoi.sujet, "Sujet test")
        self.assertEqual(envoi.statut, EmailEnvoi.Statut.ENVOYE)

    def test_inactive_user_skip_is_logged_not_recorded(self):
        self.student.actif = False
        with self.assertLogs(LOGGER, level="INFO") as logs:
            self.assertFalse(send_notification_email(self.student, "Sujet", "Corps"))
        self.assertEqual(len(mail.outbox), 0)
        self.assertIn("skipped (inactive user)", logs.output[0])
        self.assertFalse(EmailEnvoi.objects.exists())

    def test_missing_address_skip_is_logged(self):
        self.student.email = ""
        with self.assertLogs(LOGGER, level="INFO") as logs:
            self.assertFalse(send_notification_email(self.student, "Sujet", "Corps"))
        self.assertIn("skipped (no address)", logs.output[0])
        self.assertFalse(EmailEnvoi.objects.exists())

    def test_failure_is_logged_as_error_and_recorded(self):
        with patch("apps.notifications.email.send_mail", side_effect=OSError("smtp down")):
            with self.assertLogs(LOGGER, level="ERROR") as logs:
                self.assertFalse(send_notification_email(self.student, "Sujet", "Corps"))
        self.assertIn("Failed to send email to etu@example.com", logs.output[0])
        self.assertEqual(EmailEnvoi.objects.get().statut, EmailEnvoi.Statut.ECHEC)

    def test_record_failure_never_breaks_the_send(self):
        with patch(
            "apps.notifications.models.EmailEnvoi.objects.create",
            side_effect=RuntimeError("db down"),
        ):
            with self.assertLogs(LOGGER, level="ERROR"):
                self.assertTrue(send_notification_email(self.student, "Sujet", "Corps"))
        self.assertEqual(len(mail.outbox), 1)

    def test_dedup_skip_is_logged_at_info(self):
        self.assertTrue(send_with_dedup(self.student, "Sujet", "Corps", None, "threshold", "k1"))
        with self.assertLogs(LOGGER, level="INFO") as logs:
            self.assertFalse(send_with_dedup(self.student, "Sujet", "Corps", None, "threshold", "k1"))
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Dedup: skipping threshold email to etu@example.com", logs.output[0])
        self.assertEqual(EmailEnvoi.objects.count(), 1)


class BackgroundSendingTests(TestCase):
    def setUp(self):
        self.student = _make_user("etu@example.com")

    def test_background_send_is_deferred_until_commit(self):
        with patch.object(email_module.transaction, "on_commit") as on_commit:
            self.assertTrue(
                send_notification_email(self.student, "Sujet", "Corps", background=True)
            )
        # Nothing leaves before the transaction commits.
        self.assertEqual(len(mail.outbox), 0)
        on_commit.assert_called_once()

        # Commit: the callback queues the delivery (run inline here).
        on_commit_callback = on_commit.call_args.args[0]
        with patch.object(email_module, "_queue", side_effect=lambda args: email_module._deliver(*args)):
            on_commit_callback()
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(EmailEnvoi.objects.get().statut, EmailEnvoi.Statut.ENVOYE)

    def test_skips_are_still_immediate_in_background_mode(self):
        self.student.actif = False
        with patch.object(email_module.transaction, "on_commit") as on_commit:
            self.assertFalse(
                send_notification_email(self.student, "Sujet", "Corps", background=True)
            )
        on_commit.assert_not_called()


class ThreadPoolDeliveryTests(TransactionTestCase):
    """Real worker thread: the email is sent and recorded off the request thread."""

    def test_worker_thread_sends_and_records(self):
        student = _make_user("etu@example.com")
        executor = email_module._EMAIL_EXECUTOR
        futures = []

        def spy_submit(*args, **kwargs):
            future = type(executor).submit(executor, *args, **kwargs)
            futures.append(future)
            return future

        with self.settings(EMAIL_ASYNC=True), patch.object(executor, "submit", spy_submit):
            # Autocommit: on_commit runs immediately and queues the job.
            self.assertTrue(send_notification_email(student, "Sujet thread", "Corps"))
        self.assertEqual(len(futures), 1)
        futures[0].result(timeout=10)

        self.assertEqual(len(mail.outbox), 1)
        envoi = EmailEnvoi.objects.get()
        self.assertEqual(envoi.sujet, "Sujet thread")
        self.assertEqual(envoi.destinataire, student)

class EmailHistoryViewsTests(TestCase):
    def setUp(self):
        self.student = _make_user("etu@example.com")
        self.other = _make_user("autre@example.com")
        self.secretary = _make_user("sec@example.com", role=User.Role.SECRETAIRE)
        EmailEnvoi.objects.create(
            destinataire=self.student, destinataire_email=self.student.email,
            sujet="Absence enregistrée — JAVA", statut=EmailEnvoi.Statut.ENVOYE,
        )
        EmailEnvoi.objects.create(
            destinataire=self.other, destinataire_email=self.other.email,
            sujet="Absence enregistrée — CCNA", statut=EmailEnvoi.Statut.ECHEC,
        )

    def test_student_sees_only_own_emails(self):
        self.client.force_login(self.student)
        response = self.client.get(reverse("dashboard:student_emails"), secure=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Absence enregistrée — JAVA")
        self.assertNotContains(response, "CCNA")

    def test_secretary_sees_all_and_can_filter(self):
        self.client.force_login(self.secretary)
        url = reverse("dashboard:secretary_email_logs")
        response = self.client.get(url, secure=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "JAVA")
        self.assertContains(response, "CCNA")

        response = self.client.get(url, {"statut": "ECHEC"}, secure=True)
        self.assertNotContains(response, "JAVA")
        self.assertContains(response, "CCNA")

        response = self.client.get(url, {"q": "etu@"}, secure=True)
        self.assertContains(response, "JAVA")
        self.assertNotContains(response, "CCNA")

    def test_student_cannot_access_secretary_history(self):
        self.client.force_login(self.student)
        response = self.client.get(reverse("dashboard:secretary_email_logs"), secure=True)
        self.assertEqual(response.status_code, 302)
