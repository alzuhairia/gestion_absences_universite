"""
Manual attendance marking — full-page form view.

``mark_absence``
    Renders and processes the full class attendance sheet for a given course.
    The professor selects a date and session times, then marks each enrolled
    student as PRESENT, ABSENT, or PARTIAL (late arrival / early departure).

Critical business rule
----------------------
Absences that have been encoded by the secretariat (status ``JUSTIFIEE`` or
``EN_ATTENTE``) are **protected**: the professor can see them in the list but
cannot overwrite or delete them.  Any ``status_<id>`` submission targeting a
protected absence is silently skipped inside the transaction.

Workflow
--------
1. Verify course ownership (double security beyond the decorator).
2. Load all active enrollments for the course and the current academic year.
3. On POST:
   a. Validate that no ``status_*`` key targets an enrollment outside this
      course (prevents parameter-tampering; raises ``PermissionDenied``).
   b. Validate and parse session times; compute session duration.
   c. Inside an atomic transaction, ``get_or_create`` the ``Seance`` record
      and ``update_or_create`` one ``Absence`` per absent student.
   d. Optionally validate (lock) the session if ``form_action == "validate"``.
   e. Trigger a notification email for each *new* absence record created.
4. On GET: load existing session data for the selected date so the form
   renders in "edit mode" when a session already exists.

Part of the UniAbsences attendance system.
"""
import datetime
import logging
from decimal import ROUND_HALF_UP, Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from ..models import Absence
from ..services import calculer_absence_stats
from apps.academic_sessions.models import AnneeAcademique, Seance
from apps.academics.models import Cours
from apps.accounts.models import User
from apps.audits.utils import log_action
from apps.dashboard.decorators import professor_required
from apps.enrollments.models import Inscription
from apps.notifications.email import build_absence_recorded_email, send_with_dedup

logger = logging.getLogger(__name__)


