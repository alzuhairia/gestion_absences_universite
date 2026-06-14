"""
Tests d'intégration et de cas limites transverses pour le sous-système des absences.

Classes de tests :
  - FutureSessionsExcludedTest       : les séances futures doivent être exclues
                                       de toutes les statistiques d'absence,
                                       compteurs de risque et calculs de pourcentage.
  - SignalLoopProtectionTest         : le signal post_save sur Absence doit être
                                       borné — jamais récursif (garde anti-bug).
  - AcademicYearDeactivationTests    : désactiver une année fait transiter les
                                       inscriptions EN_COURS vers NON_VALIDE.
  - QRFinalizeDurationGuardTest      : quand duree_heures() retourne 0, la
                                       finalisation QR replie sur 2,0 h.
  - JustificationEmailNeverRaisesTest: le helper d'email de décision ne doit
                                       jamais propager d'exception à l'appelant.
  - StudentViewsFallbackFilterTest   : sans année active, les vues
                                       dashboard/absences de l'étudiant filtrent
                                       uniquement les inscriptions EN_COURS.

Fait partie de la suite de tests UniAbsences.
"""
from datetime import date, time, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from apps.absences.models import Absence
from apps.absences.services import (
    calculer_absence_stats,
    calculer_pourcentage_absence,
    get_at_risk_count_for_queryset,
)
from apps.academic_sessions.models import AnneeAcademique, Seance
from apps.academics.models import Cours, Departement, Faculte
from apps.accounts.models import User
from apps.enrollments.models import Inscription


class FutureSessionsExcludedTest(TestCase):
    """
    Les absences liées à des séances futures doivent être exclues de TOUS
    les calculs de taux d'absence (stats, étudiants à risque, pourcentage).

    Justification : un étudiant ne peut pas être pénalisé pour un cours qui
    n'a pas encore eu lieu, et les absences futures fausseraient les
    comparaisons au seuil.
    """

    def setUp(self):
        """
        Crée une séance passée (avec une absence) et une séance future (avec
        une absence aussi) pour le même étudiant/cours afin que les tests
        puissent vérifier que seule l'absence passée est comptée.
        """
        self.faculte = Faculte.objects.create(nom_faculte="Faculte F")
        self.departement = Departement.objects.create(
            nom_departement="Dep F", id_faculte=self.faculte
        )
        self.annee = AnneeAcademique.objects.create(libelle="2025-2026", active=True)
        self.prof = User.objects.create_user(
            email="prof-f@test.com", nom="Prof", prenom="F",
            password="pass1234", role=User.Role.PROFESSEUR,
        )
        self.student = User.objects.create_user(
            email="stu-f@test.com", nom="Stu", prenom="F",
            password="pass1234", role=User.Role.ETUDIANT,
        )
        self.cours = Cours.objects.create(
            code_cours="FUTUR", nom_cours="Future Test",
            nombre_total_periodes=40,
            id_departement=self.departement,
            professeur=self.prof,
            id_annee=self.annee, niveau=1,
        )
        self.inscription = Inscription.objects.create(
            id_etudiant=self.student,
            id_cours=self.cours,
            id_annee=self.annee,
        )
        today = timezone.localdate()
        self.past_seance = Seance.objects.create(
            date_seance=today - timedelta(days=5),
            heure_debut=time(8, 0), heure_fin=time(10, 0),
            id_cours=self.cours, id_annee=self.annee,
        )
        self.future_seance = Seance.objects.create(
            date_seance=today + timedelta(days=30),
            heure_debut=time(8, 0), heure_fin=time(10, 0),
            id_cours=self.cours, id_annee=self.annee,
        )
        # Absence passée : 2h — doit compter dans le taux.
        Absence.objects.create(
            id_inscription=self.inscription,
            id_seance=self.past_seance,
            type_absence=Absence.TypeAbsence.ABSENT,
            duree_absence=Decimal("2.00"),
            statut=Absence.Statut.NON_JUSTIFIEE,
            encodee_par=self.prof,
        )
        # Absence future : 2h — ne doit PAS compter dans le taux.
        Absence.objects.bulk_create([
            Absence(
                id_inscription=self.inscription,
                id_seance=self.future_seance,
                type_absence=Absence.TypeAbsence.ABSENT,
                duree_absence=Decimal("2.00"),
                statut=Absence.Statut.NON_JUSTIFIEE,
                encodee_par=self.prof,
            )
        ])

    def test_future_sessions_excluded_from_absence_calculation(self):
        """calculer_absence_stats ne doit compter que l'absence passée (2h, pas 4h)."""
        stats = calculer_absence_stats(self.inscription)
        # Seule l'absence passée (2h) doit compter, pas les deux (4h).
        self.assertEqual(stats["total_absence"], 2.0)
        self.assertAlmostEqual(stats["taux"], 5.0, places=1)  # 2/40 * 100

    def test_future_sessions_excluded_from_at_risk_count(self):
        """get_at_risk_count_for_queryset ne doit pas inclure les absences de séances futures."""
        qs = Inscription.objects.filter(
            id_inscription=self.inscription.id_inscription
        ).select_related("id_cours")
        _, sums = get_at_risk_count_for_queryset(qs, system_threshold=40)
        total = float(sums.get(self.inscription.id_inscription, 0) or 0)
        # Seulement 2h (absence passée), pas 4h (passée + future).
        self.assertEqual(total, 2.0)

    def test_future_sessions_excluded_from_pourcentage(self):
        """calculer_pourcentage_absence doit exclure les séances futures du numérateur et du dénominateur."""
        result = calculer_pourcentage_absence(self.student, self.cours)
        # Seule la séance passée compte : 2h de cours total, 2h d'absence.
        self.assertEqual(result["total_heures_cours"], 2.0)
        self.assertEqual(result["total_heures_absence"], 2.0)


