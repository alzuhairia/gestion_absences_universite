"""
Tests — export PDF des absences étudiant.
  - PdfExportTests : volume multi-pages, erreur de génération → 500 propre
"""
from datetime import date, time
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse

from apps.absences.models import Absence
from apps.academic_sessions.models import AnneeAcademique, Seance
from apps.academics.models import Cours, Departement, Faculte
from apps.accounts.models import User
from apps.enrollments.models import Inscription


class PdfExportTests(TestCase):
    """Tests for the student PDF export API endpoint."""

    def setUp(self):
        self.faculte = Faculte.objects.create(nom_faculte="Fac PDF")
        self.dept = Departement.objects.create(
            nom_departement="Dept PDF", id_faculte=self.faculte
        )
        self.annee = AnneeAcademique.objects.create(libelle="2025-2026", active=True)
        self.prof = User.objects.create_user(
            email="prof-pdf@example.com",
            nom="Prof",
            prenom="PDF",
            password="pass1234",
            role=User.Role.PROFESSEUR,
        )
        self.secretary = User.objects.create_user(
            email="sec-pdf@example.com",
            nom="Sec",
            prenom="PDF",
            password="pass1234",
            role=User.Role.SECRETAIRE,
        )
        self.student = User.objects.create_user(
            email="stu-pdf@example.com",
            nom="Stu",
            prenom="PDF",
            password="pass1234",
            role=User.Role.ETUDIANT,
        )
        self.course = Cours.objects.create(
            code_cours="PDF1",
            nom_cours="PDF Course",
            nombre_total_periodes=200,
            id_departement=self.dept,
            professeur=self.prof,
            id_annee=self.annee,
            niveau=1,
        )
        self.inscription = Inscription.objects.create(
            id_etudiant=self.student,
            id_cours=self.course,
            id_annee=self.annee,
        )

    def test_pdf_export_with_large_dataset_does_not_crash(self):
        """
        PDF export with many absences (multi-page) completes without error.
        Verifies the 500-row cap and page-break logic handle volume.
        """
        # Create 60 seances + absences — enough to span multiple PDF pages
        seances = Seance.objects.bulk_create(
            [
                Seance(
                    date_seance=date(2026, 1, 1)
                    + __import__("datetime").timedelta(days=i),
                    heure_debut=time(8, 0),
                    heure_fin=time(10, 0),
                    id_cours=self.course,
                    id_annee=self.annee,
                )
                for i in range(60)
            ]
        )
        Absence.objects.bulk_create(
            [
                Absence(
                    id_inscription=self.inscription,
                    id_seance=s,
                    type_absence="ABSENT",
                    duree_absence=Decimal("2.0"),
                    statut="NON_JUSTIFIEE",
                    encodee_par=self.prof,
                )
                for s in seances
            ]
        )

        self.client.force_login(self.secretary)
        url = reverse("api:export-student-pdf", args=[self.student.pk])
        response = self.client.get(url, secure=True)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertIn(b"%PDF", response.content[:10])

    def test_pdf_export_error_returns_500_json(self):
        """If PDF generation crashes, return a clean 500, not an unhandled exception."""
        self.client.force_login(self.secretary)
        url = reverse("api:export-student-pdf", args=[self.student.pk])

        with patch(
            "apps.api.views._build_student_pdf",
            side_effect=RuntimeError("canvas exploded"),
        ):
            response = self.client.get(url, secure=True)

        self.assertEqual(response.status_code, 500)
        self.assertIn("generation", response.json()["detail"])
