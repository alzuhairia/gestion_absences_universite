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
    """Tests de protection contre les race conditions à la création simultanée d'absences."""

    def test_concurrent_absence_creation(self):
        """
        Simule une race condition : deux requêtes tentent de créer la même absence
        en parallèle. La contrainte ``unique_together`` + gestion d'``IntegrityError``
        garantit qu'une seule absence est créée et que le doublon est ignoré proprement.
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
            """Stub levant ``IntegrityError`` pour simuler une insertion concurrente."""
            raise IntegrityError("duplicate key violates unique constraint")

        with patch.object(
            type(Absence.objects), "update_or_create", raise_on_create
        ):
            response2 = self.client.post(url, data, secure=True)

        self.assertEqual(response2.status_code, 302)
        self.assertEqual(Absence.objects.filter(id_seance=seance).count(), 1)

    def test_unique_constraint_prevents_duplicate_absence(self):
        """
        Vérifie que la contrainte ``unique_together`` sur (id_inscription, id_seance)
        empêche la création de doublons d'absences.
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
        Vérifie que la séance est récupérée avec ``select_for_update()`` dans
        la transaction, empêchant la modification concurrente de la même séance.
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
    """Tests de suppression en cascade d'un cours et gestion des ``ProtectedError``."""

    def _build_course_with_deps(self):
        """Crée un cours avec séance, absence et justification associées."""
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
        """La suppression en cascade efface justifications, absences, inscriptions, séances et cours."""
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
        Lorsqu'un ``ProtectedError`` remonte, la vue affiche un message d'erreur
        clair et groupé — surtout pas une erreur 500.
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
        Une exception générique pendant la suppression doit être journalisée et
        produire un message d'erreur clair pour l'utilisateur, pas un 500.
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
    """Un numéro de page invalide doit retomber sur la page 1 et non planter ou renvoyer du vide."""

    def setUp(self):
        """Authentifie le secrétaire et résout l'URL de la liste paginée des cours."""
        super().setUp()
        self.client.force_login(self.secretary)
        self.url = reverse("dashboard:secretary_courses")

    def test_invalid_page_number_redirects_to_page_1(self):
        """``page=999``, ``page=abc``, ``page=-1`` doivent renvoyer le contenu de la page 1 (200)."""
        for bad_page in ("999", "abc", "-1", "0", ""):
            with self.subTest(page=bad_page):
                response = self.client.get(
                    self.url, {"page": bad_page}, secure=True
                )
                self.assertEqual(response.status_code, 200)
                page_obj = response.context["courses"]
                self.assertEqual(page_obj.number, 1)


class UserDeletionTests(BaseAbsenceTestCase):
    """Tests de suppression d'utilisateur par l'admin avec nettoyage des FK et verrou « dernier admin »."""

    def setUp(self):
        """Authentifie l'administrateur pour pouvoir invoquer les vues de suppression."""
        super().setUp()
        self.client.force_login(self.admin)

    def test_user_deletion_cleans_up_all_references(self):
        """Supprimer un professeur détache ses cours (FK SET_NULL) avant de supprimer le compte."""
        url = reverse("dashboard:admin_user_delete", args=[self.prof.pk])
        response = self.client.post(url, secure=True)

        self.assertEqual(response.status_code, 302)
        self.assertFalse(User.objects.filter(pk=self.prof.pk).exists())
        self.course1.refresh_from_db()
        self.assertIsNone(self.course1.professeur)

    def test_user_with_inscriptions_is_deactivated_not_deleted(self):
        """Un étudiant ayant des inscriptions est désactivé (soft delete), pas supprimé en dur."""
        url = reverse("dashboard:admin_user_delete", args=[self.student1.pk])
        response = self.client.post(url, secure=True)

        self.assertEqual(response.status_code, 302)
        self.student1.refresh_from_db()
        self.assertTrue(User.objects.filter(pk=self.student1.pk).exists())
        self.assertFalse(self.student1.actif)

    def test_cannot_delete_last_admin(self):
        """Le dernier administrateur actif ne peut pas être supprimé (verrou de sécurité)."""
        url = reverse("dashboard:admin_user_delete", args=[self.admin.pk])
        response = self.client.post(url, secure=True)

        self.assertEqual(response.status_code, 302)
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.actif)

    def test_cannot_delete_self(self):
        """Un administrateur ne peut pas supprimer son propre compte."""
        url = reverse("dashboard:admin_user_delete", args=[self.admin.pk])
        response = self.client.post(url, secure=True)

        self.assertEqual(response.status_code, 302)
        self.assertTrue(User.objects.filter(pk=self.admin.pk).exists())
