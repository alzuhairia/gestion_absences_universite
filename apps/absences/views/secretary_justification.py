"""
Validation des justificatifs — vue secrétariat.

Fonctionnalités :
  - review_justification   : consulter une absence + son justificatif (lecture/commentaire)
  - validation_list        : liste des absences filtrées par statut (NON_JUSTIFIEE / EN_ATTENTE / JUSTIFIEE)
  - process_justification  : approuver ou rejeter un justificatif soumis par un étudiant
  - justified_absences_list: liste des absences justifiées encodées par le secrétariat

SÉCURITÉ : @secretary_required sur toutes les vues.
TRANSACTION : select_for_update() sur justification + absence pour éviter le double-traitement.
"""
import logging
from pathlib import Path

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Prefetch
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from apps.utils import safe_get_page
from apps.academic_sessions.models import AnneeAcademique
from apps.accounts.models import User
from apps.audits.utils import log_action
from apps.dashboard.decorators import secretary_required
from apps.notifications.email import (
    build_justification_decision_email,
    build_justification_decision_professor_email,
    send_notification_email,
)
from apps.notifications.models import Notification

from ..models import Absence, Justification

logger = logging.getLogger(__name__)


def _send_justification_decision_emails(absence, approved, motif=""):
    """Envoie les emails de décision à l'étudiant et au professeur. Ne lève jamais d'exception."""
    try:
        student = absence.id_inscription.id_etudiant
        course_code = absence.id_seance.id_cours.code_cours
        date_str = str(absence.id_seance.date_seance)
        professor = absence.id_seance.id_cours.professeur

        subj, body, html_body = build_justification_decision_email(
            student, course_code, date_str, approved, motif
        )
        send_notification_email(student, subj, body, html_body)

        if professor:
            subj, body, html_body = build_justification_decision_professor_email(
                professor, student, course_code, date_str, approved
            )
            send_notification_email(professor, subj, body, html_body)
    except Exception:
        logger.exception("Failed to send justification decision emails for absence %s", getattr(absence, "pk", "?"))


@login_required
@secretary_required
@require_http_methods(["GET", "POST"])
def review_justification(request, absence_id):
    """Consulte une absence + son justificatif. Permet d'ajouter un commentaire de gestion."""
    absence = get_object_or_404(
        Absence.objects.select_related(
            "id_inscription__id_etudiant",
            "id_seance__id_cours",
        ),
        id_absence=absence_id,
    )
    justification = Justification.objects.filter(id_absence=absence).first()

    if request.method == "POST" and justification:
        if justification.state != Justification.State.EN_ATTENTE:
            messages.warning(request, "Le commentaire ne peut plus être modifié après validation.")
            return redirect("absences:review_justification", absence_id=absence_id)
        new_comment = request.POST.get("commentaire_gestion")
        justification.commentaire_gestion = new_comment
        justification.save()
        messages.success(request, "Commentaire mis à jour.")
        return redirect("absences:review_justification", absence_id=absence_id)

    document_url = document_name = None
    if justification and justification.document:
        document_url = reverse("absences:download_justification", args=[justification.id_justification])
        suffix = Path(justification.document.name).suffix
        document_name = (
            f"justificatif_{absence.id_absence}{suffix}" if suffix
            else f"justificatif_{absence.id_absence}"
        )

    return render(request, "absences/review_justification.html", {
        "absence": absence,
        "justification": justification,
        "document_url": document_url,
        "document_name": document_name,
        "is_secretary": request.user.role == User.Role.SECRETAIRE,
    })


@login_required
@secretary_required
@require_GET
def validation_list(request):
    """
    Liste des absences pour le secrétariat, filtrée par statut.
    Trois catégories : NON_JUSTIFIEE, EN_ATTENTE (justificatif soumis), JUSTIFIEE.
    """
    _VALID_ABSENCE_STATUSES = set(Absence.Statut.values)
    status_filter = request.GET.get("status", Absence.Statut.NON_JUSTIFIEE)
    if status_filter not in _VALID_ABSENCE_STATUSES:
        status_filter = Absence.Statut.NON_JUSTIFIEE

    active_year = AnneeAcademique.objects.filter(active=True).first()

    absences = Absence.objects.filter(statut=status_filter).select_related(
        "id_inscription",
        "id_inscription__id_etudiant",
        "id_seance",
        "id_seance__id_cours",
        "encodee_par",
    )
    if active_year:
        absences = absences.filter(id_inscription__id_annee=active_year)

    absences = absences.prefetch_related(
        Prefetch(
            "justification",
            queryset=Justification.objects.select_related("validee_par"),
        )
    ).order_by("-id_seance__date_seance", "-id_absence")

    base_qs = Absence.objects.all()
    if active_year:
        base_qs = base_qs.filter(id_inscription__id_annee=active_year)
    status_counts = {
        Absence.Statut.NON_JUSTIFIEE: base_qs.filter(statut=Absence.Statut.NON_JUSTIFIEE).count(),
        Absence.Statut.EN_ATTENTE: base_qs.filter(statut=Absence.Statut.EN_ATTENTE).count(),
        Absence.Statut.JUSTIFIEE: base_qs.filter(statut=Absence.Statut.JUSTIFIEE).count(),
    }

    paginator = Paginator(absences, 20)
    page_obj = safe_get_page(paginator, request.GET.get("page"))

    return render(request, "absences/validation_list.html", {
        "page_obj": page_obj,
        "current_status": status_filter,
        "status_counts": status_counts,
    })


