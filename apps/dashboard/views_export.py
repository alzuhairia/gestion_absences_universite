import datetime

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Sum
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_GET
from openpyxl import Workbook
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from apps.absences.models import Absence
from apps.accounts.models import User
from apps.audits.utils import log_action
from apps.dashboard.decorators import secretary_required
from apps.enrollments.models import Inscription


@login_required
@require_GET
def export_student_pdf(request, student_id=None):
    """
    Generate a PDF report of absences for a specific student.
    STRICT: Students can only export their own reports.
    Filtre par année académique active et inclut EN_ATTENTE + NON_JUSTIFIEE.
    """
    from apps.academic_sessions.models import AnneeAcademique

    # STRICT: Students can only export their own reports
    if request.user.role == User.Role.ETUDIANT:
        student = request.user
    elif request.user.role in [User.Role.ADMIN, User.Role.SECRETAIRE]:
        # student_id can come from URL parameter or GET query string
        effective_student_id = student_id or request.GET.get("student_id")
        if not effective_student_id:
            return HttpResponseBadRequest("student_id requis")
        student = get_object_or_404(User, pk=effective_student_id, role=User.Role.ETUDIANT)
    else:
        raise PermissionDenied("Acces non autorise")

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

    p = canvas.Canvas(response, pagesize=A4)
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

    # Cohérence avec la page rapports : EN_ATTENTE + NON_JUSTIFIEE
    absence_sums = dict(
        Absence.objects.filter(
            id_inscription__in=inscription_ids,
            statut__in=[Absence.Statut.NON_JUSTIFIEE, Absence.Statut.EN_ATTENTE],
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
            statut__in=[Absence.Statut.NON_JUSTIFIEE, Absence.Statut.EN_ATTENTE],
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


@login_required
@secretary_required
@require_GET
def export_at_risk_excel(request):
    """
    Export list of students overlapping the 40% threshold to Excel.
    """
    response = HttpResponse(
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    response["Content-Disposition"] = 'attachment; filename="etudiants_a_risque.xlsx"'

    wb = Workbook()
    ws = wb.active
    ws.title = "Étudiants à Risque"

    # Headers
    columns = [
        "Nom",
        "Prénom",
        "Email",
        "Cours",
        "Heures Manquées",
        "Taux Absence (%)",
        "Statut",
    ]
    ws.append(columns)

    # Data — filtré par année active
    from apps.absences.services import get_system_threshold
    from apps.academic_sessions.models import AnneeAcademique

    active_year = AnneeAcademique.objects.filter(active=True).first()
    all_inscriptions = Inscription.objects.filter(status=Inscription.Status.EN_COURS).select_related(
        "id_cours", "id_etudiant"
    )
    if active_year:
        all_inscriptions = all_inscriptions.filter(id_annee=active_year)
    inscription_ids = list(all_inscriptions.values_list("id_inscription", flat=True))
    system_threshold = get_system_threshold()
    absence_sums = dict(
        Absence.objects.filter(
            id_inscription__in=inscription_ids,
            statut__in=[Absence.Statut.NON_JUSTIFIEE, Absence.Statut.EN_ATTENTE],
        )
        .values("id_inscription")
        .annotate(total=Sum("duree_absence"))
        .values_list("id_inscription", "total")
    )

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
                statut = "EXEMPTÉ" if ins.exemption_40 else "BLOQUÉ"

                ws.append(
                    [
                        ins.id_etudiant.nom,
                        ins.id_etudiant.prenom,
                        ins.id_etudiant.email,
                        f"{cours.nom_cours} ({cours.code_cours})",
                        total_abs,
                        round(rate, 2),
                        statut,
                    ]
                )

    from apps.audits.utils import log_action

    log_action(
        request.user,
        f"Secrétaire a exporté la liste des étudiants à risque au format Excel",
        request,
        niveau="INFO",
        objet_type="EXPORT",
        objet_id=None,
    )

    wb.save(response)
    return response
