"""
Session creation and validation views — apps/absences/views/professor_session.py

Provides the professor-facing session lifecycle management:

``session_create``
    Unified entry point where the professor creates a session (or retrieves an
    existing one for the same date and course) and then chooses the attendance
    input mode — manual form or QR code scanner.  The ``Seance`` record is
    persisted to the database before the mode redirect so that both paths share
    a single source of truth.

``validate_session``
    Permanently locks a session.  After validation the professor can no longer
    modify absences for that session; the record becomes read-only.

Design notes
------------
- ``session_create`` deactivates any existing active QR tokens for the session
  before creating a new one, ensuring only one active token exists at a time.
- ``validate_session`` uses ``select_for_update()`` to prevent two simultaneous
  requests from double-validating the same session.
- GPS coordinates and the ``verify_location`` flag are passed through from the
  form to the new ``QRAttendanceToken`` so that the QR scan endpoint can
  enforce campus proximity checking.

Part of the UniAbsences absences system.
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
    Unified session creation entry point for professors.

    GET
        Render the session creation form with today's date and default times
        pre-filled.  The professor selects the date, start/end times, and the
        attendance input mode (manual or QR).

    POST
        1. Validate the submitted date and times.
        2. Create or update the ``Seance`` record for the given date and course.
        3. Redirect based on the chosen mode:
           - ``manual`` → redirect to ``mark_absence`` (full-page form).
           - ``qr``     → create (or resume) a ``QRAttendanceToken`` and
                          redirect to ``qr_dashboard``.

    QR mode details
    ---------------
    - If an active, non-expired token already exists for the session, the
      professor is redirected to resume it rather than creating a duplicate.
    - Any previously active tokens for the session are deactivated before a
      new token is created (one active token per session at a time).
    - GPS coordinates and the ``verify_location`` flag are forwarded to the
      new token if provided by the client.

    Parameters
    ----------
    request : HttpRequest
        The incoming HTTP request.
    course_id : int
        Primary key of the ``Cours`` for which the session is being created.

    Returns
    -------
    HttpResponse
        Rendered form on GET, or redirect to the appropriate attendance view
        on POST.

    Raises
    ------
    Http404
        When no ``Cours`` with ``course_id`` exists.
    """
    course = get_object_or_404(Cours, id_cours=course_id)

    # Ownership check — the decorator only verifies the PROFESSEUR role.
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

        # Validate time format before touching the database.
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

        # Retrieve an existing session for this date or create a new one.
        try:
            seance = Seance.objects.get(id_cours=course, date_seance=date_seance)
            # Update times only if they differ to avoid unnecessary DB writes.
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

        # Prevent any modifications to an already-validated session.
        if seance.validated:
            messages.error(request, "Cette séance est déjà validée et verrouillée.")
            return redirect("dashboard:instructor_course_detail", course_id)

        if mode == "qr":
            # Resume an active token if one already exists for this session,
            # rather than creating a duplicate token.
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

            # Deactivate any stale active tokens before creating the new one.
            QRAttendanceToken.objects.filter(seance=seance, is_active=True).update(is_active=False)

            token_kwargs = {
                "seance": seance,
                "created_by": request.user,
                "expires_at": timezone.now() + timedelta(seconds=sys_settings.qr_token_duration_seconds),
                "verify_location": verify_location,
            }

            # Attach GPS coordinates to the token only if both lat and lng are provided
            # and can be parsed as floats; silently ignore invalid values.
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
            # Manual mode — send the professor directly to the attendance form.
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

    # GET — render the form with today's date and sensible default times.
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
    Permanently lock a session so that its attendance records become read-only.

    Once validated, the professor can no longer create, update, or delete
    absences for the session.  This action is irreversible through the normal
    UI.

    A ``select_for_update()`` lock is acquired inside the transaction to prevent
    two concurrent requests from double-validating the same session (e.g., the
    professor clicking "Validate" twice in quick succession).

    Parameters
    ----------
    request : HttpRequest
        The incoming POST request.
    seance_id : int
        Primary key of the ``Seance`` to validate.

    Returns
    -------
    HttpResponse
        Redirect to the attendance form for the session's course on success or
        if the session was already validated.

    Raises
    ------
    Http404
        When no ``Seance`` with ``seance_id`` exists.
    """
    seance = get_object_or_404(Seance, pk=seance_id)

    # Verify the professor owns this session's course.
    if seance.id_cours.professeur != request.user:
        messages.error(request, "Accès non autorisé à cette séance.")
        return redirect("dashboard:instructor_dashboard")

    with transaction.atomic():
        # Re-fetch with a row-level lock to prevent concurrent double-validation.
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
