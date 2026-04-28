"""
Encodage direct d'absences par le secrétariat.

Fonctionnalités :
  - create_justified_absence    : encodage direct d'une absence (justifiée ou non) pour un étudiant
  - student_absence_history_api : API JSON — historique d'absence récent d'un étudiant

TRANSACTION : toutes les absences d'une saisie sont créées atomiquement (tout ou rien).
"""
import logging
from decimal import ROUND_HALF_UP, Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import Count, Q
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods

from apps.academic_sessions.models import AnneeAcademique, Seance
from apps.accounts.models import User
from apps.audits.utils import log_action
from apps.dashboard.decorators import (
    api_error,
    api_login_required,
    api_ok,
    new_request_id,
    secretary_required,
)
from apps.enrollments.models import Inscription

from ..forms import SecretaryJustifiedAbsenceForm
from ..models import Absence, Justification
from ..utils_upload import (
    UploadValidationError,
    generate_safe_upload_filename,
    validate_uploaded_file,
)

logger = logging.getLogger(__name__)


@login_required
@secretary_required
@require_http_methods(["GET", "POST"])
def create_justified_absence(request):
    """
    Encodage direct d'une absence par le secrétariat.

    Cas d'usage :
    - Étudiant envoie un justificatif par email → absence directement JUSTIFIÉE
    - Secrétariat constate une absence sans justificatif → absence NON_JUSTIFIÉE
    - Plusieurs cours peuvent être sélectionnés pour la même date

    TRANSACTION : toutes les absences sont créées atomiquement (tout ou rien).
    """
    if request.method == "POST":
        form = SecretaryJustifiedAbsenceForm(request.POST, request.FILES)
        if form.is_valid():
            etudiant = form.cleaned_data["etudiant"]
            date_absence = form.cleaned_data["date_absence"]
            cours_list = form.cleaned_data["cours"]
            type_absence = form.cleaned_data["type_absence"]
            duree_absence = form.cleaned_data.get("duree_absence", 0)
            heure_debut_raw = form.cleaned_data.get("heure_debut")
            heure_fin_raw = form.cleaned_data.get("heure_fin")
            commentaire = form.cleaned_data.get("commentaire", "")
            document_file = form.cleaned_data.get("document")

            annee_active = AnneeAcademique.objects.filter(active=True).first()
            if not annee_active:
                messages.error(request, "Aucune année académique active.")
                return render(request, "absences/create_justified_absence.html",
                              {"form": form, "annee_active": None})

            document_bytes = document_name = None
            if document_file:
                try:
                    meta = validate_uploaded_file(document_file)
                    document_name = generate_safe_upload_filename(meta["extension"])
                    document_file.name = document_name
                except UploadValidationError as exc:
                    messages.error(request, " ".join(exc.messages))
                    return render(request, "absences/create_justified_absence.html",
                                  {"form": form, "annee_active": annee_active})
                document_bytes = document_file.read()

            absences_created = []
            with transaction.atomic():
                for cours in cours_list:
                    inscription = Inscription.objects.filter(
                        id_etudiant=etudiant,
                        id_cours=cours,
                        id_annee=annee_active,
                        status=Inscription.Status.EN_COURS,
                    ).first()

                    if not inscription:
                        messages.warning(
                            request,
                            f"L'étudiant {etudiant.get_full_name()} n'est pas inscrit au cours {cours.code_cours}.",
                        )
                        continue

                    from datetime import time as dt_time, datetime, timedelta
                    seance_heure_debut = heure_debut_raw if heure_debut_raw else dt_time(8, 0)
                    seance_heure_fin = heure_fin_raw if heure_fin_raw else dt_time(10, 0)

                    if seance_heure_fin <= seance_heure_debut:
                        date_ref = datetime(2000, 1, 1)
                        debut = datetime.combine(date_ref, seance_heure_debut)
                        fin = debut + timedelta(hours=2)
                        seance_heure_fin = min(fin.time(), dt_time(23, 59))
                        messages.warning(
                            request,
                            f"Heure de fin invalide pour {cours.code_cours} — ajustée automatiquement.",
                        )

                    try:
                        seance = Seance.objects.get(
                            date_seance=date_absence, id_cours=cours, id_annee=annee_active
                        )
                    except Seance.DoesNotExist:
                        seance = Seance.objects.create(
                            date_seance=date_absence,
                            heure_debut=seance_heure_debut,
                            heure_fin=seance_heure_fin,
                            id_cours=cours,
                            id_annee=annee_active,
                        )

                    from datetime import datetime, timedelta
                    if type_absence == Absence.TypeAbsence.ABSENT:
                        date_ref = datetime(2000, 1, 1)
                        raw = (datetime.combine(date_ref, seance_heure_fin) -
                               datetime.combine(date_ref, seance_heure_debut)).total_seconds() / 3600.0
                        duree = Decimal(str(raw)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                    elif type_absence == Absence.TypeAbsence.PARTIEL:
                        raw = duree_absence if duree_absence and duree_absence > 0 else 1.0
                        duree = Decimal(str(raw)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                    else:
                        raw = duree_absence if duree_absence and duree_absence > 0 else 2.0
                        duree = Decimal(str(raw)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

                    statut_absence = (
                        Absence.Statut.JUSTIFIEE if document_bytes
                        else Absence.Statut.NON_JUSTIFIEE
                    )

                    absence, created = Absence.objects.update_or_create(
                        id_inscription=inscription,
                        id_seance=seance,
                        defaults={
                            "type_absence": type_absence,
                            "duree_absence": duree,
                            "statut": statut_absence,
                            "encodee_par": request.user,
                        },
                    )

                    if document_bytes or commentaire:
                        document_to_save = None
                        if document_bytes:
                            document_to_save = ContentFile(document_bytes)
                            document_to_save.name = document_name or "justificatif.bin"

                        Justification.objects.update_or_create(
                            id_absence=absence,
                            defaults={
                                "document": document_to_save,
                                "commentaire": commentaire,
                                "commentaire_gestion": (
                                    f"Absence encodée directement par le secrétariat "
                                    f"le {timezone.now().strftime('%d/%m/%Y à %H:%M')}"
                                ),
                                "state": Justification.State.ACCEPTEE,
                                "validee_par": request.user,
                                "date_validation": timezone.now(),
                            },
                        )

                    absences_created.append({"cours": cours.code_cours, "absence": absence})

                    statut_label = "justifiée" if document_bytes else "non justifiée"
                    log_action(
                        request.user,
                        f"Secrétaire a encodé une absence {statut_label} pour "
                        f"{etudiant.get_full_name()} - {cours.code_cours} le {date_absence}",
                        request,
                        niveau="INFO",
                        objet_type="ABSENCE",
                        objet_id=absence.id_absence,
                    )

            if absences_created:
                cours_list_str = ", ".join(a["cours"] for a in absences_created)
                statut_msg = "justifiée(s)" if document_bytes else "non justifiée(s)"
                messages.success(
                    request,
                    f"Absence(s) {statut_msg} encodée(s) pour {etudiant.get_full_name()} "
                    f"le {date_absence} — cours : {cours_list_str}.",
                )
                return redirect("absences:validation_list")
            else:
                messages.error(
                    request,
                    "Aucune absence créée. Vérifiez que l'étudiant est inscrit aux cours sélectionnés.",
                )
    else:
        form = SecretaryJustifiedAbsenceForm()

    annee_active = AnneeAcademique.objects.filter(active=True).first()
    return render(request, "absences/create_justified_absence.html", {
        "form": form,
        "annee_active": annee_active,
    })


@api_login_required(roles=[User.Role.SECRETAIRE])
@require_GET
def student_absence_history_api(request):
    """
    API JSON — historique récent des absences d'un étudiant.
    Query params: student_id (int, requis)
    """
    student_id = request.GET.get("student_id")
    if not student_id:
        return api_error("student_id requis", status=400, code="bad_request")

    try:
        active_year = AnneeAcademique.objects.filter(active=True).first()
        absences_qs = Absence.objects.filter(
            id_inscription__id_etudiant_id=student_id
        ).select_related("id_seance", "id_seance__id_cours")
        if active_year:
            absences_qs = absences_qs.filter(id_inscription__id_annee=active_year)

        stats = absences_qs.aggregate(
            total=Count("id_absence"),
            justified=Count("id_absence", filter=Q(statut=Absence.Statut.JUSTIFIEE)),
            pending=Count("id_absence", filter=Q(statut=Absence.Statut.EN_ATTENTE)),
            unjustified=Count("id_absence", filter=Q(statut=Absence.Statut.NON_JUSTIFIEE)),
        )

        recent_absences = absences_qs.order_by(
            "-id_seance__date_seance", "-id_seance__heure_debut", "-id_absence"
        )[:10]

        items = [
            {
                "id": ab.id_absence,
                "date": ab.id_seance.date_seance.isoformat(),
                "date_display": ab.id_seance.date_seance.strftime("%d/%m/%Y"),
                "time_start": ab.id_seance.heure_debut.strftime("%H:%M") if ab.id_seance.heure_debut else "",
                "time_end": ab.id_seance.heure_fin.strftime("%H:%M") if ab.id_seance.heure_fin else "",
                "course_code": ab.id_seance.id_cours.code_cours,
                "course_name": ab.id_seance.id_cours.nom_cours,
                "type": ab.type_absence,
                "type_display": Absence.TypeAbsence(ab.type_absence).label,
                "status": ab.statut,
                "status_display": Absence.Statut(ab.statut).label,
                "duration": float(ab.duree_absence),
            }
            for ab in recent_absences
        ]

        return api_ok({
            "items": items,
            "stats": {
                "total": stats.get("total", 0),
                "justified": stats.get("justified", 0),
                "pending": stats.get("pending", 0),
                "unjustified": stats.get("unjustified", 0),
            },
        })
    except Exception:
        request_id = new_request_id()
        logger.exception("Erreur API student_absence_history_api [request_id=%s]", request_id)
        return api_error("Une erreur interne est survenue.", status=500,
                         code="server_error", request_id=request_id)
