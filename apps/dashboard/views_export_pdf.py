"""
FICHIER : apps/dashboard/views_export_pdf.py
RESPONSABILITE : Export PDF rapport d'assiduité par étudiant
"""

import datetime
import io

from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_GET
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from apps.absences.models import Absence
from apps.accounts.models import User
from apps.audits.utils import log_action
from apps.dashboard.decorators import roles_required
from apps.enrollments.models import Inscription


@login_required
@roles_required(User.Role.ETUDIANT, User.Role.ADMIN, User.Role.SECRETAIRE)
@require_GET
def export_student_pdf(request, student_id=None):
    """
    Generate a PDF report of absences for a specific student.
    STRICT: Students can only export their own reports.
    Filtre par année académique active et inclut EN_ATTENTE + NON_JUSTIFIEE.

    Accès filtré par @roles_required (PROFESSEUR exclu). Les contrôles fins
    (un étudiant ne peut accéder qu'à son propre rapport) restent en vue.
    """
    from apps.academic_sessions.models import AnneeAcademique

    # STRICT: Students can only export their own reports
    if request.user.role == User.Role.ETUDIANT:
        student = request.user
    else:
        # ADMIN ou SECRETAIRE — student_id peut venir de l'URL ou de la query
        effective_student_id = student_id or request.GET.get("student_id")
        if not effective_student_id:
            return HttpResponseBadRequest("student_id requis")
        student = get_object_or_404(User, pk=effective_student_id, role=User.Role.ETUDIANT)

    # Filtrer par année académique active
    academic_year = AnneeAcademique.objects.filter(active=True).first()
    if not academic_year:
        academic_year = AnneeAcademique.objects.order_by("-id_annee").first()

    response = HttpResponse(content_type="application/pdf")
    # Sanitize email for filename (remove special chars that could break header)
    safe_email = "".join(c if c.isalnum() or c in "._-@" else "_" for c in student.email)
    response["Content-Disposition"] = (
        f'attachment; filename="rapport_absences_{safe_email}.pdf"'
    )

    buffer = io.BytesIO()
    p = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    def check_page_break(y, margin=80):
        """Crée une nouvelle page si nécessaire."""
        if y < margin:
            p.showPage()
            return height - 50
        return y

    # --- HEADER ---
    p.setFont("Helvetica-Bold", 16)
    p.drawString(50, height - 50, "Universite - Rapport d'Absences")

    p.setFont("Helvetica", 12)
    p.drawString(50, height - 80, f"Etudiant: {student.get_full_name()}")
    p.drawString(50, height - 100, f"Email: {student.email}")
    if academic_year:
        p.drawString(50, height - 120, f"Annee academique: {academic_year.libelle}")
    p.drawString(50, height - 140, f"Date du rapport: {datetime.date.today()}")

    # --- STATISTICS SUMMARY ---
    p.line(50, height - 160, width - 50, height - 160)
    y_position = height - 180

    # Filtrer les inscriptions par année académique active
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

    p.setFont("Helvetica-Bold", 14)
    p.drawString(50, y_position, "Resume par Cours")
    y_position -= 20

    if not inscriptions.exists():
        p.setFont("Helvetica", 10)
        p.drawString(
            60, y_position, "Aucune inscription trouvee pour cette annee academique."
        )
        y_position -= 15
    else:
        p.setFont("Helvetica", 10)
        for ins in inscriptions:
            cours = ins.id_cours
            total_abs = float(absence_sums.get(ins.id_inscription, 0) or 0)

            text = (
                f"- {cours.nom_cours} ({cours.code_cours}): {total_abs}h non justifiees"
            )
            p.drawString(60, y_position, text)
            y_position -= 15
            y_position = check_page_break(y_position)

    # --- DETAILED LIST ---
    y_position = check_page_break(y_position - 10)
    p.setFont("Helvetica-Bold", 14)
    p.drawString(50, y_position, "Detail des Absences Non Justifiees")
    y_position -= 20

    p.setFont("Helvetica", 10)
    absences = (
        Absence.objects.filter(
            id_inscription__in=inscription_ids,
            statut=Absence.Statut.NON_JUSTIFIEE,
            id_seance__date_seance__lte=today,
        )
        .select_related("id_seance", "id_seance__id_cours")
        .order_by("id_seance__date_seance")
    )

    if not absences.exists():
        p.drawString(60, y_position, "Aucune absence non justifiee enregistree.")
        y_position -= 15
    else:
        for absence_obj in absences:
            seance = absence_obj.id_seance
            line = (
                f"Date: {seance.date_seance} | "
                f"Cours: {seance.id_cours.code_cours} | "
                f"Duree: {absence_obj.duree_absence}h | "
                f"Statut: {absence_obj.get_statut_display()}"
            )
            p.drawString(60, y_position, line)
            y_position -= 15
            y_position = check_page_break(y_position)

    p.showPage()
    p.save()

    buffer.seek(0)
    response.write(buffer.read())

    # Traçabilité : journaliser l'export quand un admin/secrétaire accède aux données d'un étudiant
    if request.user.role in [User.Role.ADMIN, User.Role.SECRETAIRE]:
        log_action(
            request.user,
            f"Export PDF du rapport d'absences de l'étudiant {student.get_full_name()} ({student.email})",
            request,
            niveau="INFO",
            objet_type="EXPORT",
            objet_id=student.id_utilisateur,
        )

    return response
