import datetime
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch

def generate_absence_report(buffer, student, academic_year, course_data):
    """
    Génère un rapport PDF d'assiduité pour un étudiant.
    """
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    elements = []
    styles = getSampleStyleSheet()

    # --- Title ---
    title_style = styles['Title']
    elements.append(Paragraph(f"Relevé d'Absences - {academic_year}", title_style))
    elements.append(Spacer(1, 0.25 * inch))

    # --- Student Info ---
    normal_style = styles['Normal']
    elements.append(Paragraph(f"<b>Étudiant :</b> {student.get_full_name()}", normal_style))
    elements.append(Paragraph(f"<b>Email :</b> {student.email}", normal_style))
    elements.append(Paragraph(f"<b>Date du rapport :</b> {datetime.date.today().strftime('%d/%m/%Y')}", normal_style))
    elements.append(Spacer(1, 0.5 * inch))

    # --- Table Data ---
    # Header
    data = [['Cours', 'Vol. Horaire', 'Absences (h)', 'Taux (%)', 'Statut']]

    # Rows
    for course in course_data:
        status_text = "Admissible" if course['status'] else "BLOQUÉ"
        # Optional: color text in table style later if needed, but text is fine
        
        row = [
            course['nom'],
            f"{course['total_periods']}h",
            f"{course['duree_absence']:.1f}h",
            f"{course['absence_rate']:.1f}%",
            status_text
        ]
        data.append(row)

    # --- Table Layout ---
    # Column widths
    col_widths = [3.0 * inch, 1.0 * inch, 1.0 * inch, 1.0 * inch, 1.5 * inch]
    
    table = Table(data, colWidths=col_widths)
    
    # Table Styling
    style = TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('ALIGN', (0, 0), (0, -1), 'LEFT'),  # Left align Course Names
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 12),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
    ])
    
    # Conditional formatting for "BLOQUÉ" rows could be added here loop-wise, 
    # but keeping it simple for now standard striped table.
    
    table.setStyle(style)
    elements.append(table)

    # --- Footer ---
    elements.append(Spacer(1, 0.5 * inch))
    footer_text = "Ce document est généré automatiquement par le système de gestion des absences."
    elements.append(Paragraph(footer_text, styles['Italic']))

    doc.build(elements)
