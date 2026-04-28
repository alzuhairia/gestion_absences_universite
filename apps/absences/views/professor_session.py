"""
Création et validation de séances — vue professeur.

Fonctionnalités :
  - session_create   : point d'entrée unifié — le professeur crée une séance
                       puis choisit le mode de saisie (manuel ou QR code)
  - validate_session : verrouillage définitif d'une séance (lecture seule ensuite)
"""
import datetime
import logging
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_POST

from ..models import QRAttendanceToken
from apps.academic_sessions.models import AnneeAcademique, Seance
from apps.academics.models import Cours
from apps.audits.utils import log_action
from apps.dashboard.decorators import professor_required

logger = logging.getLogger(__name__)


@login_required
@professor_required
@require_http_methods(["GET", "POST"])
def session_create(request, course_id):
    """
    Point d'entrée unifié : le professeur crée d'abord une séance,
    puis choisit le mode de saisie (manuel ou QR code).
    La séance est persistée avant de choisir le mode.
    """
    course = get_object_or_404(Cours, id_cours=course_id)
    if course.professeur is None or course.professeur.pk != request.user.pk:
        messages.error(request, "Accès non autorisé à ce cours.")
        return redirect("dashboard:instructor_dashboard")

    academic_year = AnneeAcademique.objects.filter(active=True).first()
    if not academic_year:
        messages.error(request, "Aucune année académique active.")
        return redirect("dashboard:instructor_course_detail", course_id)

    if request.method == "POST":
        date_seance = request.POST.get("date_seance", "").strip()
        heure_debut = request.POST.get("heure_debut", "").strip()
        heure_fin = request.POST.get("heure_fin", "").strip()
        mode = request.POST.get("mode", "manual")

        if not all([date_seance, heure_debut, heure_fin]):
            messages.error(request, "Veuillez remplir tous les champs obligatoires.")
            return redirect("absences:session_create", course_id=course_id)

        try:
            fmt = "%H:%M"
            t_debut = datetime.datetime.strptime(heure_debut, fmt)
            t_fin = datetime.datetime.strptime(heure_fin, fmt)
        except (TypeError, ValueError):
            messages.error(request, "Format d'heure invalide (HH:MM attendu).")
            return redirect("absences:session_create", course_id=course_id)

        if t_fin <= t_debut:
            messages.error(request, "L'heure de fin doit être postérieure à l'heure de début.")
            return redirect("absences:session_create", course_id=course_id)

        try:
            seance = Seance.objects.get(id_cours=course, date_seance=date_seance)
            updated_fields = []
            if seance.heure_debut != t_debut.time():
                seance.heure_debut = heure_debut
                updated_fields.append("heure_debut")
            if seance.heure_fin != t_fin.time():
                seance.heure_fin = heure_fin
                updated_fields.append("heure_fin")
            if updated_fields:
                seance.save(update_fields=updated_fields)
            messages.info(request, "Séance existante récupérée.")
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

        if mode == "qr":
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

            from apps.dashboard.models import SystemSettings
            sys_settings = SystemSettings.get_settings()
            verify_location = request.POST.get("verify_location") == "on"

            QRAttendanceToken.objects.filter(seance=seance, is_active=True).update(is_active=False)

            token_kwargs = {
                "seance": seance,
                "created_by": request.user,
                "expires_at": timezone.now() + timedelta(seconds=sys_settings.qr_token_duration_seconds),
                "verify_location": verify_location,
            }
            try:
                lat = request.POST.get("latitude")
                lng = request.POST.get("longitude")
                if lat and lng:
                    token_kwargs["latitude"] = float(lat)
                    token_kwargs["longitude"] = float(lng)
            except (ValueError, TypeError):
                pass

            new_token = QRAttendanceToken.objects.create(**token_kwargs)
            log_action(
                request.user,
                f"Séance créée (QR) — {course.code_cours} {date_seance}",
                request,
                niveau="INFO",
                objet_type="SEANCE",
                objet_id=seance.id_seance,
            )
            return redirect("absences:qr_dashboard", token=new_token.token)
        else:
            log_action(
                request.user,
                f"Séance créée (manuel) — {course.code_cours} {date_seance}",
                request,
                niveau="INFO",
                objet_type="SEANCE",
                objet_id=seance.id_seance,
            )
            return redirect(
                f"{reverse('absences:mark_absence', args=[course_id])}?date={date_seance}"
            )

    today = timezone.localdate().isoformat()
    return render(request, "absences/session_create.html", {
        "course": course,
        "today": today,
        "default_start": "08:30",
        "default_end": "10:30",
    })


@login_required
@professor_required
@require_POST
def validate_session(request, seance_id):
    """
    Valide une séance et verrouille les présences définitivement.
    Après validation, le professeur ne peut plus modifier les absences.
    """
    seance = get_object_or_404(Seance, pk=seance_id)

    if seance.id_cours.professeur != request.user:
        messages.error(request, "Accès non autorisé à cette séance.")
        return redirect("dashboard:instructor_dashboard")

    with transaction.atomic():
        seance = Seance.objects.select_for_update().get(pk=seance_id)
        if seance.validated:
            messages.info(request, "Cette séance est déjà validée.")
            return redirect("absences:mark_absence", course_id=seance.id_cours.pk)

        seance.validated = True
        seance.validated_by = request.user
        seance.date_validated = timezone.now()
        seance.save(update_fields=["validated", "validated_by", "date_validated"])

        log_action(
            request.user,
            f"Professeur a validé la séance du {seance.date_seance} pour {seance.id_cours.code_cours}",
            request,
            niveau="INFO",
            objet_type="SEANCE",
            objet_id=seance.id_seance,
        )

    messages.success(
        request,
        f"La séance du {seance.date_seance} a été validée. Les présences sont verrouillées.",
    )
    return redirect("absences:mark_absence", course_id=seance.id_cours.pk)
