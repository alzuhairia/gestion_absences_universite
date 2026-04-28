"""
FICHIER : apps/dashboard/views_admin_audit.py
RESPONSABILITE : Consultation et export des journaux d'audit + logs de scans QR
"""

import csv
import logging
from datetime import date as date_type, datetime

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET

from apps.absences.models import QRScanLog
from apps.audits.models import LogAudit
from apps.audits.utils import log_action
from apps.dashboard.decorators import admin_required
from apps.utils import safe_get_page

logger = logging.getLogger(__name__)


@login_required
@admin_required
@require_GET
def admin_audit_logs(request):
    """Consultation de tous les journaux d'audit avec filtres"""

    role_filter = request.GET.get("role", "")
    action_filter = request.GET.get("action", "")
    date_from = request.GET.get("date_from", "")
    date_to = request.GET.get("date_to", "")
    user_filter = request.GET.get("user", "")
    search_query = request.GET.get("q", "")

    logs = LogAudit.objects.select_related("id_utilisateur").all()

    if role_filter:
        logs = logs.filter(id_utilisateur__role=role_filter)
    if action_filter:
        logs = logs.filter(action__icontains=action_filter)
    if date_from:
        try:
            date_type.fromisoformat(date_from)
            logs = logs.filter(date_action__date__gte=date_from)
        except ValueError:
            pass
    if date_to:
        try:
            date_type.fromisoformat(date_to)
            logs = logs.filter(date_action__date__lte=date_to)
        except ValueError:
            pass
    if user_filter:
        logs = logs.filter(
            Q(id_utilisateur__nom__icontains=user_filter)
            | Q(id_utilisateur__prenom__icontains=user_filter)
            | Q(id_utilisateur__email__icontains=user_filter)
        )
    if search_query:
        logs = logs.filter(action__icontains=search_query)

    logs = logs.order_by("-date_action")

    paginator = Paginator(logs, 50)
    logs_page = safe_get_page(paginator, request.GET.get("page"))

    return render(
        request,
        "dashboard/admin_audit_logs.html",
        {
            "logs": logs_page,
            "role_filter": role_filter,
            "action_filter": action_filter,
            "date_from": date_from,
            "date_to": date_to,
            "user_filter": user_filter,
            "search_query": search_query,
        },
    )


@login_required
@admin_required
@require_GET
def admin_export_audit_csv(request):
    """Export des journaux d'audit en CSV"""

    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = (
        f'attachment; filename="audit_logs_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv"'
    )

    writer = csv.writer(response)
    writer.writerow(
        ["Date/Heure", "Utilisateur", "Email", "Rôle", "Action", "Adresse IP"]
    )

    logs = (
        LogAudit.objects.select_related("id_utilisateur").all().order_by("-date_action")
    )

    role_filter = request.GET.get("role", "")
    action_filter = request.GET.get("action", "")
    date_from = request.GET.get("date_from", "")
    date_to = request.GET.get("date_to", "")

    if role_filter:
        logs = logs.filter(id_utilisateur__role=role_filter)
    if action_filter:
        logs = logs.filter(action__icontains=action_filter)
    if date_from:
        try:
            date_type.fromisoformat(date_from)
            logs = logs.filter(date_action__date__gte=date_from)
        except ValueError:
            pass
    if date_to:
        try:
            date_type.fromisoformat(date_to)
            logs = logs.filter(date_action__date__lte=date_to)
        except ValueError:
            pass

    def _sanitize_csv(value):
        """Prefix dangerous CSV values to prevent formula injection in Excel."""
        s = str(value) if value is not None else ""
        if s and s[0] in ("=", "+", "-", "@", "\t", "\r"):
            return "'" + s
        return s

    for log in logs.iterator(chunk_size=2000):
        user = log.id_utilisateur
        if user:
            user_name = f"{user.prenom} {user.nom}"
            user_email = user.email
            user_role = user.get_role_display()
        else:
            user_name = "(utilisateur supprimé)"
            user_email = ""
            user_role = ""
        writer.writerow(
            [
                log.date_action.strftime("%Y-%m-%d %H:%M:%S"),
                _sanitize_csv(user_name),
                _sanitize_csv(user_email),
                _sanitize_csv(user_role),
                _sanitize_csv(log.action),
                _sanitize_csv(log.adresse_ip),
            ]
        )

    log_action(
        request.user,
        "Export des journaux d'audit (CSV)",
        request,
        niveau="INFO",
        objet_type="SYSTEM",
    )
    return response


@login_required
@admin_required
@require_GET
def admin_qr_scan_logs(request):
    """Consultation des logs de scan QR avec filtres"""

    result_filter = request.GET.get("result", "")
    gps_filter = request.GET.get("gps", "")
    date_from = request.GET.get("date_from", "")
    date_to = request.GET.get("date_to", "")
    student_filter = request.GET.get("student", "")

    logs = QRScanLog.objects.select_related("etudiant", "seance", "seance__id_cours").all()

    if result_filter:
        logs = logs.filter(scan_result=result_filter)
    if gps_filter:
        logs = logs.filter(gps_status=gps_filter)
    if date_from:
        try:
            date_type.fromisoformat(date_from)
            logs = logs.filter(timestamp__gte=date_from)
        except ValueError:
            pass
    if date_to:
        try:
            date_type.fromisoformat(date_to)
            logs = logs.filter(timestamp__date__lte=date_to)
        except ValueError:
            pass
    if student_filter:
        logs = logs.filter(
            Q(etudiant__nom__icontains=student_filter)
            | Q(etudiant__prenom__icontains=student_filter)
            | Q(etudiant__email__icontains=student_filter)
        )

    logs = logs.order_by("-timestamp")

    paginator = Paginator(logs, 50)
    logs_page = safe_get_page(paginator, request.GET.get("page"))

    return render(
        request,
        "dashboard/admin_qr_scan_logs.html",
        {
            "logs": logs_page,
            "result_filter": result_filter,
            "gps_filter": gps_filter,
            "date_from": date_from,
            "date_to": date_to,
            "student_filter": student_filter,
            "scan_results": QRScanLog.ScanResult.choices,
            "gps_statuses": QRScanLog.GPSStatus.choices,
        },
    )