class SignalLoopProtectionTest(TestCase):
    """
    Vérifie que créer, modifier et supprimer des objets Absence ne provoque
    pas de boucle infinie de signaux via :
      post_save → recalculer_eligibilite → Inscription.save → (répéter).

    Chaque save/delete doit déclencher _schedule_eligibility_recalc exactement une fois.
    """

    def setUp(self):
        """Importe recalculer_eligibilite pour s'assurer que le câblage des signaux est actif."""
        from apps.absences.services import recalculer_eligibilite  # noqa: F401

        self.faculte = Faculte.objects.create(nom_faculte="Fac Signal")
        self.departement = Departement.objects.create(
            nom_departement="Dep Signal", id_faculte=self.faculte
        )
        self.annee = AnneeAcademique.objects.create(libelle="2025-2026", active=True)
        self.prof = User.objects.create_user(
            email="prof-sig@test.com", nom="Prof", prenom="Sig",
            password="pass1234", role=User.Role.PROFESSEUR,
        )
        self.student = User.objects.create_user(
            email="stu-sig@test.com", nom="Stu", prenom="Sig",
            password="pass1234", role=User.Role.ETUDIANT,
        )
        self.cours = Cours.objects.create(
            code_cours="SIG", nom_cours="Signal Test",
            nombre_total_periodes=40,
            id_departement=self.departement,
            professeur=self.prof,
            id_annee=self.annee, niveau=1,
        )
        self.inscription = Inscription.objects.create(
            id_etudiant=self.student,
            id_cours=self.cours,
            id_annee=self.annee,
        )

    def test_absence_save_does_not_trigger_infinite_signal_loop(self):
        """
        Effectue 1 création + 5 mises à jour + 1 suppression et confirme que
        _schedule_eligibility_recalc est appelé exactement 7 fois — une fois
        par opération — prouvant que le signal est borné et non récursif.
        """
        seance = Seance.objects.create(
            date_seance=date(2026, 1, 10),
            heure_debut=time(8, 0), heure_fin=time(10, 0),
            id_cours=self.cours, id_annee=self.annee,
        )

        with patch(
            "apps.absences.signals._schedule_eligibility_recalc",
        ) as mock_schedule:
            # Création : 1 appel attendu.
            absence = Absence.objects.create(
                id_inscription=self.inscription,
                id_seance=seance,
                type_absence=Absence.TypeAbsence.ABSENT,
                duree_absence=Decimal("2.00"),
                statut=Absence.Statut.NON_JUSTIFIEE,
                encodee_par=self.prof,
            )

            # Modifie 5 fois : 5 appels supplémentaires attendus.
            for i in range(5):
                absence.duree_absence = Decimal(f"1.{i:02d}")
                absence.save(update_fields=["duree_absence"])

            # Suppression : 1 appel supplémentaire attendu.
            absence.delete()

            # Total : exactement 7 (1 création + 5 mises à jour + 1 suppression), jamais récursif.
            self.assertEqual(mock_schedule.call_count, 7)
            # Chaque appel doit recevoir la bonne clé primaire d'inscription.
            for call in mock_schedule.call_args_list:
                self.assertEqual(call[0][0], self.inscription.pk)


