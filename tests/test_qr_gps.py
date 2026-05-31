"""
Tests QR code — classe de base et calcul Haversine.
Sous-fichiers:
  test_qr_gps_location.py : GPS enforcement (refus, rayon, null island)
  test_qr_gps_scan.py     : expiration, logs, doublons
"""
from datetime import date, time, timedelta

from django.test import TestCase
from django.utils import timezone

from apps.absences.models import QRAttendanceToken
from apps.absences.views.qr_utils import _haversine
from apps.academic_sessions.models import AnneeAcademique, Seance
from apps.academics.models import Cours, Departement, Faculte
from apps.accounts.models import User
from apps.dashboard.models import SystemSettings
from apps.enrollments.models import Inscription


class BaseQRTestCase(TestCase):
    """Base de test partagée : crée faculté/dept/année/cours/séance/inscription pour les scénarios QR."""

    def setUp(self):
        """Initialise le dataset minimal et configure les coordonnées GPS de l'établissement."""
        self.faculte = Faculte.objects.create(nom_faculte="Faculte QR")
        self.departement = Departement.objects.create(
            nom_departement="Dept QR", id_faculte=self.faculte,
        )
        self.annee = AnneeAcademique.objects.create(libelle="2025-2026", active=True)
        self.prof = User.objects.create_user(
            email="prof_qr@example.com", nom="Prof", prenom="QR",
            password="pass1234", role=User.Role.PROFESSEUR,
        )
        self.student = User.objects.create_user(
            email="stu_qr@example.com", nom="Student", prenom="QR",
            password="pass1234", role=User.Role.ETUDIANT,
        )
        self.course = Cours.objects.create(
            code_cours="QR101", nom_cours="QR Test Course",
            id_departement=self.departement, professeur=self.prof,
            nombre_total_periodes=100, niveau=1, id_annee=self.annee,
        )
        self.seance = Seance.objects.create(
            id_cours=self.course, date_seance=date.today(),
            heure_debut=time(8, 0), heure_fin=time(10, 0),
            id_annee=self.annee,
        )
        self.inscription = Inscription.objects.create(
            id_etudiant=self.student, id_cours=self.course,
            id_annee=self.annee, status=Inscription.Status.EN_COURS,
        )
        # Set up GPS coords for the establishment
        settings = SystemSettings.get_settings()
        settings.gps_latitude = 36.75250
        settings.gps_longitude = 3.04200
        settings.gps_radius_meters = 100
        settings.qr_token_duration_seconds = 60
        settings.save()

    def _create_token(self, verify_location=False, expired=False, **kwargs):
        """Fabrique un ``QRAttendanceToken`` pour la séance courante (option expiré/géolocalisé)."""
        expires_at = timezone.now() + (
            timedelta(seconds=-10) if expired else timedelta(seconds=60)
        )
        return QRAttendanceToken.objects.create(
            seance=self.seance, created_by=self.prof,
            expires_at=expires_at, verify_location=verify_location,
            **kwargs,
        )


class HaversineTest(TestCase):
    """Tests unitaires de la fonction ``_haversine`` (distance géodésique en mètres)."""

    def test_same_point_zero_distance(self):
        """Deux points identiques doivent renvoyer une distance de zéro mètre."""
        self.assertAlmostEqual(_haversine(36.75, 3.04, 36.75, 3.04), 0, places=0)

    def test_known_distance(self):
        """Un degré de latitude vaut ~111 km — tolérance ±500 m."""
        # ~111 km entre ces latitudes
        dist = _haversine(36.0, 3.0, 37.0, 3.0)
        self.assertAlmostEqual(dist, 111_195, delta=500)
