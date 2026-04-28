"""
Tests — race conditions, suppression en cascade et pagination.
  - ConcurrentAbsenceCreationTests : IntegrityError + select_for_update
  - CourseDeletionTests            : cascade complète + ProtectedError + erreur générique
  - PaginationFallbackTests        : page invalide → page 1
  - UserDeletionTests              : dernier admin, suppression/désactivation
"""
from datetime import date, time
from decimal import Decimal
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.db.models.deletion import ProtectedError
from django.urls import reverse

from apps.absences.models import Absence, Justification
from apps.academic_sessions.models import Seance
from apps.academics.models import Cours
from apps.accounts.models import User
from apps.enrollments.models import Inscription

from .test_absences import BaseAbsenceTestCase


class ConcurrentAbsenceCreationTests(BaseAbsenceTestCase):
    """Tests race condition protection on simultaneous absence creation."""

    def test_concurrent_absence_creation(self):
        """
        Simulates a race condition: two requests try to create the same absence
        simultaneously. The unique_together constraint + IntegrityError handling
        ensures only one absence is created and the duplicate is gracefully ignored.
        """
        seance = Seance.objects.create(
            date_seance=date(2026, 3, 15),
            heure_debut=time(8, 0),
            heure_fin=time(10, 0),
            id_cours=self.course1,
            id_annee=self.annee,
        )
        self.client.force_login(self.prof)
        url = reverse("absences:mark_absence", args=[self.course1.id_cours])
        data = {
            "date_seance": "2026-03-15",
            "heure_debut": "08:00",
            "heure_fin": "10:00",
            f"status_{self.inscription1.id_inscription}": "ABSENT",
            f"type_{self.inscription1.id_inscription}": "ABSENT",
        }

        response1 = self.client.post(url, data, secure=True)
        self.assertEqual(response1.status_code, 302)
        self.assertEqual(Absence.objects.filter(id_seance=seance).count(), 1)

        def raise_on_create(self_qs, **kwargs):
            raise IntegrityError("duplicate key violates unique constraint")

        with patch.object(
            type(Absence.objects), "update_or_create", raise_on_create
        ):
            response2 = self.client.post(url, data, secure=True)

        self.assertEqual(response2.status_code, 302)
        self.assertEqual(Absence.objects.filter(id_seance=seance).count(), 1)

    def test_unique_constraint_prevents_duplicate_absence(self):
        """
        Verifies the unique_together constraint on (id_inscription, id_seance)
        prevents duplicate absences.
        """
        seance = Seance.objects.create(
            date_seance=date(2026, 3, 16),
            heure_debut=time(8, 0),
            heure_fin=time(10, 0),
            id_cours=self.course1,
            id_annee=self.annee,
        )

        Absence.objects.create(
            id_inscription=self.inscription1,
            id_seance=seance,
            type_absence="ABSENT",
            duree_absence=2.0,
            statut="NON_JUSTIFIEE",
            encodee_par=self.prof,
        )

        with self.assertRaises(ValidationError):
            Absence.objects.create(
                id_inscription=self.inscription1,
                id_seance=seance,
                type_absence="ABSENT",
                duree_absence=2.0,
                statut="NON_JUSTIFIEE",
                encodee_par=self.prof,
            )

        self.assertEqual(Absence.objects.filter(id_seance=seance).count(), 1)

    def test_select_for_update_on_seance(self):
        """
        Verifies that the seance is fetched with select_for_update() inside
        the transaction, preventing concurrent modification of the same session.
        """
        self.client.force_login(self.prof)
        url = reverse("absences:mark_absence", args=[self.course1.id_cours])
        data = {
            "date_seance": "2026-03-17",
            "heure_debut": "08:00",
            "heure_fin": "10:00",
            f"status_{self.inscription1.id_inscription}": "ABSENT",
            f"type_{self.inscription1.id_inscription}": "ABSENT",
        }

        with patch.object(
            Seance.objects, "select_for_update", wraps=Seance.objects.select_for_update
        ) as mock_sfu:
            self.client.post(url, data, secure=True)
            mock_sfu.assert_called_once()


