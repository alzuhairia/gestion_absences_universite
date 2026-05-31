"""
Tests — messagerie interne : invalidation du cache compteur, formulaire et blocage des comptes désactivés.
"""
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import User
from apps.messaging.forms import MessageForm
from apps.messaging.models import Message


class MessageCacheInvalidationTest(TestCase):
    """Vérifie que les opérations sur ``Message`` invalident correctement le cache du compteur non-lu."""

    def setUp(self):
        """Crée un expéditeur (professeur) et un destinataire (étudiant) avec leur clé de cache."""
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
        """Purge le cache après chaque test pour éviter toute fuite d'état entre tests."""
        cache.clear()

    def test_cache_invalidated_on_new_message(self):
        """Le cache du compteur non-lu est supprimé lorsqu'un nouveau message est créé."""
        # Pré-remplit le cache avec une valeur périmée
        cache.set(self.cache_key, 0, timeout=300)
        self.assertEqual(cache.get(self.cache_key), 0)

        # Création d'un nouveau message — save() doit invalider le cache
        Message.objects.create(
            expediteur=self.sender,
            destinataire=self.recipient,
            objet="Test",
            contenu="Contenu test",
        )

        self.assertIsNone(cache.get(self.cache_key))

    def test_cache_invalidated_on_mark_as_read(self):
        """``mark_as_read()`` met ``lu=True`` et invalide le cache."""
        msg = Message.objects.create(
            expediteur=self.sender,
            destinataire=self.recipient,
            objet="Test",
            contenu="Contenu test",
        )
        # Pré-remplit le cache après création
        cache.set(self.cache_key, 1, timeout=300)

        msg.mark_as_read()

        self.assertTrue(msg.lu)
        self.assertIsNone(cache.get(self.cache_key))

    def test_mark_as_read_noop_if_already_read(self):
        """``mark_as_read()`` ne fait rien si le message est déjà lu."""
        msg = Message.objects.create(
            expediteur=self.sender,
            destinataire=self.recipient,
            objet="Test",
            contenu="Contenu test",
            lu=True,
        )
        # Ne doit déclencher aucun save
        msg.mark_as_read()
        self.assertTrue(msg.lu)


class MessageFormTests(TestCase):
    """Tests de validation du formulaire ``MessageForm`` (destinataires actifs uniquement, exclusion de soi)."""

    def setUp(self):
        """Crée un expéditeur, un destinataire actif et un destinataire désactivé."""
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
        """Sélectionner un utilisateur désactivé comme destinataire doit être rejeté."""
        # Force l'utilisateur désactivé dans le queryset (simule une race condition :
        # utilisateur désactivé entre le chargement de la page et la soumission)
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
        """Un destinataire actif doit être accepté par le formulaire."""
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
        """Les utilisateurs désactivés ne doivent pas apparaître dans le queryset des destinataires."""
        form = MessageForm(user=self.sender)
        qs = form.fields["destinataire"].queryset
        self.assertIn(self.active_recipient, qs)
        self.assertNotIn(self.inactive_recipient, qs)

    def test_message_form_excludes_self(self):
        """L'expéditeur ne doit pas figurer dans sa propre liste de destinataires."""
        form = MessageForm(user=self.sender)
        qs = form.fields["destinataire"].queryset
        self.assertNotIn(self.sender, qs)

    def test_inactive_user_cannot_send_message(self):
        """Un utilisateur désactivé ne doit pas pouvoir envoyer de message."""
        self.sender.actif = False
        self.sender.save(update_fields=["actif"])

        self.client.force_login(self.sender)
        url = reverse("messaging:compose")
        response = self.client.post(
            url,
            {"destinataire": self.active_recipient.pk, "objet": "Hi", "contenu": "Test"},
            secure=True,
        )
        # Doit rediriger sans envoyer
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Message.objects.count(), 0)
