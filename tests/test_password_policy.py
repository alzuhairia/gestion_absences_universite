from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import User
from apps.dashboard.forms_admin import UserForm
from apps.enrollments.forms import StudentCreationForm


class PasswordPolicyFormTests(TestCase):
    def test_user_form_rejects_weak_password(self):
        form = UserForm(
            data={
                'nom': 'Weak',
                'prenom': 'User',
                'email': 'weak-user@example.com',
                'role': User.Role.ETUDIANT,
                'actif': True,
                'password': 'weakpass',
                'password_confirm': 'weakpass',
            }
        )

        self.assertFalse(form.is_valid())
        self.assertIn('password', form.errors)

    def test_user_form_accepts_strong_password(self):
        form = UserForm(
            data={
                'nom': 'Strong',
                'prenom': 'User',
                'email': 'strong-user@example.com',
                'role': User.Role.ETUDIANT,
                'actif': True,
                'password': 'StrongPass123!',
                'password_confirm': 'StrongPass123!',
            }
        )

        self.assertTrue(form.is_valid(), msg=form.errors)
        user = form.save()
        self.assertTrue(user.check_password('StrongPass123!'))
        self.assertTrue(user.must_change_password)

    def test_student_creation_form_rejects_weak_password(self):
        form = StudentCreationForm(
            data={
                'nom': 'Student',
                'prenom': 'Weak',
                'email': 'student-weak@example.com',
                'niveau': 1,
                'password': 'weakpass',
                'password_confirm': 'weakpass',
            }
        )

        self.assertFalse(form.is_valid())
        self.assertIn('password', form.errors)

    def test_student_creation_form_accepts_strong_password(self):
        form = StudentCreationForm(
            data={
                'nom': 'Student',
                'prenom': 'Strong',
                'email': 'student-strong@example.com',
                'niveau': 1,
                'password': 'StrongPass123!',
                'password_confirm': 'StrongPass123!',
            }
        )

        self.assertTrue(form.is_valid(), msg=form.errors)


class AdminPasswordResetPolicyTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            email='admin-password@example.com',
            nom='Admin',
            prenom='Password',
            password='AdminPass123!',
            role=User.Role.ADMIN,
        )
        self.target = User.objects.create_user(
            email='target-password@example.com',
            nom='Target',
            prenom='Password',
            password='InitialPass123!',
            role=User.Role.ETUDIANT,
            must_change_password=False,
        )
        self.client.force_login(self.admin)
        self.url = reverse('dashboard:admin_user_reset_password', args=[self.target.id_utilisateur])

    def test_admin_reset_rejects_weak_password(self):
        response = self.client.post(self.url, {'new_password': 'weakpass'}, secure=True)

        self.assertEqual(response.status_code, 302)
        self.target.refresh_from_db()
        self.assertTrue(self.target.check_password('InitialPass123!'))
        self.assertFalse(self.target.must_change_password)

    def test_admin_reset_accepts_strong_password(self):
        response = self.client.post(self.url, {'new_password': 'StrongPass123!'}, secure=True)

        self.assertEqual(response.status_code, 302)
        self.target.refresh_from_db()
        self.assertTrue(self.target.check_password('StrongPass123!'))
        self.assertTrue(self.target.must_change_password)