class CourseDeletionTests(BaseAbsenceTestCase):
    """Tests for course deletion cascade and ProtectedError handling."""

    def _build_course_with_deps(self):
        """Create a course with seance, absence, and justification."""
        seance = Seance.objects.create(
            date_seance=date(2026, 2, 1),
            heure_debut=time(8, 0),
            heure_fin=time(10, 0),
            id_cours=self.course1,
            id_annee=self.annee,
        )
        absence = Absence.objects.create(
            id_inscription=self.inscription1,
            id_seance=seance,
            type_absence="ABSENT",
            duree_absence=Decimal("2.00"),
            statut="NON_JUSTIFIEE",
            encodee_par=self.prof,
        )
        justification = Justification.objects.create(
            id_absence=absence,
            state="EN_ATTENTE",
        )
        return seance, absence, justification

    def test_secretary_cascade_deletes_all_related_objects(self):
        """Full cascade deletion removes justifications, absences, inscriptions, seances, and course."""
        seance, absence, justification = self._build_course_with_deps()
        course_pk = self.course1.id_cours

        self.client.force_login(self.secretary)
        url = reverse("dashboard:secretary_course_delete", args=[course_pk])
        response = self.client.post(url, secure=True)

        self.assertEqual(response.status_code, 302)
        self.assertFalse(Cours.objects.filter(pk=course_pk).exists())
        self.assertFalse(Seance.objects.filter(pk=seance.pk).exists())
        self.assertFalse(Absence.objects.filter(pk=absence.pk).exists())
        self.assertFalse(Justification.objects.filter(pk=justification.pk).exists())
        self.assertFalse(Inscription.objects.filter(pk=self.inscription1.pk).exists())

    def test_course_deletion_with_protected_references_shows_error(self):
        """
        When a ProtectedError bubbles up, the view must show a clear, grouped
        error message — NOT a 500.
        """
        seance, absence, justification = self._build_course_with_deps()
        course_pk = self.course1.id_cours

        self.client.force_login(self.secretary)
        url = reverse("dashboard:secretary_course_delete", args=[course_pk])

        protected_err = ProtectedError(
            "Cannot delete some instances of model 'Cours'.",
            {self.inscription1},
        )
        with patch.object(Cours, "delete", side_effect=protected_err), \
             patch("apps.dashboard.views_secretary.messages") as mock_messages:
            response = self.client.post(url, secure=True)

        self.assertEqual(response.status_code, 302)
        self.assertTrue(Cours.objects.filter(pk=course_pk).exists())

        mock_messages.error.assert_called_once()
        error_text = mock_messages.error.call_args[0][1]
        self.assertIn("Impossible de supprimer", error_text)
        self.assertIn("bloquants", error_text)
        self.assertIn("inscription", error_text.lower())

    def test_course_deletion_generic_exception_shows_error(self):
        """
        A generic exception during deletion must be logged and produce
        a user-friendly error message, not a 500.
        """
        self._build_course_with_deps()
        course_pk = self.course1.id_cours

        self.client.force_login(self.secretary)
        url = reverse("dashboard:secretary_course_delete", args=[course_pk])

        with patch.object(Cours, "delete", side_effect=RuntimeError("DB connection lost")), \
             patch("apps.dashboard.views_secretary.messages") as mock_messages:
            response = self.client.post(url, secure=True)

        self.assertEqual(response.status_code, 302)
        self.assertTrue(Cours.objects.filter(pk=course_pk).exists())

        mock_messages.error.assert_called_once()
        error_text = mock_messages.error.call_args[0][1]
        self.assertIn("Erreur lors de la suppression", error_text)


class PaginationFallbackTests(BaseAbsenceTestCase):
    """Invalid page numbers must fall back to page 1, not crash or show empty."""

    def setUp(self):
        super().setUp()
        self.client.force_login(self.secretary)
        self.url = reverse("dashboard:secretary_courses")

    def test_invalid_page_number_redirects_to_page_1(self):
        """page=999, page=abc, page=-1 all return page 1 content (200)."""
        for bad_page in ("999", "abc", "-1", "0", ""):
            with self.subTest(page=bad_page):
                response = self.client.get(
                    self.url, {"page": bad_page}, secure=True
                )
                self.assertEqual(response.status_code, 200)
                page_obj = response.context["courses"]
                self.assertEqual(page_obj.number, 1)


class UserDeletionTests(BaseAbsenceTestCase):
    """Tests for admin user deletion with FK cleanup and last-admin guard."""

    def setUp(self):
        super().setUp()
        self.client.force_login(self.admin)

    def test_user_deletion_cleans_up_all_references(self):
        """Deleting a professor with courses detaches courses and deletes the user."""
        url = reverse("dashboard:admin_user_delete", args=[self.prof.pk])
        response = self.client.post(url, secure=True)

        self.assertEqual(response.status_code, 302)
        self.assertFalse(User.objects.filter(pk=self.prof.pk).exists())
        self.course1.refresh_from_db()
        self.assertIsNone(self.course1.professeur)

    def test_user_with_inscriptions_is_deactivated_not_deleted(self):
        """A student with inscriptions is deactivated, not hard-deleted."""
        url = reverse("dashboard:admin_user_delete", args=[self.student1.pk])
        response = self.client.post(url, secure=True)

        self.assertEqual(response.status_code, 302)
        self.student1.refresh_from_db()
        self.assertTrue(User.objects.filter(pk=self.student1.pk).exists())
        self.assertFalse(self.student1.actif)

    def test_cannot_delete_last_admin(self):
        """The last active admin cannot be deleted."""
        url = reverse("dashboard:admin_user_delete", args=[self.admin.pk])
        response = self.client.post(url, secure=True)

        self.assertEqual(response.status_code, 302)
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.actif)

    def test_cannot_delete_self(self):
        """An admin cannot delete their own account."""
        url = reverse("dashboard:admin_user_delete", args=[self.admin.pk])
        response = self.client.post(url, secure=True)

        self.assertEqual(response.status_code, 302)
        self.assertTrue(User.objects.filter(pk=self.admin.pk).exists())
