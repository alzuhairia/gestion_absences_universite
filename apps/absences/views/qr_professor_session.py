"""
QR session lifecycle views — apps/absences/views/qr_professor_session.py

Manages the active QR attendance session after the initial token has been
created by ``qr_generate``.

``qr_dashboard``
    Real-time scan dashboard.  Displays the QR image and a live list of
    students who have scanned, refreshed via HTMX polling.  When called with
    an ``HX-Request`` header the view returns only the ``_qr_scan_list.html``
    partial instead of the full page (HTMX swap).

``qr_refresh_token``
    Token rotation endpoint.  Invalidates the current token, generates a fresh
    signed token with the same GPS settings, and returns either a JSON payload
    (AJAX call) or a redirect (regular form submit).  Existing scan records are
    preserved — only the URL that students scan changes.

``qr_finalize``
    Session close endpoint.  Marks every enrolled student who did not scan as
    ABSENT, deactivates all remaining QR tokens, and locks the session.  Runs
    entirely inside a single atomic transaction to guarantee consistency.

Security controls
-----------------
- ``@professor_required`` on all three views.
- Ownership check: ``course.professeur == request.user`` on every request.
- ``select_for_update()`` in ``qr_finalize`` prevents a concurrent duplicate
  finalization from creating duplicate absences.

Part of the UniAbsences absences system.
"""
import logging
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from apps.academic_sessions.models import Seance
from apps.audits.utils import log_action
from apps.dashboard.decorators import professor_required
from apps.enrollments.models import Inscription
from ..models import Absence, QRAttendanceToken, QRScanRecord
from .qr_utils import _generate_qr_data_uri

logger = logging.getLogger(__name__)


@login_required
@professor_required
@require_GET
def qr_dashboard(request, token):
    """
    Real-time QR attendance dashboard for the professor.

    Renders the QR code image alongside two student lists: those who have
    already scanned and those who have not yet scanned.  Suspicious scans
    (students whose GPS position was far from the classroom) are highlighted.

    HTMX polling
    ------------
    When the request carries an ``HX-Request`` header (i.e., a periodic HTMX
    poll from the dashboard page), only the ``_qr_scan_list.html`` partial is
    returned so the browser can swap the scan list in-place without a full
    reload.

    Parameters
    ----------
    request : HttpRequest
        The incoming GET request.
    token : UUID
        The ``QRAttendanceToken.token`` value from the URL.

    Returns
    -------
    HttpResponse
        Full dashboard page, or the ``_qr_scan_list.html`` partial for HTMX.

    Raises
    ------
    Http404
        When no token with the given UUID exists.
    """
    qr_token = get_object_or_404(QRAttendanceToken, token=token)
    seance = qr_token.seance
    course = seance.id_cours

    # Ownership check — prevent a professor from viewing another course's dashboard.
    if course.professeur is None or course.professeur.pk != request.user.pk:
        messages.error(request, "Accès non autorisé.")
        return redirect("dashboard:instructor_dashboard")

    # Build the absolute scan URL that will be encoded into the QR image.
    scan_url = request.build_absolute_uri(
        reverse("absences:qr_scan", kwargs={"token": str(token)})
    )
    qr_data_uri = _generate_qr_data_uri(scan_url)

    # Fetch all enrollments for this course and academic year.
    inscriptions = list(
        Inscription.objects.filter(
            id_cours=course,
            id_annee=seance.id_annee,
            status=Inscription.Status.EN_COURS,
        ).select_related("id_etudiant")
    )

    # Build a dict of scan records keyed by enrollment PK for O(1) lookup.
    scan_records = {
        sr.inscription.pk if sr.inscription else None: sr
        for sr in QRScanRecord.objects.filter(seance=seance).select_related("inscription")
    }
    scanned_ids = set(scan_records.keys())

    # Partition enrollments into scanned / not-scanned lists and count suspicions.
    scanned = []
    suspicious_count = 0
    for ins in inscriptions:
        if ins.id_inscription in scanned_ids:
            sr = scan_records[ins.id_inscription]
            # Attach the scan record so the template can access GPS and timestamp.
            setattr(ins, "scan_record", sr)
            if sr.is_suspicious:
                suspicious_count += 1
            scanned.append(ins)
    not_scanned = [ins for ins in inscriptions if ins.id_inscription not in scanned_ids]

    from apps.dashboard.models import SystemSettings
    sys_settings = SystemSettings.get_settings()

    ctx = {
        "qr_token": qr_token,
        "seance": seance,
        "course": course,
        "qr_data_uri": qr_data_uri,
        "scan_url": scan_url,
        "scanned": scanned,
        "not_scanned": not_scanned,
        "total_students": len(inscriptions),
        "scanned_count": len(scanned),
        "suspicious_count": suspicious_count,
        "is_expired": qr_token.is_expired,
        "has_gps": qr_token.latitude is not None,
        "verify_location": qr_token.verify_location,
        # Pass the configured QR duration so JavaScript can render a countdown.
        "qr_duration_seconds": sys_settings.qr_token_duration_seconds,
    }

    # HTMX partial response: return only the scan list fragment when polled.
    if request.headers.get("HX-Request"):
        return render(request, "absences/_qr_scan_list.html", ctx)

    return render(request, "absences/qr_dashboard.html", ctx)