@login_required
@professor_required
@require_http_methods(["GET", "POST"])
def mark_absence(request, course_id):
    """
    Render and process the full-page manual attendance form for a course.

    GET
        Load the attendance sheet for the requested date (``?date=YYYY-MM-DD``).
        If a session already exists for that date the form pre-fills with the
        recorded times and any existing absence data (edit mode).

    POST
        Process the submitted attendance sheet atomically:
        - Validate session date / times.
        - Create or update the ``Seance`` record.
        - For each ``status_<inscription_id>`` field:
            * ``ABSENT`` — ``update_or_create`` an ``Absence`` (skips protected ones).
            * ``PRESENT`` — delete any existing unprotected ``Absence``.
        - Optionally lock the session (``form_action=validate``).
        - Send a notification email for each newly created absence.

    Security
    --------
    - Course ownership is verified against ``request.user`` before processing.
    - Enrollment IDs in POST data are validated against the course's own
      enrollment queryset; any unknown ID raises ``PermissionDenied``.

    Parameters
    ----------
    request : HttpRequest
        The incoming HTTP request.
    course_id : int
        Primary key of the ``Cours`` record whose attendance is being recorded.

    Returns
    -------
    HttpResponse
        Rendered attendance form on GET or redirect on successful POST.

    Raises
    ------
    Http404
        When no ``Cours`` with ``course_id`` exists.
    PermissionDenied
        When a POST submission contains enrollment IDs outside this course.
    """
    course = get_object_or_404(Cours, id_cours=course_id)

    # Secondary ownership check — the decorator only verifies the role, not
    # which course belongs to which professor.
    if course.professeur != request.user:
        messages.error(request, "Unauthorized access to this course.")
        return redirect("dashboard:instructor_dashboard")

    active_year = AnneeAcademique.objects.filter(active=True).first()

    # Build the enrollment queryset filtered to the active academic year.
    inscriptions_qs = Inscription.objects.filter(
        id_cours=course, status=Inscription.Status.EN_COURS
    ).select_related("id_etudiant")
    if active_year:
        inscriptions_qs = inscriptions_qs.filter(id_annee=active_year)

    # Index by string PK for O(1) lookup when iterating POST fields.
    inscriptions_by_id = {str(ins.id_inscription): ins for ins in inscriptions_qs}

    if request.method == "POST":
        # Pre-check: if the session is already validated for this date, bail early
        # before acquiring any locks — saves a round trip in the common case.
        check_date = request.POST.get("date_seance", "").strip()
        if check_date:
            validated_seance = Seance.objects.filter(
                id_cours=course, date_seance=check_date, validated=True
            ).first()
            if validated_seance:
                messages.error(request, "This session has already been validated.")
                return redirect("absences:mark_absence", course_id=course_id)

        # Security: collect any enrollment IDs from POST that do not belong to
        # this course.  If any exist, log and raise PermissionDenied immediately.
        invalid_ids = [
            key.split("_", 1)[1]
            for key in request.POST.keys()
            if key.startswith("status_") and key.split("_", 1)[1] not in inscriptions_by_id
        ]
        if invalid_ids:
            log_action(
                request.user,
                f"Attempted access to unauthorized enrollments: {', '.join(invalid_ids)}",
                request,
                niveau="WARNING",
                objet_type="INSCRIPTION",
                objet_id=None,
            )
            raise PermissionDenied("Unauthorized access to one or more enrollments.")

        date_seance = request.POST.get("date_seance", "").strip()
        heure_debut = request.POST.get("heure_debut", "").strip()
        heure_fin = request.POST.get("heure_fin", "").strip()

        if not date_seance or not heure_debut or not heure_fin:
            messages.error(request, "Invalid session date and times.")
            return redirect("absences:mark_absence", course_id=course_id)

        # Parse times in HH:MM format; reject anything else immediately.
        try:
            fmt = "%H:%M"
            t_debut = datetime.datetime.strptime(heure_debut, fmt)
            t_fin = datetime.datetime.strptime(heure_fin, fmt)
        except (TypeError, ValueError):
            messages.error(request, "Format d'heure invalide (HH:MM attendu).")
            return redirect("absences:mark_absence", course_id=course_id)

        if t_fin <= t_debut:
            messages.error(request, "L'heure de fin doit être postérieure à l'heure de début.")
            return redirect("absences:mark_absence", course_id=course_id)

        # Compute session duration in decimal hours (used as default absence duration).
        duree_seance = Decimal((t_fin - t_debut).seconds) / Decimal(3600)
        duree_seance = duree_seance.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        annee = AnneeAcademique.objects.filter(active=True).first()
        if not annee:
            messages.error(request, "Aucune année académique active.")
            return redirect("absences:mark_absence", course_id=course_id)

        with transaction.atomic():
            seance_created = False
            try:
                # Attempt to retrieve an existing session for this date and course.
                # select_for_update() prevents a concurrent race on the same session.
                seance = Seance.objects.select_for_update().get(date_seance=date_seance, id_cours=course)
                if seance.validated:
                    # Another user may have validated it between our earlier check
                    # and acquiring the lock — abort gracefully.
                    messages.error(request, "Cette séance a été validée entre-temps.")
                    return redirect("absences:mark_absence", course_id=course_id)

                # Update session times only if they actually changed.
                updated_fields = []
                if seance.heure_debut != heure_debut:
                    seance.heure_debut = heure_debut
                    updated_fields.append("heure_debut")
                if seance.heure_fin != heure_fin:
                    seance.heure_fin = heure_fin
                    updated_fields.append("heure_fin")
                if updated_fields:
                    seance.save(update_fields=updated_fields)
                messages.info(request, "Séance existante récupérée — absences mises à jour.")
            except Seance.DoesNotExist:
                # No session yet for this date — create one.
                seance = Seance.objects.create(
                    date_seance=date_seance,
                    heure_debut=heure_debut,
                    heure_fin=heure_fin,
                    id_cours=course,
                    id_annee=annee,
                )
                seance_created = True

            # Iterate over every status_<id> field in the POST body.
            for key, value in request.POST.items():
                if not key.startswith("status_"):
                    continue

                inscription_id = key.split("_", 1)[1]
                status = value
                inscription = inscriptions_by_id.get(inscription_id)
                if not inscription:
                    # Should not happen (already validated above), but guard anyway.
                    continue

                # Look up any previously recorded absence for this student + session.
                existing_absence = Absence.objects.filter(
                    id_inscription=inscription, id_seance=seance
                ).first()
                is_prof = request.user.role == User.Role.PROFESSEUR

                if status == "ABSENT":
                    # Only ABSENT and PARTIEL are valid type values for professor input.
                    _ALLOWED_TYPES = {Absence.TypeAbsence.ABSENT, Absence.TypeAbsence.PARTIEL}
                    type_absence = request.POST.get(f"type_{inscription_id}", Absence.TypeAbsence.ABSENT)
                    if type_absence not in _ALLOWED_TYPES:
                        type_absence = Absence.TypeAbsence.ABSENT

                    # Default duration is the full session; override for PARTIEL.
                    duree = duree_seance
                    if type_absence == Absence.TypeAbsence.PARTIEL:
                        try:
                            duree = Decimal(
                                str(float(request.POST.get(f"duree_{inscription_id}", 0)))
                            ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                            if duree <= 0 or duree > duree_seance:
                                raise ValueError("invalid range")
                        except (TypeError, ValueError):
                            # Fall back to full session duration and warn the professor.
                            duree = duree_seance
                            messages.warning(
                                request,
                                f"Durée invalide pour {inscription.id_etudiant.get_full_name()} "
                                f"— absence complète ({duree_seance}h) appliquée par défaut.",
                            )

                    # CRITICAL: do not overwrite absences encoded by the secretariat.
                    if existing_absence and existing_absence.statut in (
                        Absence.Statut.JUSTIFIEE, Absence.Statut.EN_ATTENTE
                    ):
                        continue  # Skip — secretary-encoded absence is protected.

                    note = request.POST.get(f"note_{inscription_id}", "").strip()[:500]

                    try:
                        absence, created = Absence.objects.update_or_create(
                            id_inscription=inscription,
                            id_seance=seance,
                            defaults={
                                "type_absence": type_absence,
                                "duree_absence": duree,
                                "statut": Absence.Statut.NON_JUSTIFIEE,
                                "encodee_par": request.user,
                                "note_professeur": note,
                            },
                        )
                    except IntegrityError:
                        # Rare but possible if two requests race on the same record.
                        messages.warning(
                            request,
                            f"Absence déjà enregistrée pour {inscription.id_etudiant.get_full_name()} (doublon ignoré).",
                        )
                        continue

                    # Log each individual absence record created by the professor.
                    if is_prof:
                        log_action(
                            request.user,
                            f"Professeur a enregistré une absence pour "
                            f"{inscription.id_etudiant.get_full_name()} - {course.code_cours} le {date_seance}",
                            request,
                            niveau="INFO",
                            objet_type="ABSENCE",
                            objet_id=absence.id_absence,
                        )

                    # Send a notification email only for brand-new absence records.
                    # Deduplication via event_key prevents duplicate emails when the
                    # professor saves the same form multiple times.
                    if created:
                        stats = calculer_absence_stats(inscription)
                        student = inscription.id_etudiant
                        subj, body, html_body = build_absence_recorded_email(
                            student, course.nom_cours, date_seance, stats["taux"]
                        )
                        event_key = f"{inscription.id_inscription}-{seance.id_seance}"
                        send_with_dedup(
                            student, subj, body, html_body,
                            event_type="absence_recorded",
                            event_key=event_key,
                        )
                else:
                    # Student is marked PRESENT — remove any existing unprotected absence.
                    if existing_absence:
                        if existing_absence.statut in (Absence.Statut.JUSTIFIEE, Absence.Statut.EN_ATTENTE):
                            continue  # Protected — do not delete secretary-encoded absence.
                        existing_absence.delete()

            # Log session creation and attendance submission at the session level.
            if request.user.role == User.Role.PROFESSEUR:
                if seance_created:
                    log_action(
                        request.user,
                        f"Professeur a créé une séance pour {course.code_cours} le {date_seance}",
                        request,
                        niveau="INFO",
                        objet_type="SEANCE",
                        objet_id=seance.id_seance if hasattr(seance, "id_seance") else None,
                    )
                log_action(
                    request.user,
                    f"Professeur a enregistré la présence pour {course.code_cours} le {date_seance}",
                    request,
                    niveau="INFO",
                    objet_type="SEANCE",
                    objet_id=seance.id_seance if hasattr(seance, "id_seance") else None,
                )

            # "validate" action locks the session permanently; "draft" keeps it editable.
            post_action = request.POST.get("form_action", "draft")
            if post_action == "validate":
                seance.validated = True
                seance.validated_by = request.user
                seance.date_validated = timezone.now()
                seance.save(update_fields=["validated", "validated_by", "date_validated"])
                log_action(
                    request.user,
                    f"Professeur a validé la séance du {date_seance} pour {course.code_cours}",
                    request,
                    niveau="INFO",
                    objet_type="SEANCE",
                    objet_id=seance.id_seance,
                )
                messages.success(
                    request,
                    f"L'appel du {date_seance} a été validé et verrouillé. La séance ne peut plus être modifiée.",
                )
            else:
                messages.success(
                    request,
                    f"Brouillon enregistré pour la séance du {date_seance}. Vous pourrez le modifier ultérieurement.",
                )

            # Redirect back to the same date so the professor can review the result.
            return redirect(f"{reverse('absences:mark_absence', args=[course_id])}?date={date_seance}")

    # --- GET ---
    students = inscriptions_qs.order_by("id_etudiant__nom")

    # Resolve the requested date from the query string; fall back to today.
    today = request.GET.get("date", "")
    try:
        datetime.date.fromisoformat(today)
    except (ValueError, TypeError):
        today = timezone.now().strftime("%Y-%m-%d")
    default_start = "08:30"
    default_end = "10:30"

    # Attempt to load an existing session for the selected date.
    try:
        existing_seance = Seance.objects.get(id_cours=course, date_seance=today)
    except Seance.DoesNotExist:
        existing_seance = None

    existing_absences = {}
    is_edit_mode = False
    is_validated = False

    if existing_seance:
        is_edit_mode = True
        is_validated = existing_seance.validated

        # Pre-fill start/end time inputs from the stored session.
        if existing_seance.heure_debut:
            default_start = existing_seance.heure_debut.strftime("%H:%M")
        if existing_seance.heure_fin:
            default_end = existing_seance.heure_fin.strftime("%H:%M")

        # Build a dict keyed by enrollment PK for O(1) template lookup.
        abs_list = Absence.objects.filter(id_seance=existing_seance).select_related("encodee_par")
        for ab in abs_list:
            existing_absences[ab.id_inscription.pk] = {
                "type": ab.type_absence,
                "duree": ab.duree_absence,
                "statut": ab.statut,
                "note_professeur": ab.note_professeur,
                "encodee_par": ab.encodee_par,
            }

    # Attach absence data directly to each enrollment for simpler template logic.
    for ins in students:
        setattr(ins, "absence_data", existing_absences.get(ins.id_inscription))

    # Summary counts for the recap banner at the top of the form.
    recap_absent_count = len(existing_absences)
    recap_present_count = len(students) - recap_absent_count

    return render(request, "absences/mark_absence.html", {
        "course": course,
        "students": students,
        "today": today,
        "default_start": default_start,
        "default_end": default_end,
        "is_edit_mode": is_edit_mode,
        "is_validated": is_validated,
        "existing_seance": existing_seance,
        "recap_present_count": recap_present_count,
        "recap_absent_count": recap_absent_count,
    })