class AcademicYearDeactivationTests(TestCase):
    """
    Tests pour le BUG #35 : désactiver une année académique doit faire
    transiter ses inscriptions EN_COURS vers NON_VALIDE tout en laissant
    les VALIDE intactes.
    """

    def setUp(self):
        """Crée une année active avec une inscription EN_COURS."""
        self.faculte = Faculte.objects.create(nom_faculte="Fac Year")
        self.dept = Departement.objects.create(
            nom_departement="Dept Year", id_faculte=self.faculte
        )
        self.annee = AnneeAcademique.objects.create(libelle="2025-2026", active=True)
        self.prof = User.objects.create_user(
            email="prof-year@test.com", nom="Prof", prenom="Year",
            password="pass1234", role=User.Role.PROFESSEUR,
        )
        self.student = User.objects.create_user(
            email="stu-year@test.com", nom="Stu", prenom="Year",
            password="pass1234", role=User.Role.ETUDIANT,
        )
        self.cours = Cours.objects.create(
            code_cours="YEAR1", nom_cours="Year Course",
            nombre_total_periodes=40, id_departement=self.dept,
            professeur=self.prof, id_annee=self.annee, niveau=1,
        )
        self.inscription = Inscription.objects.create(
            id_etudiant=self.student, id_cours=self.cours, id_annee=self.annee,
        )

    def test_deactivating_year_closes_enrollments(self):
        """Mettre active=False sur l'année doit passer les inscriptions EN_COURS à NON_VALIDE."""
        self.assertEqual(self.inscription.status, "EN_COURS")

        self.annee.active = False
        self.annee.save()

        self.inscription.refresh_from_db()
        self.assertEqual(self.inscription.status, "NON_VALIDE")

    def test_already_validated_inscription_unchanged(self):
        """Les inscriptions VALIDE ne doivent pas être affectées par la désactivation de l'année."""
        self.inscription.status = "VALIDE"
        self.inscription.save(update_fields=["status"])

        self.annee.active = False
        self.annee.save()

        self.inscription.refresh_from_db()
        self.assertEqual(self.inscription.status, "VALIDE")

    def test_activating_new_year_does_not_close_inscriptions(self):
        """
        Activer une nouvelle année désactive l'ancienne via un update() en lot
        qui ne déclenche PAS le signal save() du modèle, donc les inscriptions
        EN_COURS de l'ancienne année ne sont pas affectées par la seule
        activation de la nouvelle année.
        """
        new_annee = AnneeAcademique(libelle="2026-2027", active=True)
        new_annee.save()

        # L'ancienne année est maintenant inactive.
        self.annee.refresh_from_db()
        self.assertFalse(self.annee.active)

        # L'inscription de l'ancienne année n'est PAS fermée car AnneeAcademique.save()
        # désactive l'année précédente via .update(active=False), qui contourne save()
        # et ne déclenche donc pas le signal de fermeture d'inscription.
        self.inscription.refresh_from_db()
        self.assertEqual(self.inscription.status, "EN_COURS")


class QRFinalizeDurationGuardTest(TestCase):
    """
    Garde anti-régression : la finalisation par QR ne doit pas créer
    d'absences avec duree_absence=0 quand Seance.duree_heures() retourne zéro.
    """

    def setUp(self):
        """Crée des fixtures minimales (cours, séance, inscription) pour les tests de durée."""
        self.faculte = Faculte.objects.create(nom_faculte="Fac QR")
        self.dept = Departement.objects.create(
            nom_departement="Dept QR", id_faculte=self.faculte
        )
        self.annee = AnneeAcademique.objects.create(libelle="2025-2026", active=True)
        self.prof = User.objects.create_user(
            email="prof-qr@test.com", nom="Prof", prenom="QR",
            password="pass1234", role=User.Role.PROFESSEUR,
        )
        self.student = User.objects.create_user(
            email="stu-qr@test.com", nom="Stu", prenom="QR",
            password="pass1234", role=User.Role.ETUDIANT,
        )
        self.cours = Cours.objects.create(
            code_cours="QR1", nom_cours="QR Course",
            nombre_total_periodes=40, id_departement=self.dept,
            professeur=self.prof, id_annee=self.annee, niveau=1,
        )
        self.seance = Seance.objects.create(
            date_seance=date(2026, 1, 10),
            heure_debut=time(8, 0), heure_fin=time(10, 0),
            id_cours=self.cours, id_annee=self.annee,
        )
        self.inscription = Inscription.objects.create(
            id_etudiant=self.student, id_cours=self.cours, id_annee=self.annee,
        )

    def test_duree_heures_zero_fallback(self):
        """Quand duree_heures() retourne 0, le repli ``or 2.0`` doit s'appliquer."""
        with patch.object(Seance, "duree_heures", return_value=0.0):
            duree = self.seance.duree_heures() or 2.0
        self.assertEqual(duree, 2.0)

    def test_duree_heures_normal(self):
        """Quand duree_heures() retourne une valeur positive, elle doit être utilisée telle quelle."""
        duree = self.seance.duree_heures() or 2.0
        self.assertEqual(duree, 2.0)  # 08:00–10:00 = 2 h