@login_required
@professor_required
@require_POST
def qr_refresh_token(request, token):
    """
    Rotate the active QR token to prevent students from sharing the QR image.

    Deactivates the current token and creates a fresh signed token with the
    same GPS settings.  Existing ``QRScanRecord`` entries are preserved because
    they are linked to the session, not the token.

    Response format
    ---------------
    - ``XMLHttpRequest`` (AJAX) — returns a JSON payload containing the new
      token UUID, a freshly rendered QR data URI, all relevant dashboard URLs,
      and the new expiry timestamp.
    - Regular POST (no ``X-Requested-With: XMLHttpRequest`` header) — redirects
      to the updated ``qr_dashboard``.

    Parameters
    ----------
    request : HttpRequest
        The incoming POST request.
    token : UUID
        The current ``QRAttendanceToken.token`` value.

    Returns
    -------
    JsonResponse | HttpResponseRedirect
        JSON with new token data for AJAX callers, or a redirect for form submits.

    Raises
    ------
    Http404
        When no token with the given UUID exists.
    """
    from apps.dashboard.models import SystemSettings

    qr_token = get_object_or_404(QRAttendanceToken, token=token)
    seance = qr_token.seance
    course = seance.id_cours

    # Ownership check — return 403 JSON for AJAX callers, redirect for others.
    if course.professeur_id != request.user.pk:
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return JsonResponse({"error": "Accès non autorisé."}, status=403)
        messages.error(request, "Accès non autorisé.")
        return redirect("dashboard:instructor_dashboard")

    sys_settings = SystemSettings.get_settings()

    # Preserve GPS settings from the old token so location enforcement continues.
    old_verify_location = qr_token.verify_location
    old_lat = qr_token.latitude
    old_lng = qr_token.longitude

    # Deactivate all active tokens for this session before issuing the new one.
    QRAttendanceToken.objects.filter(seance=seance, is_active=True).update(is_active=False)

    new_token = QRAttendanceToken.objects.create(
        seance=seance,
        created_by=request.user,
        expires_at=timezone.now() + timedelta(seconds=sys_settings.qr_token_duration_seconds),
        verify_location=old_verify_location,
        latitude=old_lat,
        longitude=old_lng,
    )

    # AJAX path: return JSON so the JavaScript on the dashboard can update the
    # QR image and countdown timer without a page reload.
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        scan_url = request.build_absolute_uri(
            reverse("absences:qr_scan", kwargs={"token": str(new_token.token)})
        )
        qr_data_uri = _generate_qr_data_uri(scan_url)
        return JsonResponse({
            "token": str(new_token.token),
            "qr_data_uri": qr_data_uri,
            "scan_url": scan_url,
            "expires_at": new_token.expires_at.isoformat(),
            # Pre-built URLs so the client can update all links in the DOM at once.
            "refresh_url": reverse("absences:qr_refresh_token", kwargs={"token": str(new_token.token)}),
            "dashboard_url": reverse("absences:qr_dashboard", kwargs={"token": str(new_token.token)}),
            "finalize_url": reverse("absences:qr_finalize", kwargs={"token": str(new_token.token)}),
        })

    # Fallback for non-AJAX form submit: redirect to the updated dashboard.
    messages.success(request, "QR code rafraîchi avec un nouveau token.")
    return redirect("absences:qr_dashboard", token=new_token.token)