@login_required
@secretary_required
@require_POST
def process_justification(request, pk):
    """
    Approuve ou refuse un justificatif soumis par un étudiant.

    SÉCURITÉ :
    - select_for_update() sur justification + absence : évite le double-traitement concurrent
    - Emails envoyés APRÈS la transaction pour ne pas bloquer sur un échec SMTP
    """
    action = request.POST.get("action")
    comment = request.POST.get("comment", "")[:2000]

    if action not in ("approve", "reject"):
        messages.error(request, "Action invalide.")
        return redirect("absences:validation_list")

    if action == "reject" and not comment:
        messages.error(request, "Un motif de refus est obligatoire.")
        return redirect("absences:validation_list")

    approved = action == "approve"

    with transaction.atomic():
        try:
            justification = Justification.objects.select_for_update().get(pk=pk)
        except Justification.DoesNotExist:
            messages.error(request, "Justification introuvable.")
            return redirect("absences:validation_list")

        if justification.state != Justification.State.EN_ATTENTE:
            messages.warning(request, "Ce justificatif a déjà été traité.")
            return redirect("absences:validation_list")

        absence = (
            Absence.objects
            .select_related("id_seance__id_cours", "id_inscription__id_etudiant")
            .select_for_update()
            .get(pk=justification.id_absence.pk)
        )

        justification.state = Justification.State.ACCEPTEE if approved else Justification.State.REFUSEE
        justification.commentaire_gestion = comment
        justification.validee_par = request.user
        justification.date_validation = timezone.now()
        justification.save()

        absence.statut = Absence.Statut.JUSTIFIEE if approved else Absence.Statut.NON_JUSTIFIEE
        absence.save(update_fields=["statut"])

        decision = "ACCEPTÉE" if approved else "REFUSÉE"
        msg_text = f"Votre justification pour l'absence du {absence.id_seance.date_seance} a été {decision}."
        if not approved and comment:
            msg_text += f" Motif : {comment}"
        Notification.objects.create(
            id_utilisateur=absence.id_inscription.id_etudiant,
            message=msg_text,
            type="INFO",
            lue=False,
        )

        action_label = "APPROUVÉ" if approved else "REFUSÉ"
        log_action(
            request.user,
            f"Secrétaire a {action_label} la justification {justification.pk} "
            f"pour l'absence {absence.pk} - {absence.id_seance.id_cours.code_cours}. Motif: {comment}",
            request,
            niveau="INFO" if approved else "WARNING",
            objet_type="JUSTIFICATION",
            objet_id=justification.id_justification,
        )

    _send_justification_decision_emails(absence, approved=approved, motif=comment)

    if approved:
        messages.success(
            request,
            f"Le justificatif a été accepté. L'absence de "
            f"{absence.id_inscription.id_etudiant.get_full_name()} est maintenant justifiée.",
        )
    else:
        messages.warning(
            request,
            "Le justificatif a été refusé. L'étudiant a été notifié avec le motif indiqué.",
        )

    return redirect("absences:validation_list")


@login_required
@secretary_required
@require_GET
def justified_absences_list(request):
    """Liste des absences justifiées encodées par le secrétariat, avec filtres et pagination."""
    try:
        active_year = AnneeAcademique.objects.filter(active=True).first()

        absences = Absence.objects.filter(statut=Absence.Statut.JUSTIFIEE)
        if active_year:
            absences = absences.filter(id_inscription__id_annee=active_year)
        absences = (
            absences.select_related(
                "id_inscription__id_etudiant",
                "id_seance__id_cours",
                "id_seance__id_cours__id_departement",
                "id_seance__id_cours__id_departement__id_faculte",
                "encodee_par",
            )
            .select_related("justification")
            .order_by("-id_seance__date_seance", "-id_absence")
        )

        student_filter = request.GET.get("student", "")[:255]
        if student_filter:
            absences = absences.filter(
                id_inscription__id_etudiant__email__icontains=student_filter
            )

        date_filter = request.GET.get("date", "")[:10]
        if date_filter:
            try:
                from datetime import date as date_type
                date_type.fromisoformat(date_filter)
                absences = absences.filter(id_seance__date_seance=date_filter)
            except ValueError:
                pass

        course_filter = request.GET.get("course", "")[:255]
        if course_filter:
            absences = absences.filter(id_seance__id_cours__code_cours__icontains=course_filter)

        grouped_absences = {}
        for absence in absences:
            key = f"{absence.id_inscription.id_etudiant.id_utilisateur}_{absence.id_seance.date_seance}"
            if key not in grouped_absences:
                justification = getattr(absence, "justification", None)
                date_encodage = justification.date_validation if justification and justification.date_validation else None
                grouped_absences[key] = {
                    "etudiant": absence.id_inscription.id_etudiant,
                    "date": absence.id_seance.date_seance,
                    "absences": [],
                    "encodee_par": absence.encodee_par,
                    "date_encodage": date_encodage,
                    "total_duree": 0.0,
                }
            grouped_absences[key]["absences"].append(absence)
            grouped_absences[key]["total_duree"] += float(absence.duree_absence)

        absences_list = sorted(
            grouped_absences.values(),
            key=lambda x: (x["date"], x["etudiant"].nom or ""),
            reverse=True,
        )

        paginator = Paginator(absences_list, 20)
        page_obj = safe_get_page(paginator, request.GET.get("page"))

        return render(request, "absences/justified_absences_list.html", {
            "page_obj": page_obj,
            "student_filter": student_filter or "",
            "date_filter": date_filter or "",
            "course_filter": course_filter or "",
        })
    except Exception:
        messages.error(request, "Une erreur interne est survenue.")
        logger.exception("Error in justified_absences_list")
        return render(request, "absences/justified_absences_list.html", {
            "page_obj": None,
            "student_filter": "",
            "date_filter": "",
            "course_filter": "",
        })
