"""
Manual attendance marking — HTMX partial endpoint.

``mark_absence_htmx``
    Processes a single student's attendance update in real time and returns
    only the refreshed ``<tr>`` row HTML fragment, avoiding a full page reload.
    Designed to be triggered by HTMX ``hx-post`` attributes in the attendance
    form template.

Critical business rule
----------------------
Absences encoded by the secretariat (status ``JUSTIFIEE`` or ``EN_ATTENTE``)
are **protected**: the professor can see them but cannot modify or delete them.
Any request targeting a protected absence is silently ignored and the original
row is re-rendered unchanged.

Session lifecycle
-----------------
If no ``Seance`` record exists for the submitted date and course, one is
created automatically so the professor does not have to save session times
separately before marking individual students.  If a session already exists,
its times are updated only when they have actually changed, to avoid spurious
``UPDATE`` statements.

Part of the UniAbsences attendance system.
"""
import datetime
import logging
from decimal import ROUND_HALF_UP, Decimal

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from django.db import transaction
from django.views.decorators.http import require_POST

from ..models import Absence
from apps.academic_sessions.models import AnneeAcademique, Seance
from apps.academics.models import Cours
from apps.dashboard.decorators import professor_required
from apps.enrollments.models import Inscription

logger = logging.getLogger(__name__)


