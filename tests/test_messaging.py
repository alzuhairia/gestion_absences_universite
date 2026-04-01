from django.core.cache import cache
from django.test import TestCase

from apps.accounts.models import User
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
