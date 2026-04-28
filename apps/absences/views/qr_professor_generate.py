"""
FICHIER : apps/absences/views/qr_professor_generate.py
RESPONSABILITE : Création de séance et génération du token QR de présence

SÉCURITÉ : @professor_required + vérification course.professeur == request.user
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
    """Le professeur crée une séance et génère un token QR de présence."""
    course = get_object_or_404(Cours, id_cours=course_id)
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

        try:
            seance = Seance.objects.get(id_cours=course, date_seance=date_seance)
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

        if seance.validated:
            messages.error(request, "Cette séance est déjà validée et verrouillée.")
            return redirect("dashboard:instructor_course_detail", course_id)

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

        prof_lat = request.POST.get("latitude")
        prof_lng = request.POST.get("longitude")
        verify_location = request.POST.get("verify_location") == "on"

        from apps.dashboard.models import SystemSettings
        sys_settings = SystemSettings.get_settings()

        QRAttendanceToken.objects.filter(seance=seance, is_active=True).update(is_active=False)

        token_kwargs = {
            "seance": seance,
            "created_by": request.user,
            "expires_at": timezone.now() + timedelta(seconds=sys_settings.qr_token_duration_seconds),
            "verify_location": verify_location,
        }
        try:
            if prof_lat and prof_lng:
                token_kwargs["latitude"] = float(prof_lat)
                token_kwargs["longitude"] = float(prof_lng)
        except (ValueError, TypeError):
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

    today = timezone.localdate().isoformat()
    return render(request, "absences/qr_generate.html", {
        "course": course,
        "today": today,
        "default_start": "08:00",
        "default_end": "09:30",
    })
