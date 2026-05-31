"""
Utilitaire de rapport PDF du système d'absences UniAbsences.

Ce module fournit ``generate_absence_report``, qui écrit un rapport de
présence PDF formaté directement dans un tampon de type fichier en utilisant
ReportLab Platypus.  Le rapport comprend un tableau récapitulatif des
absences par cours avec les heures manquées, le taux d'absence et le statut
d'éligibilité.

Appelé depuis ``views_profile.download_report_pdf`` (libre-service étudiant)
et constitue le moteur de rendu partagé pour les flux d'export PDF basés sur
les templates et sur l'API.

Fait partie du système d'absences UniAbsences.
"""

import datetime

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


def generate_absence_report(buffer, student, academic_year, course_data):
    """
    Génère un rapport d'absences PDF formaté pour un seul étudiant et l'écrit dans un tampon.

    Le rapport contient :
      - Une ligne de titre avec l'année académique.
      - Bloc d'identification de l'étudiant (nom complet, email, date du rapport).
      - Un tableau récapitulatif avec une ligne par cours, indiquant les heures
        totales de séance, les heures manquées, le taux d'absence en pourcentage
        et le statut d'éligibilité.
      - Une clause de bas de page générée automatiquement.

    Le PDF est écrit directement dans ``buffer`` en utilisant le moteur de mise
    en page Platypus de ReportLab.  Le tampon n'est ni repositionné ni fermé
    après l'écriture ; l'appelant est responsable du repositionnement à la
    position 0 avant de lire les données.

    Paramètres :
        buffer : Un objet inscriptible de type fichier (par ex. ``io.BytesIO``)
            qui recevra les octets PDF bruts.
        student : Une instance User dont les attributs ``get_full_name()`` et
            ``email`` sont utilisés dans l'en-tête du rapport.
        academic_year : Une étiquette lisible pour l'année académique
            (par ex. ``"2024-2025"``), imprimée dans le titre du rapport.
        course_data : Un itérable de dicts, contenant chacun :
            - ``"nom"`` (str) : nom d'affichage du cours.
            - ``"total_periods"`` (int|float) : nombre total d'heures prévues.
            - ``"duree_absence"`` (float) : nombre total d'heures manquées.
            - ``"absence_rate"`` (float) : pourcentage d'absence (0–100).
            - ``"status"`` (bool) : True si l'étudiant est admissible à l'examen.
    """
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    elements = []
    styles = getSampleStyleSheet()

    # --- Titre ---
    title_style = styles["Title"]
    elements.append(Paragraph(f"Relevé d'Absences - {academic_year}", title_style))
    elements.append(Spacer(1, 0.25 * inch))

    # --- Infos étudiant ---
    normal_style = styles["Normal"]
    elements.append(
        Paragraph(f"<b>Étudiant :</b> {student.get_full_name()}", normal_style)
    )
    elements.append(Paragraph(f"<b>Email :</b> {student.email}", normal_style))
    elements.append(
        Paragraph(
            f"<b>Date du rapport :</b> {datetime.date.today().strftime('%d/%m/%Y')}",
            normal_style,
        )
    )
    elements.append(Spacer(1, 0.5 * inch))

    # --- Données du tableau ---
    # En-tête
    data = [["Cours", "Vol. Horaire", "Absences (h)", "Taux (%)", "Statut"]]

    # Lignes
    for course in course_data:
        status_text = "Admissible" if course["status"] else "BLOQUÉ"

        row = [
            course["nom"],
            f"{course['total_periods']}h",
            f"{course['duree_absence']:.1f}h",
            f"{course['absence_rate']:.1f}%",
            status_text,
        ]
        data.append(row)

    # --- Mise en page du tableau ---
    # Largeurs de colonnes
    col_widths = [3.0 * inch, 1.0 * inch, 1.0 * inch, 1.0 * inch, 1.5 * inch]

    table = Table(data, colWidths=col_widths)

    # Style du tableau
    style = TableStyle(
        [
            ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("ALIGN", (0, 0), (0, -1), "LEFT"),  # Alignement à gauche des noms de cours
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 12),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 12),
            ("BACKGROUND", (0, 1), (-1, -1), colors.beige),
            ("GRID", (0, 0), (-1, -1), 1, colors.black),
        ]
    )

    table.setStyle(style)
    elements.append(table)

    # --- Pied de page ---
    elements.append(Spacer(1, 0.5 * inch))
    footer_text = (
        "Ce document est généré automatiquement par le système de gestion des absences."
    )
    elements.append(Paragraph(footer_text, styles["Italic"]))

    doc.build(elements)
