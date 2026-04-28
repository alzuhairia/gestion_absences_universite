"""
FICHIER : apps/dashboard/views_export_excel.py
RESPONSABILITE : Export Excel liste étudiants à risque
"""

from typing import cast

from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.http import HttpResponse
from django.utils import timezone
from django.views.decorators.http import require_GET
from openpyxl import Workbook
from openpyxl.worksheet.worksheet import Worksheet

from apps.absences.models import Absence
from apps.audits.utils import log_action
from apps.dashboard.decorators import secretary_required
from apps.enrollments.models import Inscription


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
    ws = cast(Worksheet, wb.active)
    ws.title = "Étudiants à Risque"

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

    from apps.absences.services import get_system_threshold
    from apps.academic_sessions.models import AnneeAcademique

    active_year = AnneeAcademique.objects.filter(active=True).first()
    all_inscriptions = Inscription.objects.filter(
        status=Inscription.Status.EN_COURS
    ).select_related("id_cours", "id_etudiant")
    if active_year:
        all_inscriptions = all_inscriptions.filter(id_annee=active_year)
    inscription_ids = list(all_inscriptions.values_list("id_inscription", flat=True))
    system_threshold = get_system_threshold()
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

    def _safe(val):
        s = str(val) if val is not None else ""
        if s and s[0] in ("=", "+", "-", "@", "\t", "\r"):
            return "'" + s
        return s

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
            seuil_effectif = min(seuil + ins.exemption_margin, 100) if ins.exemption_40 else seuil
            if rate >= seuil:
                if ins.exemption_40 and rate < seuil_effectif:
                    statut = "EXEMPTÉ"
                else:
                    statut = "BLOQUÉ"

                ws.append([
                    _safe(ins.id_etudiant.nom),
                    _safe(ins.id_etudiant.prenom),
                    _safe(ins.id_etudiant.email),
                    _safe(f"{cours.nom_cours} ({cours.code_cours})"),
                    total_abs,
                    round(rate, 2),
                    statut,
                ])

    log_action(
        request.user,
        "Secrétaire a exporté la liste des étudiants à risque au format Excel",
        request,
        niveau="INFO",
        objet_type="EXPORT",
        objet_id=None,
    )

    wb.save(response)
    return response
