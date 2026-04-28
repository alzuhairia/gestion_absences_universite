"""
FICHIER : apps/absences/views/qr_professor_session.py
RESPONSABILITE : Gestion de la session QR active — dashboard temps réel, renouvellement, finalisation

SÉCURITÉ : @professor_required + vérification course.professeur == request.user
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
    """Dashboard temps réel : QR affiché + liste des scans (HTMX polling)."""
    qr_token = get_object_or_404(QRAttendanceToken, token=token)
    seance = qr_token.seance
    course = seance.id_cours

    if course.professeur is None or course.professeur.pk != request.user.pk:
        messages.error(request, "Accès non autorisé.")
        return redirect("dashboard:instructor_dashboard")

    scan_url = request.build_absolute_uri(
        reverse("absences:qr_scan", kwargs={"token": str(token)})
    )
    qr_data_uri = _generate_qr_data_uri(scan_url)

    inscriptions = list(
        Inscription.objects.filter(
            id_cours=course,
            id_annee=seance.id_annee,
            status=Inscription.Status.EN_COURS,
        ).select_related("id_etudiant")
    )

    scan_records = {
        sr.inscription.pk if sr.inscription else None: sr
        for sr in QRScanRecord.objects.filter(seance=seance).select_related("inscription")
    }
    scanned_ids = set(scan_records.keys())

    scanned = []
    suspicious_count = 0
    for ins in inscriptions:
        if ins.id_inscription in scanned_ids:
            sr = scan_records[ins.id_inscription]
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
        "qr_duration_seconds": sys_settings.qr_token_duration_seconds,
    }

    if request.headers.get("HX-Request"):
        return render(request, "absences/_qr_scan_list.html", ctx)

    return render(request, "absences/qr_dashboard.html", ctx)


@login_required
@professor_required
@require_POST
def qr_refresh_token(request, token):
    """Renouvelle le token QR sans perdre les scans existants."""
    from apps.dashboard.models import SystemSettings

    qr_token = get_object_or_404(QRAttendanceToken, token=token)
    seance = qr_token.seance
    course = seance.id_cours

    if course.professeur_id != request.user.pk:
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return JsonResponse({"error": "Accès non autorisé."}, status=403)
        messages.error(request, "Accès non autorisé.")
        return redirect("dashboard:instructor_dashboard")

    sys_settings = SystemSettings.get_settings()

    old_verify_location = qr_token.verify_location
    old_lat = qr_token.latitude
    old_lng = qr_token.longitude

    QRAttendanceToken.objects.filter(seance=seance, is_active=True).update(is_active=False)

    new_token = QRAttendanceToken.objects.create(
        seance=seance,
        created_by=request.user,
        expires_at=timezone.now() + timedelta(seconds=sys_settings.qr_token_duration_seconds),
        verify_location=old_verify_location,
        latitude=old_lat,
        longitude=old_lng,
    )

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
            "refresh_url": reverse("absences:qr_refresh_token", kwargs={"token": str(new_token.token)}),
            "dashboard_url": reverse("absences:qr_dashboard", kwargs={"token": str(new_token.token)}),
            "finalize_url": reverse("absences:qr_finalize", kwargs={"token": str(new_token.token)}),
        })

    messages.success(request, "QR code rafraîchi avec un nouveau token.")
    return redirect("absences:qr_dashboard", token=new_token.token)


@login_required
@professor_required
@require_POST
def qr_finalize(request, token):
    """
    Finalise la séance QR : les étudiants non scannés sont marqués absents.
    Verrouille la séance après finalisation.
    """
    qr_token = get_object_or_404(QRAttendanceToken, token=token)
    course = qr_token.seance.id_cours

    if course.professeur is None or course.professeur.pk != request.user.pk:
        messages.error(request, "Accès non autorisé.")
        return redirect("dashboard:instructor_dashboard")

    with transaction.atomic():
        seance = Seance.objects.select_for_update().get(pk=qr_token.seance.pk)

        if seance.validated:
            messages.warning(request, "Cette séance est déjà validée.")
            return redirect("dashboard:instructor_course_detail", course.id_cours)

        inscriptions = list(
            Inscription.objects.filter(
                id_cours=course,
                id_annee=seance.id_annee,
                status=Inscription.Status.EN_COURS,
            ).select_related("id_etudiant", "id_cours")
        )

        scanned_ids = set(
            QRScanRecord.objects.filter(seance=seance).values_list("inscription_id", flat=True)
        )

        QRAttendanceToken.objects.filter(seance=seance, is_active=True).update(is_active=False)

        absent_count = 0
        for ins in inscriptions:
            if ins.id_inscription not in scanned_ids:
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
