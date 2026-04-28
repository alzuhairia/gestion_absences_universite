"""
Vues étudiant pour la gestion des absences.

Responsabilité :
  - absence_details      : consulter ses absences et leur statut de justification
  - upload_justification : soumettre un justificatif pour une absence
  - download_justification : télécharger un justificatif (accès contrôlé par rôle)

SÉCURITÉ : @student_required sur toutes les vues étudiants.
Les étudiants ne peuvent accéder qu'à leurs propres absences.
"""
import logging
from pathlib import Path

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods

from ..models import Absence, Justification
from ..services import (
    calculer_absence_stats,
    calculer_pourcentage_absence,
    get_absences_queryset,
    get_justification_deadline,
    is_justification_expired,
)
from ..utils_upload import (
    UploadValidationError,
    generate_safe_upload_filename,
    validate_uploaded_file,
)
from apps.accounts.models import User
from apps.audits.utils import log_action
from apps.dashboard.decorators import roles_required, student_required
from apps.enrollments.models import Inscription
from apps.notifications.email import (
    build_justification_submitted_professor_email,
    send_notification_email,
)

logger = logging.getLogger(__name__)


@login_required
@student_required
@require_GET
def absence_details(request, id_inscription):
    """
    Affiche les détails des absences pour un étudiant — lecture seule.
    Inclut le statut de justification et le délai restant pour chaque absence.
    """
    inscription = get_object_or_404(
        Inscription, id_inscription=id_inscription, id_etudiant=request.user
    )

    absences = get_absences_queryset(inscription)

    absences_data = []
    for absence in absences:
        justification = getattr(absence, "justification", None)

        if justification:
            if justification.state == Justification.State.ACCEPTEE:
                status, status_color = "JUSTIFIÉE", "success"
            elif justification.state == Justification.State.REFUSEE:
                status, status_color = "NON JUSTIFIÉE", "danger"
            else:
                status, status_color = "EN ATTENTE", "warning"
        else:
            if absence.statut == Absence.Statut.JUSTIFIEE:
                status, status_color = "JUSTIFIÉE", "success"
            else:
                status, status_color = "NON JUSTIFIÉE", "danger"

        is_refused = justification is not None and justification.state == Justification.State.REFUSEE
        is_not_yet_submitted = justification is None and absence.statut not in (
            Absence.Statut.JUSTIFIEE,
            Absence.Statut.EN_ATTENTE,
        )
        can_submit_status = is_not_yet_submitted or is_refused

        deadline = get_justification_deadline(absence)
        expired = is_justification_expired(absence)
        can_submit = can_submit_status and not expired

        absences_data.append({
            "absence": absence,
            "status": status,
            "status_color": status_color,
            "justification": justification,
            "can_submit": can_submit,
            "deadline": deadline,
            "is_expired": expired and can_submit_status,
        })

    course = inscription.id_cours
    prof_name = course.professeur.get_full_name() if course.professeur else "Non assigné"

    stats = calculer_absence_stats(inscription)
    absence_rate = stats["taux"]
    seuil = inscription.id_cours.get_seuil_absence()
    seuil_effectif = min(seuil + inscription.exemption_margin, 100) if inscription.exemption_40 else seuil
    is_blocked = absence_rate >= seuil_effectif

    pct_stats = calculer_pourcentage_absence(request.user, course)

    return render(request, "absences/details.html", {
        "inscription": inscription,
        "course": course,
        "absences_data": absences_data,
        "prof_name": prof_name,
        "absence_rate": round(absence_rate, 1),
        "is_blocked": is_blocked,
        "is_exempted": inscription.exemption_40,
        "total_heures_cours": pct_stats["total_heures_cours"],
        "total_heures_absence": pct_stats["total_heures_absence"],
        "pourcentage_absence": pct_stats["pourcentage_absence"],
        "pourcentage_presence": pct_stats["pourcentage_presence"],
    })


