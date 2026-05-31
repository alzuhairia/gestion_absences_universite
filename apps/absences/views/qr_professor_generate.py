"""
QR session creation view — apps/absences/views/qr_professor_generate.py

``qr_generate``
    Allows a professor to create (or reuse) a ``Seance`` for a given course
    date and issue a short-lived signed ``QRAttendanceToken``.  The generated
    token is embedded into a QR code that students scan to record their
    attendance.  After creation the professor is redirected to the live
    ``qr_dashboard`` where they can monitor scans in real time.

Token lifecycle
---------------
- A new token is valid for ``SystemSettings.qr_token_duration_seconds`` seconds
  (default: 30 minutes).
- Any previously active token for the same session is deactivated before a new
  one is created, ensuring that only one valid QR code exists per session.
- If an active, non-expired token already exists, the professor is redirected
  to resume it (idempotent behaviour — no duplicate tokens).

GPS support
-----------
If the professor's browser provides GPS coordinates and the
``verify_location`` checkbox is checked, the coordinates are stored on the
token.  The student-side ``qr_scan`` view then uses them to enforce campus
proximity (Haversine distance check).

Security controls
-----------------
- ``@professor_required`` — only professors may access this view.
- Ownership check: ``course.professeur == request.user`` prevents a professor
  from generating QR codes for another professor's course.

Part of the UniAbsences absences system.
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
    Create a session and generate a QR attendance token for a course.

    GET
        Render the QR generation form with today's date and default session
        times pre-filled.

    POST
        1. Validate that all required fields are present.
        2. Create or update the ``Seance`` record for the submitted date.
        3. If an active token already exists for the session, resume it.
        4. Otherwise deactivate stale tokens and create a new ``QRAttendanceToken``.
        5. Attach GPS coordinates to the token when provided by the client.
        6. Redirect to ``qr_dashboard`` with the new token.

    Parameters
    ----------
    request : HttpRequest
        The incoming HTTP request.
    course_id : int
        Primary key of the ``Cours`` for which the QR session is being created.

    Returns
    -------
    HttpResponse
        Rendered form on GET, or redirect to ``qr_dashboard`` on POST success.

    Raises
    ------
    Http404
        When no ``Cours`` with ``course_id`` exists.
    """
    course = get_object_or_404(Cours, id_cours=course_id)

    # Secondary ownership check beyond the role decorator.
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

        # Create or retrieve the session record for this course and date.
        try:
            seance = Seance.objects.get(id_cours=course, date_seance=date_seance)
            # Update times only when they have actually changed (HH:MM comparison).
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

        # Prevent QR generation on an already-locked session.
        if seance.validated:
            messages.error(request, "Cette séance est déjà validée et verrouillée.")
            return redirect("dashboard:instructor_course_detail", course_id)

        # Idempotent: resume an existing active token if one is still valid
        # rather than creating a second QR code for the same session.
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

        # Read optional GPS coordinates submitted by the professor's browser.
        prof_lat = request.POST.get("latitude")
        prof_lng = request.POST.get("longitude")
        verify_location = request.POST.get("verify_location") == "on"

        from apps.dashboard.models import SystemSettings
        sys_settings = SystemSettings.get_settings()

        # Deactivate any stale active tokens before creating the new one.
        QRAttendanceToken.objects.filter(seance=seance, is_active=True).update(is_active=False)

        token_kwargs = {
            "seance": seance,
            "created_by": request.user,
            "expires_at": timezone.now() + timedelta(seconds=sys_settings.qr_token_duration_seconds),
            "verify_location": verify_location,
        }

        # Attach GPS coordinates only when both values are provided and valid floats.
        try:
            if prof_lat and prof_lng:
                token_kwargs["latitude"] = float(prof_lat)
                token_kwargs["longitude"] = float(prof_lng)
        except (ValueError, TypeError):
            # Invalid coordinate data — proceed without GPS enforcement.
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

    # GET — render the form with today's date and default session times.
    today = timezone.localdate().isoformat()
    return render(request, "absences/qr_generate.html", {
        "course": course,
        "today": today,
        "default_start": "08:00",
        "default_end": "09:30",
    })