@login_required
@professor_required
@require_POST
def mark_absence_htmx(request, course_id):
    """
    HTMX endpoint — update a single student's attendance without a full reload.

    Accepts a POST submission containing the enrollment ID, the desired status
    (``ABSENT`` or ``PRESENT``), and the session date / times.  Returns the
    updated ``<tr>`` HTML partial for the targeted student row.

    Absence type / duration logic
    ------------------------------
    - ``ABSENT`` — full session duration is recorded.
    - ``PARTIEL`` — a custom duration (``duree_<inscription_id>``) is used;
      falls back to the full session duration if the value is invalid.
    - Protected absences (``JUSTIFIEE`` / ``EN_ATTENTE``) are left untouched.

    Parameters
    ----------
    request : HttpRequest
        The incoming POST request (triggered by HTMX).
    course_id : int
        Primary key of the ``Cours`` whose attendance is being updated.

    Returns
    -------
    HttpResponse
        - ``403`` if the professor does not own this course or the session is
          already validated.
        - ``400`` if required fields are missing or times are malformed.
        - ``404`` if the enrollment does not exist in this course.
        - The rendered ``absences/_student_row.html`` partial on success.
    """
    course = get_object_or_404(Cours, id_cours=course_id)

    # Ownership check — the decorator verifies the role, not the course.
    if course.professeur != request.user:
        return HttpResponse("Accès non autorisé.", status=403)

    inscription_id = request.POST.get("inscription_id", "")
    status = request.POST.get("status", "")

    active_year = AnneeAcademique.objects.filter(active=True).first()

    # Fetch the enrollment, scoped to this course and the active academic year.
    ins_qs = Inscription.objects.filter(
        id_inscription=inscription_id,
        id_cours=course,
        status=Inscription.Status.EN_COURS,
    ).select_related("id_etudiant", "id_cours")
    if active_year:
        ins_qs = ins_qs.filter(id_annee=active_year)
    inscription = ins_qs.first()

    if not inscription:
        return HttpResponse("Inscription introuvable.", status=404)

    date_seance = request.POST.get("date_seance", "").strip()
    heure_debut = request.POST.get("heure_debut", "").strip()
    heure_fin = request.POST.get("heure_fin", "").strip()

    if not date_seance or not heure_debut or not heure_fin:
        return HttpResponse("Date et horaires requis.", status=400)

    # Parse session times in HH:MM format.
    try:
        fmt = "%H:%M"
        t_debut = datetime.datetime.strptime(heure_debut, fmt)
        t_fin = datetime.datetime.strptime(heure_fin, fmt)
    except (TypeError, ValueError):
        return HttpResponse("Format d'heure invalide.", status=400)

    if t_fin <= t_debut:
        return HttpResponse("L'heure de fin doit être après l'heure de début.", status=400)

    # Compute session duration in decimal hours for absence duration defaults.
    duree_seance = Decimal((t_fin - t_debut).seconds) / Decimal(3600)
    duree_seance = duree_seance.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    if not active_year:
        return HttpResponse("Aucune année académique active.", status=400)

    with transaction.atomic():
        try:
            # Re-use an existing session record and update its times if needed.
            seance = Seance.objects.select_for_update().get(date_seance=date_seance, id_cours=course)
            updated_fields = []
            # Compare only the HH:MM portion to avoid spurious updates from seconds.
            if str(seance.heure_debut or "")[:5] != heure_debut:
                seance.heure_debut = heure_debut
                updated_fields.append("heure_debut")
            if str(seance.heure_fin or "")[:5] != heure_fin:
                seance.heure_fin = heure_fin
                updated_fields.append("heure_fin")
            if updated_fields:
                seance.save(update_fields=updated_fields)
        except Seance.DoesNotExist:
            # First HTMX update for this date — create the session automatically.
            seance = Seance.objects.create(
                date_seance=date_seance,
                heure_debut=heure_debut,
                heure_fin=heure_fin,
                id_cours=course,
                id_annee=active_year,
            )

        # Reject updates to locked sessions.
        if seance.validated:
            return HttpResponse("Séance déjà validée.", status=403)

        # Retrieve any existing absence for this student and session.
        existing_absence = Absence.objects.filter(
            id_inscription=inscription, id_seance=seance
        ).first()

        if status == "ABSENT":
            if existing_absence and existing_absence.statut in (
                Absence.Statut.JUSTIFIEE, Absence.Statut.EN_ATTENTE
            ):
                # Protected absence — silently skip; re-render the row unchanged.
                pass
            else:
                # Only ABSENT and PARTIEL are valid professor-submitted types.
                _ALLOWED_TYPES_HTMX = {Absence.TypeAbsence.ABSENT, Absence.TypeAbsence.PARTIEL}
                type_absence = request.POST.get(f"type_{inscription_id}", Absence.TypeAbsence.ABSENT)
                if type_absence not in _ALLOWED_TYPES_HTMX:
                    type_absence = Absence.TypeAbsence.ABSENT

                # Default to full session duration; apply custom duration for PARTIEL.
                duree = duree_seance
                if type_absence == Absence.TypeAbsence.PARTIEL:
                    try:
                        duree = Decimal(
                            str(float(request.POST.get(f"duree_{inscription_id}", 0)))
                        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                        if duree <= 0 or duree > duree_seance:
                            raise ValueError
                    except (TypeError, ValueError):
                        # Invalid custom duration — fall back silently.
                        duree = duree_seance

                note = request.POST.get(f"note_{inscription_id}", "").strip()[:500]

                Absence.objects.update_or_create(
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

        elif status == "PRESENT":
            # Remove the absence record; skip if it is secretary-protected.
            if existing_absence:
                if existing_absence.statut not in (Absence.Statut.JUSTIFIEE, Absence.Statut.EN_ATTENTE):
                    existing_absence.delete()

    # Re-fetch the final absence state (after all changes) for the partial render.
    absence = Absence.objects.select_related(
        "id_inscription__id_etudiant", "id_seance"
    ).filter(id_inscription=inscription, id_seance=seance).first()

    # Attach absence data to the enrollment object so the template can read it
    # without an extra query — mirrors the structure used in the full-page view.
    if absence:
        setattr(inscription, "absence_data", {
            "type": absence.type_absence,
            "duree": absence.duree_absence,
            "statut": absence.statut,
            "note_professeur": absence.note_professeur,
            "encodee_par": absence.encodee_par,
        })
    else:
        setattr(inscription, "absence_data", None)

    # Return only the updated student row HTML fragment (HTMX replaces it in-place).
    return render(request, "absences/_student_row.html", {
        "ins": inscription,
        "is_validated": False,
        "course": course,
        "seance_id": seance.id_seance,
    })