@login_required
@student_required
@require_http_methods(["GET", "POST"])
def upload_justification(request, absence_id):
    """
    Soumission d'un justificatif par l'étudiant.
    Strictement limité aux absences NON JUSTIFIÉES ou REFUSÉES.
    Le délai de soumission est de JUSTIFICATION_DEADLINE_DAYS jours.
    """
    absence = get_object_or_404(Absence, id_absence=absence_id)

    if absence.id_inscription.id_etudiant != request.user:
        messages.error(request, "Accès non autorisé. Vous ne pouvez consulter que vos propres absences.")
        return redirect("dashboard:student_dashboard")

    if absence.statut == Absence.Statut.JUSTIFIEE:
        messages.info(request, "Cette absence est déjà justifiée.")
        return redirect("absences:details", id_inscription=absence.id_inscription.id_inscription)

    justification = Justification.objects.filter(id_absence=absence).first()

    if justification and justification.state == Justification.State.ACCEPTEE:
        messages.success(request, "Votre justificatif a été accepté par le secrétariat.")
        return redirect("absences:details", id_inscription=absence.id_inscription.id_inscription)

    if justification and justification.state == Justification.State.EN_ATTENTE:
        messages.warning(
            request,
            "Un justificatif a déjà été soumis et est en cours d'examen. "
            "Vous serez notifié une fois la décision prise.",
        )
        return redirect("absences:details", id_inscription=absence.id_inscription.id_inscription)

    deadline = get_justification_deadline(absence)
    if is_justification_expired(absence):
        messages.error(
            request,
            f"Le délai de justification est dépassé. "
            f"Vous aviez jusqu'au {deadline.strftime('%d/%m/%Y')}.",
        )
        return redirect("absences:details", id_inscription=absence.id_inscription.id_inscription)

    if request.method == "POST":
        file = request.FILES.get("document")
        if not file:
            messages.error(request, "Aucun fichier reçu. Veuillez sélectionner un PDF, JPG ou PNG.")
            return redirect("absences:upload", absence_id=absence_id)

        comment = request.POST.get("comment", "")

        try:
            meta = validate_uploaded_file(file)
            file.name = generate_safe_upload_filename(meta["extension"])
        except UploadValidationError as exc:
            messages.error(request, " ".join(exc.messages))
            return redirect("absences:upload", absence_id=absence_id)

        new_justification = None
        with transaction.atomic():
            if justification and justification.state == Justification.State.REFUSEE:
                justification.document = file
                justification.commentaire = comment
                justification.state = Justification.State.EN_ATTENTE
                justification.validee_par = None
                justification.date_validation = None
                justification.save()
                new_justification = justification
            elif not justification:
                new_justification = Justification.objects.create(
                    id_absence=absence,
                    document=file,
                    commentaire=comment,
                    state=Justification.State.EN_ATTENTE,
                )
            else:
                messages.error(request, "Impossible de soumettre le justificatif dans l'état actuel.")
                return redirect("absences:upload", absence_id=absence_id)

            absence.statut = Absence.Statut.EN_ATTENTE
            absence.save()

        if new_justification:
            log_action(
                request.user,
                f"Étudiant a soumis une justification pour l'absence {absence.id_absence} "
                f"- {absence.id_seance.id_cours.code_cours}",
                request,
                niveau="INFO",
                objet_type="JUSTIFICATION",
                objet_id=new_justification.id_justification,
            )
            professor = absence.id_seance.id_cours.professeur
            if professor:
                subj, body, html_body = build_justification_submitted_professor_email(
                    professor,
                    request.user,
                    absence.id_seance.id_cours.code_cours,
                    str(absence.id_seance.date_seance),
                )
                send_notification_email(professor, subj, body, html_body)

        messages.success(
            request,
            "Votre justificatif a été envoyé et est en attente de validation par le secrétariat. "
            "Vous serez notifié une fois la décision prise.",
        )
        return redirect("absences:details", id_inscription=absence.id_inscription.id_inscription)

    return render(request, "absences/justify.html", {
        "absence": absence,
        "justification": justification,
        "deadline": deadline,
        "days_remaining": max((deadline - timezone.localdate()).days, 0),
    })


@login_required
@roles_required(User.Role.SECRETAIRE, User.Role.ADMIN, User.Role.ETUDIANT)
@require_GET
def download_justification(request, justification_id):
    """
    Télécharger un justificatif avec contrôle d'accès :
    - Secrétaire / Admin : accès autorisé
    - Étudiant : seulement ses propres justificatifs
    - Professeur : refusé (filtré par le décorateur roles_required)
    """
    justification = get_object_or_404(Justification, id_justification=justification_id)
    absence = justification.id_absence

    if request.user.role == User.Role.ETUDIANT:
        if absence.id_inscription.id_etudiant != request.user:
            raise PermissionDenied("Accès non autorisé")

    if not justification.document or not justification.document.name:
        raise Http404("Aucun document")

    try:
        justification.document.open("rb")
    except FileNotFoundError as exc:
        raise Http404("Le fichier justificatif est introuvable sur le serveur.") from exc
    except OSError as exc:
        raise Http404("Impossible d'ouvrir le fichier justificatif.") from exc

    return FileResponse(
        justification.document,
        as_attachment=True,
        filename=Path(justification.document.name).name,
    )
