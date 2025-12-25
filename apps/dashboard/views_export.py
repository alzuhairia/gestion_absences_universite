import datetime
from django.http import HttpResponse
from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from openpyxl import Workbook

from apps.enrollments.models import Inscription
from apps.absences.models import Absence
from apps.accounts.models import User
from apps.dashboard.decorators import secretary_required

def export_student_pdf(request, student_id=None):
    """
    Generate a PDF report of absences for a specific student.
    STRICT: Students can only export their own reports.
    """
    # STRICT: Students can only export their own reports
    if request.user.role == User.Role.ETUDIANT:
        student = request.user
    elif student_id:
        # Admin/Secretary can view others
        student = User.objects.get(pk=student_id)
    else:
        student = request.user
    
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="absence_report_{student.email}.pdf"'
    
    p = canvas.Canvas(response, pagesize=A4)
    width, height = A4
    
    # --- HEADER ---
    p.setFont("Helvetica-Bold", 16)
    p.drawString(50, height - 50, "Université - Rapport d'Absences")
    
    p.setFont("Helvetica", 12)
    p.drawString(50, height - 80, f"Étudiant: {student.get_full_name()}")
    p.drawString(50, height - 100, f"Email: {student.email}")
    p.drawString(50, height - 120, f"Date du rapport: {datetime.date.today()}")
    
    # --- STATISTICS SUMMARY ---
    p.line(50, height - 140, width - 50, height - 140)
    y_position = height - 160
    
    inscriptions = Inscription.objects.filter(id_etudiant=student)
    
    p.setFont("Helvetica-Bold", 14)
    p.drawString(50, y_position, "Résumé par Cours")
    y_position -= 20
    
    p.setFont("Helvetica", 10)
    for ins in inscriptions:
        cours = ins.id_cours
        total_abs = Absence.objects.filter(id_inscription=ins, statut='NON_JUSTIFIEE').aggregate(total=Sum('duree_absence'))['total'] or 0
        
        text = f"- {cours.nom_cours} ({cours.code_cours}): {total_abs}h non justifiées"
        p.drawString(60, y_position, text)
        y_position -= 15
        
        if y_position < 100:
            p.showPage()
            y_position = height - 50
    
    # --- DETAILED LIST ---
    y_position -= 20
    p.setFont("Helvetica-Bold", 14)
    p.drawString(50, y_position, "Détail des Absences Non Justifiées")
    y_position -= 20
    
    p.setFont("Helvetica", 10)
    absences = Absence.objects.filter(id_inscription__in=inscriptions, statut='NON_JUSTIFIEE').order_by('id_seance__date_seance')
    
    for abs in absences:
        line = f"Date: {abs.id_seance.date_seance} | Cours: {abs.id_seance.id_cours.code_cours} | Durée: {abs.duree_absence}h"
        p.drawString(60, y_position, line)
        y_position -= 15
        
        if y_position < 50:
            p.showPage()
            y_position = height - 50

    p.showPage()
    p.save()
    return response


@login_required
@secretary_required
def export_at_risk_excel(request):
    """
    Export list of students overlapping the 40% threshold to Excel.
    """
    response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    response['Content-Disposition'] = 'attachment; filename="etudiants_a_risque.xlsx"'
    
    wb = Workbook()
    ws = wb.active
    ws.title = "Étudiants à Risque"
    
    # Headers
    columns = ['Nom', 'Prénom', 'Email', 'Cours', 'Heures Manquées', 'Taux Absence (%)', 'Statut']
    ws.append(columns)
    
    # Data
    all_inscriptions = Inscription.objects.select_related('id_cours', 'id_etudiant').all()
    
    for ins in all_inscriptions:
        cours = ins.id_cours
        if cours.nombre_total_periodes > 0:
            total_abs = Absence.objects.filter(
                id_inscription=ins, 
                statut='NON_JUSTIFIEE'
            ).aggregate(total=Sum('duree_absence'))['total'] or 0
            
            rate = (total_abs / cours.nombre_total_periodes) * 100
            
            if rate >= 40:
                statut = "EXEMPTÉ" if ins.exemption_40 else "BLOQUÉ"
                
                ws.append([
                    ins.id_etudiant.nom,
                    ins.id_etudiant.prenom,
                    ins.id_etudiant.email,
                    f"{cours.nom_cours} ({cours.code_cours})",
                    total_abs,
                    round(rate, 2),
                    statut
                ])
    
    from apps.audits.utils import log_action
    log_action(
        request.user,
        f"Secrétaire a exporté la liste des étudiants à risque au format Excel",
        request,
        niveau='INFO',
        objet_type='EXPORT',
        objet_id=None
    )
    
    wb.save(response)
    return response
