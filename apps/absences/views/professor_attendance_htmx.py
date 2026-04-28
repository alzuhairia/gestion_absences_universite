"""
Saisie des présences — endpoint HTMX (appel manuel).

mark_absence_htmx : mise à jour temps réel d'un seul étudiant sans rechargement.

RÈGLE MÉTIER CRITIQUE :
  Les absences encodées par le secrétariat (statut JUSTIFIEE / EN_ATTENTE) sont
  PROTÉGÉES : le professeur peut les voir mais pas les modifier.
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
    Endpoint HTMX — met à jour la présence d'un seul étudiant sans rechargement.
    Retourne le <tr> partiel mis à jour pour cet étudiant.
    """
    course = get_object_or_404(Cours, id_cours=course_id)
    if course.professeur != request.user:
        return HttpResponse("Accès non autorisé.", status=403)

    inscription_id = request.POST.get("inscription_id", "")
    status = request.POST.get("status", "")

    active_year = AnneeAcademique.objects.filter(active=True).first()
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

    try:
        fmt = "%H:%M"
        t_debut = datetime.datetime.strptime(heure_debut, fmt)
        t_fin = datetime.datetime.strptime(heure_fin, fmt)
    except (TypeError, ValueError):
        return HttpResponse("Format d'heure invalide.", status=400)

    if t_fin <= t_debut:
        return HttpResponse("L'heure de fin doit être après l'heure de début.", status=400)

    duree_seance = Decimal((t_fin - t_debut).seconds) / Decimal(3600)
    duree_seance = duree_seance.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    if not active_year:
        return HttpResponse("Aucune année académique active.", status=400)

    with transaction.atomic():
        try:
            seance = Seance.objects.select_for_update().get(date_seance=date_seance, id_cours=course)
            updated_fields = []
            if str(seance.heure_debut or "")[:5] != heure_debut:
                seance.heure_debut = heure_debut
                updated_fields.append("heure_debut")
            if str(seance.heure_fin or "")[:5] != heure_fin:
                seance.heure_fin = heure_fin
                updated_fields.append("heure_fin")
            if updated_fields:
                seance.save(update_fields=updated_fields)
        except Seance.DoesNotExist:
            seance = Seance.objects.create(
                date_seance=date_seance,
                heure_debut=heure_debut,
                heure_fin=heure_fin,
                id_cours=course,
                id_annee=active_year,
            )

        if seance.validated:
            return HttpResponse("Séance déjà validée.", status=403)

        existing_absence = Absence.objects.filter(
            id_inscription=inscription, id_seance=seance
        ).first()

        if status == "ABSENT":
            if existing_absence and existing_absence.statut in (
                Absence.Statut.JUSTIFIEE, Absence.Statut.EN_ATTENTE
            ):
                pass
            else:
                _ALLOWED_TYPES_HTMX = {Absence.TypeAbsence.ABSENT, Absence.TypeAbsence.PARTIEL}
                type_absence = request.POST.get(f"type_{inscription_id}", Absence.TypeAbsence.ABSENT)
                if type_absence not in _ALLOWED_TYPES_HTMX:
                    type_absence = Absence.TypeAbsence.ABSENT

                duree = duree_seance
                if type_absence == Absence.TypeAbsence.PARTIEL:
                    try:
                        duree = Decimal(
                            str(float(request.POST.get(f"duree_{inscription_id}", 0)))
                        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                        if duree <= 0 or duree > duree_seance:
                            raise ValueError
                    except (TypeError, ValueError):
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
            if existing_absence:
                if existing_absence.statut not in (Absence.Statut.JUSTIFIEE, Absence.Statut.EN_ATTENTE):
                    existing_absence.delete()

    absence = Absence.objects.select_related(
        "id_inscription__id_etudiant", "id_seance"
    ).filter(id_inscription=inscription, id_seance=seance).first()

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

    return render(request, "absences/_student_row.html", {
        "ins": inscription,
        "is_validated": False,
        "course": course,
        "seance_id": seance.id_seance,
    })
