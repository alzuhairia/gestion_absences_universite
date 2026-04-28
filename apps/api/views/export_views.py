"""
FICHIER : apps/api/views/export_views.py
RESPONSABILITE : Endpoints d'export — rapport PDF etudiant et Excel etudiants a risque.
  - export_student_pdf_api   : rapport PDF individuel (etudiant ou admin/secretaire)
  - export_at_risk_excel_api : export Excel des etudiants depassant le seuil (admin/secretaire)
"""
import datetime
import io
from typing import cast

from django.db.models import Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from openpyxl import Workbook
from openpyxl.worksheet.worksheet import Worksheet
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.absences.models import Absence
from apps.absences.services import get_system_threshold
from apps.academic_sessions.models import AnneeAcademique
from apps.accounts.models import User
from apps.enrollments.models import Inscription

from ..permissions import IsAdminOrSecretary

import logging

logger = logging.getLogger(__name__)


@extend_schema(
    summary="Export student absence report as PDF",
    tags=["Exports"],
    responses={(200, "application/pdf"): bytes},
)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def export_student_pdf_api(request, student_id):
    """Generate PDF absence report for a student."""
    user = request.user

    if user.role == User.Role.ETUDIANT:
        if user.pk != student_id:
            return Response(
                {"detail": "You can only export your own report."},
                status=status.HTTP_403_FORBIDDEN,
            )
        student = user
    elif user.role in (User.Role.ADMIN, User.Role.SECRETAIRE):
        student = get_object_or_404(User, pk=student_id, role=User.Role.ETUDIANT)
    else:
        return Response(
            {"detail": "Not authorized."},
            status=status.HTTP_403_FORBIDDEN,
        )

    academic_year = AnneeAcademique.objects.filter(active=True).first()

    insc_filter = {"id_etudiant": student, "status": Inscription.Status.EN_COURS}
    if academic_year:
        insc_filter["id_annee"] = academic_year

    inscriptions = Inscription.objects.filter(**insc_filter).select_related("id_cours")
    inscription_ids = list(inscriptions.values_list("id_inscription", flat=True))

    today = timezone.localdate()
    absence_sums = dict(
        Absence.objects.filter(
            id_inscription__in=inscription_ids,
            statut=Absence.Statut.NON_JUSTIFIEE,
            id_seance__date_seance__lte=today,
        )
        .values("id_inscription")
        .annotate(total=Sum("duree_absence"))
        .values_list("id_inscription", "total")
    )

    absences = (
        Absence.objects.filter(
            id_inscription__in=inscription_ids,
            statut=Absence.Statut.NON_JUSTIFIEE,
            id_seance__date_seance__lte=today,
        )
        .select_related("id_seance", "id_seance__id_cours")
        .order_by("id_seance__date_seance")[:500]
    )

    try:
        return _build_student_pdf(student, academic_year, inscriptions, absence_sums, absences)
    except Exception:
        logger.exception("PDF generation failed for student %s", student_id)
        return Response(
            {"detail": "Erreur lors de la generation du rapport PDF."},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


def _build_student_pdf(student, academic_year, inscriptions, absence_sums, absences):
    """Build and return the PDF HttpResponse."""
    buf = io.BytesIO()
    p = canvas.Canvas(buf, pagesize=A4)
    width, height = A4

    def check_page_break(y, margin=80):
        if y < margin:
            p.showPage()
            return height - 50
        return y

    p.setFont("Helvetica-Bold", 16)
    p.drawString(50, height - 50, "Universite - Rapport d'Absences")

    p.setFont("Helvetica", 12)
    p.drawString(50, height - 80, f"Etudiant: {student.get_full_name()}")
    p.drawString(50, height - 100, f"Email: {student.email}")
    if academic_year:
        p.drawString(50, height - 120, f"Annee academique: {academic_year.libelle}")
    p.drawString(50, height - 140, f"Date du rapport: {datetime.date.today()}")

    p.line(50, height - 160, width - 50, height - 160)
    y = height - 180

    p.setFont("Helvetica-Bold", 14)
    p.drawString(50, y, "Resume par Cours")
    y -= 20

    p.setFont("Helvetica", 10)
    for ins in inscriptions:
        cours = ins.id_cours
        total_abs = float(absence_sums.get(ins.id_inscription, 0) or 0)
        p.drawString(
            60,
            y,
            f"- {cours.nom_cours} ({cours.code_cours}): {total_abs}h non justifiees",
        )
        y -= 15
        y = check_page_break(y)

    y = check_page_break(y - 10)
    p.setFont("Helvetica-Bold", 14)
    p.drawString(50, y, "Detail des Absences Non Justifiees")
    y -= 20

    p.setFont("Helvetica", 10)
    for absence_obj in absences:
        seance = absence_obj.id_seance
        line = (
            f"Date: {seance.date_seance} | "
            f"Cours: {seance.id_cours.code_cours} | "
            f"Duree: {absence_obj.duree_absence}h | "
            f"Statut: {absence_obj.get_statut_display()}"
        )
        p.drawString(60, y, line)
        y -= 15
        y = check_page_break(y)

    p.showPage()
    p.save()

    buf.seek(0)
    safe_email = "".join(
        c if c.isalnum() or c in "._-@" else "_" for c in student.email
    )
    response = HttpResponse(buf.read(), content_type="application/pdf")
    response["Content-Disposition"] = (
        f'attachment; filename="rapport_absences_{safe_email}.pdf"'
    )
    return response


def _export_status(ins, rate, seuil):
    """Return export status label based on exemption logic."""
    seuil_eff = min(seuil + ins.exemption_margin, 100) if ins.exemption_40 else seuil
    if rate >= seuil_eff:
        return "BLOQUE"
    if ins.exemption_40:
        return "SOUS EXEMPTION"
    return "A RISQUE"


@extend_schema(
    summary="Export at-risk students as Excel (admin/secretary)",
    tags=["Exports"],
    responses={(200, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"): bytes},
)
@api_view(["GET"])
@permission_classes([IsAdminOrSecretary])
def export_at_risk_excel_api(request):
    """Export students exceeding absence threshold to Excel."""
    academic_year = AnneeAcademique.objects.filter(active=True).first()
    system_threshold = get_system_threshold()

    all_inscriptions = Inscription.objects.filter(
        status=Inscription.Status.EN_COURS
    ).select_related("id_cours", "id_etudiant")
    if academic_year:
        all_inscriptions = all_inscriptions.filter(id_annee=academic_year)

    inscription_ids = list(all_inscriptions.values_list("id_inscription", flat=True))
    today = timezone.localdate()
    absence_sums = dict(
        Absence.objects.filter(
            id_inscription__in=inscription_ids,
            statut=Absence.Statut.NON_JUSTIFIEE,
            id_seance__date_seance__lte=today,
        )
        .values("id_inscription")
        .annotate(total=Sum("duree_absence"))
        .values_list("id_inscription", "total")
    )

    wb = Workbook()
    ws = cast(Worksheet, wb.active)
    ws.title = "Etudiants a Risque"
    ws.append([
        "Nom",
        "Prenom",
        "Email",
        "Cours",
        "Heures Manquees",
        "Taux Absence (%)",
        "Statut",
    ])

    for ins in all_inscriptions:
        cours = ins.id_cours
        if cours.nombre_total_periodes > 0:
            total_abs = float(absence_sums.get(ins.id_inscription, 0) or 0)
            rate = (total_abs / cours.nombre_total_periodes) * 100
            seuil = (
                cours.seuil_absence
                if cours.seuil_absence is not None
                else system_threshold
            )
            if rate >= seuil:
                def _safe(val):
                    s = str(val) if val is not None else ""
                    if s and s[0] in ("=", "+", "-", "@", "\t", "\r"):
                        return "'" + s
                    return s

                ws.append([
                    _safe(ins.id_etudiant.nom),
                    _safe(ins.id_etudiant.prenom),
                    _safe(ins.id_etudiant.email),
                    _safe(f"{cours.nom_cours} ({cours.code_cours})"),
                    total_abs,
                    round(rate, 2),
                    _export_status(ins, rate, seuil),
                ])

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    response = HttpResponse(
        buf.read(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = 'attachment; filename="etudiants_a_risque.xlsx"'
    return response
