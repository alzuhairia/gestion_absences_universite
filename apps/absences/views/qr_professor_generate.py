"""
Vue de création d'une séance QR — apps/absences/views/qr_professor_generate.py

``qr_generate``
    Permet à un professeur de créer (ou réutiliser) une ``Seance`` pour une
    date de cours donnée et d'émettre un ``QRAttendanceToken`` signé à courte
    durée de vie. Le token généré est intégré dans un QR code que les
    étudiants scannent pour enregistrer leur présence. Après la création, le
    professeur est redirigé vers le ``qr_dashboard`` en direct où il peut
    suivre les scans en temps réel.

Cycle de vie du token
---------------------
- Un nouveau token est valide pendant ``SystemSettings.qr_token_duration_seconds``
  secondes (par défaut : 30 minutes).
- Tout token actif précédent pour la même séance est désactivé avant qu'un
  nouveau soit créé, garantissant qu'un seul QR code valide existe par séance.
- Si un token actif et non expiré existe déjà, le professeur est redirigé pour
  le reprendre (comportement idempotent — pas de tokens en doublon).

Prise en charge du GPS
----------------------
Si le navigateur du professeur fournit des coordonnées GPS et que la case
``verify_location`` est cochée, les coordonnées sont stockées sur le token.
La vue ``qr_scan`` côté étudiant les utilise alors pour imposer la proximité
au campus (contrôle de distance Haversine).

Contrôles de sécurité
---------------------
- ``@professor_required`` — seuls les professeurs peuvent accéder à cette vue.
- Contrôle de propriété : ``course.professeur == request.user`` empêche un
  professeur de générer des QR codes pour le cours d'un autre professeur.

Fait partie du système d'absences UniAbsences.
"""
import logging
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from apps.academic_sessions.models import AnneeAcademique, Seance
from apps.academics.models import Cours
from apps.audits.utils import log_action
from apps.dashboard.decorators import professor_required
from ..models import QRAttendanceToken

logger = logging.getLogger(__name__)


@login_required
@professor_required
@require_http_methods(["GET", "POST"])
def qr_generate(request, course_id):
    """
    Crée une séance et génère un token QR de présence pour un cours.

    GET
        Rend le formulaire de génération du QR avec la date du jour et les
        horaires de séance par défaut pré-remplis.

    POST
        1. Vérifie que tous les champs requis sont présents.
        2. Crée ou met à jour l'enregistrement ``Seance`` pour la date soumise.
        3. Si un token actif existe déjà pour la séance, le reprend.
        4. Sinon, désactive les tokens obsolètes et crée un nouveau
           ``QRAttendanceToken``.
        5. Attache les coordonnées GPS au token lorsqu'elles sont fournies
           par le client.
        6. Redirige vers ``qr_dashboard`` avec le nouveau token.

    Paramètres
    ----------
    request : HttpRequest
        La requête HTTP entrante.
    course_id : int
        Clé primaire du ``Cours`` pour lequel la séance QR est créée.

    Retour
    ------
    HttpResponse
        Formulaire rendu sur GET, ou redirection vers ``qr_dashboard`` en
        cas de succès sur POST.

    Lève
    ----
    Http404
        Quand aucun ``Cours`` n'existe avec ``course_id``.
    """
    course = get_object_or_404(Cours, id_cours=course_id)

    # Contrôle de propriété secondaire au-delà du décorateur de rôle.
    if course.professeur is None or course.professeur.pk != request.user.pk:
        messages.error(request, "Accès non autorisé à ce cours.")
        return redirect("dashboard:instructor_dashboard")

    academic_year = AnneeAcademique.objects.filter(active=True).first()
    if not academic_year:
        messages.error(request, "Aucune année académique active.")
        return redirect("dashboard:instructor_course_detail", course_id)

    if request.method == "POST":
        date_seance = request.POST.get("date_seance")
        heure_debut = request.POST.get("heure_debut")
        heure_fin = request.POST.get("heure_fin")

        if not all([date_seance, heure_debut, heure_fin]):
            messages.error(request, "Veuillez remplir tous les champs.")
            return redirect("absences:qr_generate", course_id=course_id)

        # Crée ou récupère l'enregistrement de séance pour ce cours et cette date.
        try:
            seance = Seance.objects.get(id_cours=course, date_seance=date_seance)
            # Met à jour les horaires uniquement quand ils ont réellement changé (comparaison HH:MM).
            updated_fields = []
            if str(seance.heure_debut)[:5] != heure_debut:
                seance.heure_debut = heure_debut
                updated_fields.append("heure_debut")
            if str(seance.heure_fin)[:5] != heure_fin:
                seance.heure_fin = heure_fin
                updated_fields.append("heure_fin")
            if updated_fields:
                seance.save(update_fields=updated_fields)
        except Seance.DoesNotExist:
            seance = Seance.objects.create(
                id_cours=course,
                date_seance=date_seance,
                heure_debut=heure_debut,
                heure_fin=heure_fin,
                id_annee=academic_year,
            )

        # Empêche la génération de QR sur une séance déjà verrouillée.
        if seance.validated:
            messages.error(request, "Cette séance est déjà validée et verrouillée.")
            return redirect("dashboard:instructor_course_detail", course_id)

        # Idempotent : reprend un token actif existant s'il est encore valide,
        # plutôt que d'en créer un second pour la même séance.
        existing_token = (
            QRAttendanceToken.objects.filter(
                seance=seance,
                is_active=True,
                expires_at__gt=timezone.now(),
            )
            .order_by("-created_at")
            .first()
        )
        if existing_token:
            messages.info(request, "Un QR de présence est déjà actif — reprise en cours.")
            return redirect("absences:qr_dashboard", token=existing_token.token)

        # Lit les coordonnées GPS facultatives soumises par le navigateur du professeur.
        prof_lat = request.POST.get("latitude")
        prof_lng = request.POST.get("longitude")
        verify_location = request.POST.get("verify_location") == "on"

        from apps.dashboard.models import SystemSettings
        sys_settings = SystemSettings.get_settings()

        # Désactive tout token actif obsolète avant de créer le nouveau.
        QRAttendanceToken.objects.filter(seance=seance, is_active=True).update(is_active=False)

        token_kwargs = {
            "seance": seance,
            "created_by": request.user,
            "expires_at": timezone.now() + timedelta(seconds=sys_settings.qr_token_duration_seconds),
            "verify_location": verify_location,
        }

        # Attache les coordonnées GPS uniquement quand les deux valeurs sont fournies et sont des floats valides.
        try:
            if prof_lat and prof_lng:
                token_kwargs["latitude"] = float(prof_lat)
                token_kwargs["longitude"] = float(prof_lng)
        except (ValueError, TypeError):
            # Données de coordonnées invalides — on continue sans application du GPS.
            pass

        token = QRAttendanceToken.objects.create(**token_kwargs)

        log_action(
            request.user,
            f"QR généré pour {course.code_cours} — séance {date_seance}",
            request,
            niveau="INFO",
            objet_type="SEANCE",
            objet_id=seance.id_seance,
        )
        return redirect("absences:qr_dashboard", token=token.token)

    # GET — rend le formulaire avec la date du jour et les horaires de séance par défaut.
    today = timezone.localdate().isoformat()
    return render(request, "absences/qr_generate.html", {
        "course": course,
        "today": today,
        "default_start": "08:00",
        "default_end": "09:30",
    })
