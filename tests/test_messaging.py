from django.core.cache import cache
from django.test import TestCase

from apps.accounts.models import User
from apps.messaging.forms import MessageForm
from apps.messaging.models import Message


class MessageCacheInvalidationTest(TestCase):
    def setUp(self):
        self.sender = User.objects.create_user(
            email="sender@example.com",
            password="testpass123",
            nom="Sender",
            prenom="Test",
            role=User.Role.PROFESSEUR,
        )
        self.recipient = User.objects.create_user(
            email="recipient@example.com",
            password="testpass123",
            nom="Recipient",
            prenom="Test",
            role=User.Role.ETUDIANT,
        )
        self.cache_key = f"messages:unread_count:{self.recipient.pk}"

    def tearDown(self):
        cache.clear()

    def test_cache_invalidated_on_new_message(self):
        """Le cache du compteur non-lu est supprime quand un nouveau message est cree."""
        # Seed the cache with a stale value
        cache.set(self.cache_key, 0, timeout=300)
        self.assertEqual(cache.get(self.cache_key), 0)

        # Create a new message — save() should invalidate the cache
        Message.objects.create(
            expediteur=self.sender,
            destinataire=self.recipient,
            objet="Test",
            contenu="Contenu test",
        )

        self.assertIsNone(cache.get(self.cache_key))

    def test_cache_invalidated_on_mark_as_read(self):
        """mark_as_read() met lu=True et invalide le cache."""
        msg = Message.objects.create(
            expediteur=self.sender,
            destinataire=self.recipient,
            objet="Test",
            contenu="Contenu test",
        )
        # Seed cache after creation
        cache.set(self.cache_key, 1, timeout=300)

        msg.mark_as_read()

        self.assertTrue(msg.lu)
        self.assertIsNone(cache.get(self.cache_key))

    def test_mark_as_read_noop_if_already_read(self):
        """mark_as_read() ne fait rien si le message est deja lu."""
        msg = Message.objects.create(
            expediteur=self.sender,
            destinataire=self.recipient,
            objet="Test",
            contenu="Contenu test",
            lu=True,
        )
        # Should not trigger a save
        msg.mark_as_read()
        self.assertTrue(msg.lu)


class MessageFormTests(TestCase):
    def setUp(self):
        self.sender = User.objects.create_user(
            email="sender@example.com",
            password="testpass123",
            nom="Sender",
            prenom="Test",
            role=User.Role.PROFESSEUR,
        )
        self.active_recipient = User.objects.create_user(
            email="active@example.com",
            password="testpass123",
            nom="Active",
            prenom="User",
            role=User.Role.ETUDIANT,
        )
        self.inactive_recipient = User.objects.create_user(
            email="inactive@example.com",
            password="testpass123",
            nom="Inactive",
            prenom="User",
            role=User.Role.ETUDIANT,
        )
        self.inactive_recipient.actif = False
        self.inactive_recipient.save(update_fields=["actif"])

    def test_message_form_rejects_inactive_recipient(self):
        """Selecting an inactive user as recipient must be rejected."""
        # Force the inactive user into the queryset (simulates race condition:
        # user deactivated between page load and form submission)
        form = MessageForm(
            data={
                "destinataire": self.inactive_recipient.pk,
                "objet": "Test",
                "contenu": "Hello",
            },
            user=self.sender,
        )
        # Widen queryset to include inactive users (as if loaded before deactivation)
        form.fields["destinataire"].queryset = User.objects.exclude(pk=self.sender.pk)

        self.assertFalse(form.is_valid())
        self.assertIn("destinataire", form.errors)
        self.assertIn("actif", form.errors["destinataire"][0])

    def test_message_form_accepts_active_recipient(self):
        """Active recipient should be accepted."""
        form = MessageForm(
            data={
                "destinataire": self.active_recipient.pk,
                "objet": "Test subject",
                "contenu": "Message body",
            },
            user=self.sender,
        )
        self.assertTrue(form.is_valid())

    def test_message_form_excludes_inactive_from_queryset(self):
        """Inactive users should not appear in the recipient queryset."""
        form = MessageForm(user=self.sender)
        qs = form.fields["destinataire"].queryset
        self.assertIn(self.active_recipient, qs)
        self.assertNotIn(self.inactive_recipient, qs)

    def test_message_form_excludes_self(self):
        """The sender should not appear in their own recipient list."""
        form = MessageForm(user=self.sender)
        qs = form.fields["destinataire"].queryset
        self.assertNotIn(self.sender, qs)