@login_required
@professor_required
@require_POST
def qr_finalize(request, token):
    """
    Close the QR attendance session and lock it permanently.

    Steps performed inside a single atomic transaction:

    1. Acquire a row-level lock on the ``Seance`` record.
    2. Collect the set of enrollment IDs that have a ``QRScanRecord``
       (i.e., students who scanned successfully).
    3. For every enrolled student **not** in that set, create an ``Absence``
       record with ``note_professeur = "Absent (QR non scanné)"``.
    4. Deactivate all remaining active tokens for the session.
    5. Mark the session as validated (permanently locked).

    Parameters
    ----------
    request : HttpRequest
        The incoming POST request.
    token : UUID
        The ``QRAttendanceToken.token`` value identifying the session.

    Returns
    -------
    HttpResponseRedirect
        Redirect to the instructor course detail page after finalization, or to
        the dashboard if the session was already validated.

    Raises
    ------
    Http404
        When no token with the given UUID exists.
    """
    qr_token = get_object_or_404(QRAttendanceToken, token=token)
    course = qr_token.seance.id_cours

    # Ownership check.
    if course.professeur is None or course.professeur.pk != request.user.pk:
        messages.error(request, "Accès non autorisé.")
        return redirect("dashboard:instructor_dashboard")

    with transaction.atomic():
        # Lock the session row to prevent a concurrent finalization.
        seance = Seance.objects.select_for_update().get(pk=qr_token.seance.pk)

        if seance.validated:
            messages.warning(request, "Cette séance est déjà validée.")
            return redirect("dashboard:instructor_course_detail", course.id_cours)

        # Load all active enrollments for the course and academic year.
        inscriptions = list(
            Inscription.objects.filter(
                id_cours=course,
                id_annee=seance.id_annee,
                status=Inscription.Status.EN_COURS,
            ).select_related("id_etudiant", "id_cours")
        )

        # Collect all enrollment PKs that have a successful scan record.
        scanned_ids = set(
            QRScanRecord.objects.filter(seance=seance).values_list("inscription_id", flat=True)
        )

        # Deactivate all tokens now — no more scanning allowed after finalization.
        QRAttendanceToken.objects.filter(seance=seance, is_active=True).update(is_active=False)

        # Create an absence record for each student who did not scan.
        absent_count = 0
        for ins in inscriptions:
            if ins.id_inscription not in scanned_ids:
                # Use the computed session duration; fall back to 2h if unavailable.
                duree = seance.duree_heures() or 2.0
                _absence, created = Absence.objects.get_or_create(
                    id_inscription=ins,
                    id_seance=seance,
                    defaults={
                        "type_absence": Absence.TypeAbsence.ABSENT,
                        "duree_absence": duree,
                        "statut": Absence.Statut.NON_JUSTIFIEE,
                        "encodee_par": request.user,
                        "note_professeur": "Absent (QR non scanné)",
                    },
                )
                if created:
                    absent_count += 1

        # Lock the session permanently.
        seance.validated = True
        seance.validated_by = request.user
        seance.date_validated = timezone.now()
        seance.save(update_fields=["validated", "validated_by", "date_validated"])

        log_action(
            request.user,
            f"QR finalisé — {course.code_cours} {seance.date_seance}: "
            f"{len(scanned_ids)} présent(s), {absent_count} absent(s)",
            request,
            niveau="INFO",
            objet_type="SEANCE",
            objet_id=seance.id_seance,
        )

    messages.success(
        request,
        f"Séance finalisée : {len(scanned_ids)} présent(s), {absent_count} absent(s).",
    )
    return redirect("dashboard:instructor_course_detail", course.id_cours)
