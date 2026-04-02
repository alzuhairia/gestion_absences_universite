from django.test import TestCase, override_settings
from django.urls import reverse

from apps.accounts.models import User
from apps.dashboard.forms_admin import UserForm
from apps.enrollments.forms import StudentCreationForm


class PasswordPolicyFormTests(TestCase):
    def test_user_form_rejects_weak_password(self):
        form = UserForm(
            data={
                "nom": "Weak",
                "prenom": "User",
                "email": "weak-user@example.com",
                "role": User.Role.ETUDIANT,
                "actif": True,
                "password": "weakpass",
                "password_confirm": "weakpass",
            }
        )

        self.assertFalse(form.is_valid())
        self.assertIn("password", form.errors)

    def test_user_form_accepts_strong_password(self):
        form = UserForm(
            data={
                "nom": "Strong",
                "prenom": "User",
                "email": "strong-user@example.com",
                "role": User.Role.ETUDIANT,
                "actif": True,
                "password": "StrongPass123!",
                "password_confirm": "StrongPass123!",
            }
        )

        self.assertTrue(form.is_valid(), msg=form.errors)
        user = form.save()
        self.assertTrue(user.check_password("StrongPass123!"))
        self.assertTrue(user.must_change_password)

    def test_student_creation_form_rejects_weak_password(self):
        form = StudentCreationForm(
            data={
                "nom": "Student",
                "prenom": "Weak",
                "email": "student-weak@example.com",
                "niveau": 1,
                "password": "weakpass",
                "password_confirm": "weakpass",
            }
        )

        self.assertFalse(form.is_valid())
        self.assertIn("password", form.errors)

    def test_student_creation_form_accepts_strong_password(self):
        form = StudentCreationForm(
            data={
                "nom": "Student",
                "prenom": "Strong",
                "email": "student-strong@example.com",
                "niveau": 1,
                "password": "StrongPass123!",
                "password_confirm": "StrongPass123!",
            }
        )

        self.assertTrue(form.is_valid(), msg=form.errors)


@override_settings(SECURE_SSL_REDIRECT=False)
class InitialSetupTests(TestCase):
    """Tests for the one-time initial admin setup page."""

    def test_initial_setup_prevents_double_admin(self):
        """
        If an admin is created between loading the form (GET) and submitting
        it (POST), the select_for_update guard must reject the second creation.
        """
        # No admin exists yet — GET succeeds
        url = reverse("setup")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        # Meanwhile, another admin is created (simulates concurrent request)
        User.objects.create_superuser(
            email="first-admin@example.com",
            nom="First",
            prenom="Admin",
            password="StrongPass123!",
        )
        self.assertEqual(
            User.objects.filter(role=User.Role.ADMIN).count(), 1
        )

        # POST arrives — must be rejected (404) since an admin now exists
        response = self.client.post(url, {
            "prenom": "Second",
            "nom": "Admin",
            "email": "second-admin@example.com",
            "password": "StrongPass456!",
            "password_confirm": "StrongPass456!",
        })
        self.assertEqual(response.status_code, 404)

        # Only the first admin should exist
        self.assertEqual(
            User.objects.filter(role=User.Role.ADMIN).count(), 1
        )
        self.assertFalse(
            User.objects.filter(email="second-admin@example.com").exists()
        )

    def test_initial_setup_returns_404_when_admin_exists(self):
        """Both GET and POST return 404 if an admin already exists."""
        User.objects.create_superuser(
            email="existing-admin@example.com",
            nom="Existing",
            prenom="Admin",
            password="StrongPass123!",
        )
        url = reverse("setup")

        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.post(url, {}).status_code, 404)


class AdminPasswordResetPolicyTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            email="admin-password@example.com",
            nom="Admin",
            prenom="Password",
            password="AdminPass123!",
            role=User.Role.ADMIN,
        )
        self.target = User.objects.create_user(
            email="target-password@example.com",
            nom="Target",
            prenom="Password",
            password="InitialPass123!",
            role=User.Role.ETUDIANT,
            must_change_password=False,
        )
        self.client.force_login(self.admin)
        self.url = reverse(
            "dashboard:admin_user_reset_password", args=[self.target.id_utilisateur]
        )

    def test_admin_reset_rejects_weak_password(self):
        response = self.client.post(self.url, {"new_password": "weakpass"}, secure=True)

        self.assertEqual(response.status_code, 302)
        self.target.refresh_from_db()
        self.assertTrue(self.target.check_password("InitialPass123!"))
        self.assertFalse(self.target.must_change_password)

    def test_admin_reset_accepts_strong_password(self):
        response = self.client.post(
            self.url, {"new_password": "StrongPass123!"}, secure=True
        )

        self.assertEqual(response.status_code, 302)
        self.target.refresh_from_db()
        self.assertTrue(self.target.check_password("StrongPass123!"))
        self.assertTrue(self.target.must_change_password)
