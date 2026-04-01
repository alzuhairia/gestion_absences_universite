"""
Tests that user-generated content is properly escaped in rendered templates.
"""

from datetime import date, time
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from apps.absences.models import Absence, Justification
from apps.academic_sessions.models import AnneeAcademique, Seance
from apps.academics.models import Cours, Departement, Faculte
from apps.accounts.models import User
from apps.enrollments.models import Inscription


class CommentEscapingTest(TestCase):
    """Verify that user comments are HTML-escaped in rendered pages."""

    @classmethod
    def setUpTestData(cls):
        cls.faculte = Faculte.objects.create(nom_faculte="Fac XSS")
        cls.dept = Departement.objects.create(
            nom_departement="Dept XSS", id_faculte=cls.faculte
        )
        cls.annee = AnneeAcademique.objects.create(libelle="2025-2026", active=True)
        cls.prof = User.objects.create_user(
            email="prof@xss.com", nom="Prof", prenom="X",
            password="pass1234", role=User.Role.PROFESSEUR,
        )
        cls.secretary = User.objects.create_user(
            email="sec@xss.com", nom="Sec", prenom="X",
            password="pass1234", role=User.Role.SECRETAIRE,
        )
        cls.student = User.objects.create_user(
            email="stu@xss.com", nom="Stu", prenom="X",
            password="pass1234", role=User.Role.ETUDIANT,
        )
        cls.xss_payload = '<script>alert("xss")</script>'

        cls.cours = Cours.objects.create(
            code_cours="XSS1", nom_cours="Course XSS",
            nombre_total_periodes=30, id_departement=cls.dept,
            professeur=cls.prof, id_annee=cls.annee, niveau=1,
        )
        cls.inscription = Inscription.objects.create(
            id_etudiant=cls.student, id_cours=cls.cours, id_annee=cls.annee,
        )
        cls.seance = Seance.objects.create(
            date_seance=date(2026, 1, 5), heure_debut=time(8, 0),
            heure_fin=time(10, 0), id_cours=cls.cours, id_annee=cls.annee,
        )
        cls.absence = Absence.objects.create(
            id_inscription=cls.inscription, id_seance=cls.seance,
            type_absence="ABSENT", duree_absence=Decimal("2.0"),
            statut="EN_ATTENTE", encodee_par=cls.secretary,
            note_professeur=cls.xss_payload,
        )
        cls.justification = Justification.objects.create(
            id_absence=cls.absence, state="EN_ATTENTE",
            commentaire=cls.xss_payload,
            commentaire_gestion=cls.xss_payload,
        )

    def test_justification_comment_escaped_in_review_page(self):
        """Justification comments must be HTML-escaped in the review page."""
        self.client.force_login(self.secretary)
        url = reverse(
            "absences:review_justification",
            args=[self.absence.id_absence],
        )
        response = self.client.get(url, secure=True)
        content = response.content.decode()
        # Raw <script> must NOT appear — Django auto-escaping converts it
        self.assertNotIn(self.xss_payload, content)
        # The escaped version must be present (commentaire + commentaire_gestion + note_professeur)
        self.assertIn("&lt;script&gt;", content)

    def test_no_safe_filter_on_templates(self):
        """No template should use |safe on user-generated content."""
        import pathlib

        templates_dir = pathlib.Path("templates")
        safe_violations = []
        for html_file in templates_dir.rglob("*.html"):
            text = html_file.read_text(encoding="utf-8", errors="ignore")
            if "|safe" in text:
                safe_violations.append(str(html_file))
        self.assertEqual(
            safe_violations, [],
            f"|safe found in templates: {safe_violations}",
        )