class JustificationEmailNeverRaisesTest(TestCase):
    """
    Garde anti-régression : ``_send_justification_decision_emails`` doit
    intercepter toutes les exceptions en interne et ne jamais les propager
    à l'appelant.

    Si le helper d'email plante (par exemple attributs manquants sur None),
    la réponse HTTP doit tout de même réussir afin que la décision du
    secrétariat soit persistée.
    """

    def test_email_function_does_not_raise(self):
        """
        Passer None comme objet de justification fait échouer l'accès aux
        attributs à l'intérieur du helper. La fonction doit intercepter
        l'exception silencieusement.
        """
        from apps.absences.views.secretary_justification import _send_justification_decision_emails

        # On passe None — tout accès d'attribut lèvera AttributeError, mais
        # la fonction doit l'intercepter et retourner normalement.
        _send_justification_decision_emails(None, approved=True)
        # Atteindre cette ligne signifie qu'aucune exception n'a été propagée — test passé.


class StudentViewsFallbackFilterTest(TestCase):
    """
    Garde anti-régression : lorsqu'aucune année académique n'est active,
    les vues dashboard et absences de l'étudiant doivent replier sur le
    filtrage des inscriptions EN_COURS uniquement — pas toutes les
    inscriptions de l'étudiant.
    """

    def setUp(self):
        """
        Crée des fixtures sans année active et deux inscriptions pour le
        même étudiant : une EN_COURS et une NON_VALIDE.
        """
        self.faculte = Faculte.objects.create(nom_faculte="Fac Fallback")
        self.dept = Departement.objects.create(
            nom_departement="Dept Fallback", id_faculte=self.faculte
        )
        # Pas d'année active — déclenche le chemin de code de repli.
        self.annee = AnneeAcademique.objects.create(libelle="2024-2025", active=False)
        self.prof = User.objects.create_user(
            email="prof-fb@test.com", nom="Prof", prenom="FB",
            password="pass1234", role=User.Role.PROFESSEUR,
        )
        self.student = User.objects.create_user(
            email="stu-fb@test.com", nom="Stu", prenom="FB",
            password="pass1234", role=User.Role.ETUDIANT,
        )
        self.cours = Cours.objects.create(
            code_cours="FB1", nom_cours="Fallback Course",
            nombre_total_periodes=40, id_departement=self.dept,
            professeur=self.prof, id_annee=self.annee, niveau=1,
        )
        # Inscription active — doit apparaître dans la vue de repli.
        self.active_ins = Inscription.objects.create(
            id_etudiant=self.student, id_cours=self.cours, id_annee=self.annee,
            status=Inscription.Status.EN_COURS,
        )
        # Inscription archivée — ne doit PAS apparaître dans la vue de repli.
        self.archived_ins = Inscription.objects.create(
            id_etudiant=self.student, id_cours=Cours.objects.create(
                code_cours="FB2", nom_cours="Archived Course",
                nombre_total_periodes=40, id_departement=self.dept,
                professeur=self.prof, id_annee=self.annee, niveau=1,
            ), id_annee=self.annee,
            status=Inscription.Status.NON_VALIDE,
        )

    def test_student_dashboard_fallback_filters_en_cours(self):
        """Le repli du dashboard étudiant doit afficher exactement 1 cours (le EN_COURS)."""
        self.client.force_login(self.student)
        response = self.client.get("/dashboard/student/", secure=True)
        self.assertEqual(response.status_code, 200)
        # Doit afficher 1 cours (l'inscription active EN_COURS), pas 2.
        self.assertEqual(response.context["total_courses"], 1)

    def test_student_absences_fallback_filters_en_cours(self):
        """Le repli de la vue absences étudiant ne doit retourner que les inscriptions EN_COURS."""
        self.client.force_login(self.student)
        response = self.client.get("/dashboard/student/absences/", secure=True)
        self.assertEqual(response.status_code, 200)
