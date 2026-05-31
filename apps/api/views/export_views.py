"""
Endpoints d'export de l'API pour l'API REST UniAbsences.

Ce module fournit deux endpoints de téléchargement qui génèrent des rapports
binaires à la volée en utilisant ReportLab (PDF) et openpyxl (Excel).

Endpoints
---------
``export_student_pdf_api`` (GET /api/exports/students/{id}/pdf/)
    Rapport d'absences individuel pour un seul étudiant. Les étudiants ne
    peuvent télécharger que leur propre rapport ; les admins et secrétaires
    peuvent télécharger le rapport de n'importe quel étudiant. Le PDF liste
    un résumé d'absences par cours suivi d'un tableau détaillé des
    enregistrements d'absences non justifiées.

``export_at_risk_excel_api`` (GET /api/exports/at-risk/excel/)
    Export Excel groupé de tous les étudiants dépassant actuellement le
    seuil d'absence pour au moins un cours. Restreint aux admins et
    secrétaires. Chaque ligne inclut l'identité de l'étudiant, le cours,
    les heures manquées, le taux d'absence et un libellé de statut
    (BLOQUE / SOUS EXEMPTION / A RISQUE).

Partie de l'API REST UniAbsences.
"""
import datetime
import io
import logging
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
from apps.utils import excel_safe_cell, pdf_check_page_break

from ..permissions import IsAdminOrSecretary

logger = logging.getLogger(__name__)


@extend_schema(
    summary="Export student absence report as PDF",
    tags=["Exports"],
    responses={(200, "application/pdf"): bytes},
)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def export_student_pdf_api(request, student_id):
    """
    Génère et diffuse un rapport d'absences PDF pour un seul étudiant.

    Contrôle d'accès :
      - Les étudiants ne peuvent télécharger que leur propre rapport. Demander
        le rapport d'un autre étudiant retourne HTTP 403.
      - Les administrateurs et secrétaires peuvent télécharger le rapport
        pour n'importe quel compte étudiant.
      - Les professeurs et autres rôles reçoivent HTTP 403.

    Le PDF contient deux sections :
      1. Un résumé par cours du total des heures d'absence non justifiées.
      2. Un tableau détaillé chronologique des enregistrements individuels
         d'absences non justifiées (limité à 500 lignes pour borner
         l'utilisation de la mémoire).

    Seules les absences non justifiées des séances qui ont déjà eu lieu
    (``date_seance <= today``) sont incluses dans les deux sections.

    Paramètres :
        request (Request) : La requête HTTP authentifiée.
        student_id (int) : Clé primaire de l'étudiant cible.

    Retourne :
        HttpResponse : Une réponse ``application/pdf`` avec le rapport
            généré en pièce jointe. Retourne une réponse d'erreur JSON en
            cas d'échec de permission (403) ou d'échec de génération PDF (500).
    """
    user = request.user

    # --- Contrôle d'accès : applique la propriété pour les étudiants, recherche pour le personnel ---
    if user.role == User.Role.ETUDIANT:
        # Les étudiants ne peuvent télécharger que leur propre rapport
        if user.pk != student_id:
            return Response(
                {"detail": "You can only export your own report."},
                status=status.HTTP_403_FORBIDDEN,
            )
        student = user
    elif user.role in (User.Role.ADMIN, User.Role.SECRETAIRE):
        # Le personnel peut télécharger le rapport de n'importe quel étudiant ; 404 si l'ID n'existe pas
        student = get_object_or_404(User, pk=student_id, role=User.Role.ETUDIANT)
    else:
        # Les professeurs et rôles inconnus sont refusés
        return Response(
            {"detail": "Not authorized."},
            status=status.HTTP_403_FORBIDDEN,
        )

    # Filtre sur l'année académique active lorsqu'elle est configurée
    academic_year = AnneeAcademique.objects.filter(active=True).first()

    insc_filter = {"id_etudiant": student, "status": Inscription.Status.EN_COURS}
    if academic_year:
        insc_filter["id_annee"] = academic_year

    # Charge les inscriptions avec les données de cours pour éviter N+1 dans la section résumé du PDF
    inscriptions = Inscription.objects.filter(**insc_filter).select_related("id_cours")
    inscription_ids = list(inscriptions.values_list("id_inscription", flat=True))

    today = timezone.localdate()

    # Agrège les heures non justifiées par inscription en une seule requête (utilisé dans le résumé)
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

    # Charge les enregistrements d'absence individuels pour la section détail ; limité à 500 pour borner la mémoire
    absences = (
        Absence.objects.filter(
            id_inscription__in=inscription_ids,
            statut=Absence.Statut.NON_JUSTIFIEE,
            id_seance__date_seance__lte=today,
        )
        .select_related("id_seance", "id_seance__id_cours")
        .order_by("id_seance__date_seance")[:500]
    )

    # Délègue au constructeur PDF ; intercepte et journalise toute exception ReportLab
    try:
        return _build_student_pdf(student, academic_year, inscriptions, absence_sums, absences)
    except Exception:
        logger.exception("PDF generation failed for student %s", student_id)
        return Response(
            {"detail": "Erreur lors de la generation du rapport PDF."},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


def _build_student_pdf(student, academic_year, inscriptions, absence_sums, absences):
    """
    Construit le PDF du rapport d'absences de l'étudiant et le retourne comme HttpResponse.

    Le PDF est rendu entièrement en mémoire en utilisant ReportLab. Deux
    sections sont dessinées sur le canvas :

    1. Résumé par cours — une ligne par inscription active montrant le total
       des heures non justifiées pour ce cours.
    2. Détail des absences individuelles — une ligne par enregistrement
       d'absence non justifiée, montrant date, code de cours, durée et
       statut d'affichage.

    Les sauts de page automatiques sont gérés par ``pdf_check_page_break``
    (depuis ``apps.utils``), qui commence une nouvelle page et réinitialise
    ``y`` lorsque le curseur approche de la marge inférieure.

    Le nom de fichier dans ``Content-Disposition`` est dérivé de l'adresse
    email de l'étudiant, avec tous les caractères non alphanumériques
    remplacés par des underscores pour garantir la sécurité multi-plateforme
    des noms de fichiers.

    Paramètres :
        student (User) : L'étudiant dont le rapport est généré.
        academic_year (AnneeAcademique | None) : L'année académique active,
            ou None lorsqu'aucune n'est configurée.
        inscriptions (QuerySet[Inscription]) : Les inscriptions actives de
            l'étudiant (préchargées avec ``id_cours``).
        absence_sums (dict) : Mapping de PK d'inscription → total des heures
            non justifiées (pré-agrégé par l'appelant).
        absences (QuerySet[Absence]) : Enregistrements d'absences non
            justifiées à lister dans la section détail (préchargés avec
            ``id_seance``).

    Retourne :
        HttpResponse : Une réponse pièce jointe ``application/pdf`` contenant
            les octets PDF générés.
    """
    # Écrit le PDF dans un buffer en mémoire pour éviter de toucher au système de fichiers
    buf = io.BytesIO()
    p = canvas.Canvas(buf, pagesize=A4)
    width, height = A4

    # Helper local qui délègue à l'utilitaire partagé de saut de page
    def _page_break(y, margin=80):
        """Délègue à ``pdf_check_page_break`` en injectant le canvas et la hauteur courants."""
        return pdf_check_page_break(p, height, y, margin)

    # --- En-tête de page ---
    p.setFont("Helvetica-Bold", 16)
    p.drawString(50, height - 50, "Universite - Rapport d'Absences")

    p.setFont("Helvetica", 12)
    p.drawString(50, height - 80, f"Etudiant: {student.get_full_name()}")
    p.drawString(50, height - 100, f"Email: {student.email}")
    if academic_year:
        p.drawString(50, height - 120, f"Annee academique: {academic_year.libelle}")
    p.drawString(50, height - 140, f"Date du rapport: {datetime.date.today()}")

    # Ligne horizontale séparant l'en-tête du corps
    p.line(50, height - 160, width - 50, height - 160)
    y = height - 180

    # --- Section 1 : Résumé par cours ---
    p.setFont("Helvetica-Bold", 14)
    p.drawString(50, y, "Resume par Cours")
    y -= 20

    p.setFont("Helvetica", 10)
    for ins in inscriptions:
        cours = ins.id_cours
        # Recherche la somme pré-agrégée ; par défaut 0 lorsqu'aucune absence n'existe
        total_abs = float(absence_sums.get(ins.id_inscription, 0) or 0)
        p.drawString(
            60,
            y,
            f"- {cours.nom_cours} ({cours.code_cours}): {total_abs}h non justifiees",
        )
        y -= 15
        # Commence une nouvelle page si le curseur est trop proche de la marge inférieure
        y = _page_break(y)

    # --- Section 2 : Détail des absences individuelles ---
    y = _page_break(y - 10)
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
        y = _page_break(y)

    # Finalise le PDF et rembobine le buffer pour la lecture
    p.showPage()
    p.save()
    buf.seek(0)

    # Assainit l'email pour produire un nom de fichier ASCII sécurisé
    safe_email = "".join(
        c if c.isalnum() or c in "._-@" else "_" for c in student.email
    )
    response = HttpResponse(buf.read(), content_type="application/pdf")
    response["Content-Disposition"] = (
        f'attachment; filename="rapport_absences_{safe_email}.pdf"'
    )
    return response


def _export_status(ins, rate, seuil):
    """
    Détermine le libellé de statut d'export pour la ligne d'inscription d'un étudiant.

    Trois libellés sont définis par ordre de gravité décroissant :

    - ``"BLOQUE"``       — le taux d'absence non justifiée de l'étudiant
                           atteint ou dépasse le seuil effectif (en tenant
                           compte de l'exemption). L'inscription peut être
                           bloquée.
    - ``"SOUS EXEMPTION"``— le taux est inférieur au seuil effectif mais
                           l'étudiant a un indicateur ``exemption_40``
                           actif, ce qui signifie qu'il bénéficie d'une
                           limite relevée.
    - ``"A RISQUE"``     — le taux atteint ou dépasse le seuil de base mais
                           l'étudiant n'a pas de statut d'exemption.

    Remarque : cette fonction n'est appelée que pour les inscriptions où
    ``rate >= seuil`` (seuil de base), donc ``"A RISQUE"`` et ``"BLOQUE"``
    sont les libellés les plus courants.

    Paramètres :
        ins (Inscription) : L'enregistrement d'inscription ; ses attributs
            ``exemption_40`` et ``exemption_margin`` pilotent le calcul du
            seuil.
        rate (float) : Le taux d'absence non justifiée calculé en pourcentage.
        seuil (int) : Le seuil d'absence de base pour le cours (soit le
            seuil spécifique au cours, soit le seuil système par défaut).

    Retourne :
        str : L'un de ``"BLOQUE"``, ``"SOUS EXEMPTION"`` ou ``"A RISQUE"``.
    """
    # Le seuil effectif est relevé de exemption_margin pour les étudiants exemptés, plafonné à 100 %
    seuil_eff = min(seuil + ins.exemption_margin, 100) if ins.exemption_40 else seuil

    if rate >= seuil_eff:
        # Le taux dépasse même le seuil relevé — l'étudiant est complètement bloqué
        return "BLOQUE"
    if ins.exemption_40:
        # Le taux est inférieur au seuil relevé mais l'indicateur d'exemption est actif
        return "SOUS EXEMPTION"
    # Le taux atteint le seuil de base et aucune exemption ne s'applique
    return "A RISQUE"


@extend_schema(
    summary="Export at-risk students as Excel (admin/secretary)",
    tags=["Exports"],
    responses={(200, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"): bytes},
)
@api_view(["GET"])
@permission_classes([IsAdminOrSecretary])
def export_at_risk_excel_api(request):
    """
    Génère et diffuse un classeur Excel listant tous les étudiants à risque.

    Une paire étudiant-inscription est considérée comme "à risque" lorsque
    son taux d'absence non justifiée (total des heures non justifiées /
    total des périodes du cours * 100) atteint ou dépasse le seuil d'absence
    de base pour son cours. Chaque ligne qualifiante est écrite dans le
    classeur avec un libellé de statut déterminé par ``_export_status``.

    Seules les inscriptions avec une valeur ``nombre_total_periodes``
    positive sont évaluées ; les cours avec zéro période totale sont
    ignorés pour éviter la division par zéro.

    Seules les absences non justifiées des séances qui ont déjà eu lieu
    (``date_seance <= today``) sont incluses dans le calcul du taux,
    conformément à la logique de risque du tableau de bord.

    Le classeur est construit entièrement en mémoire (``io.BytesIO``) et
    diffusé comme une réponse ``Content-Disposition: attachment``.

    Paramètres :
        request (Request) : La requête authentifiée admin ou secrétaire.

    Retourne :
        HttpResponse : Une pièce jointe tableur OOXML (``application/vnd.
            openxmlformats-officedocument.spreadsheetml.sheet``) contenant
            une ligne d'en-tête et une ligne de données par inscription à
            risque.
    """
    # Résout l'année académique active (peut être None)
    academic_year = AnneeAcademique.objects.filter(active=True).first()

    # Récupère le seuil de repli système pour les cours sans surcharge spécifique
    system_threshold = get_system_threshold()

    # Charge toutes les inscriptions actives avec les données d'étudiant et de cours pré-jointes
    all_inscriptions = Inscription.objects.filter(
        status=Inscription.Status.EN_COURS
    ).select_related("id_cours", "id_etudiant")
    if academic_year:
        all_inscriptions = all_inscriptions.filter(id_annee=academic_year)

    inscription_ids = list(all_inscriptions.values_list("id_inscription", flat=True))
    today = timezone.localdate()

    # Agrège les heures non justifiées par inscription en une seule requête
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

    # --- Construit le classeur Excel ---
    wb = Workbook()
    ws = cast(Worksheet, wb.active)
    ws.title = "Etudiants a Risque"

    # Écrit la ligne d'en-tête
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

        # Ignore les cours sans périodes déclarées pour éviter la division par zéro
        if cours.nombre_total_periodes > 0:
            total_abs = float(absence_sums.get(ins.id_inscription, 0) or 0)
            # Calcule le taux d'absence en pourcentage du total des périodes du cours
            rate = (total_abs / cours.nombre_total_periodes) * 100

            # Utilise le seuil spécifique au cours s'il est défini, sinon le seuil système par défaut
            seuil = (
                cours.seuil_absence
                if cours.seuil_absence is not None
                else system_threshold
            )

            # Inclut uniquement les inscriptions qui atteignent ou dépassent le seuil de base
            if rate >= seuil:
                ws.append([
                    excel_safe_cell(ins.id_etudiant.nom),
                    excel_safe_cell(ins.id_etudiant.prenom),
                    excel_safe_cell(ins.id_etudiant.email),
                    excel_safe_cell(f"{cours.nom_cours} ({cours.code_cours})"),
                    total_abs,
                    round(rate, 2),
                    # Détermine le libellé de statut détaillé (BLOQUE / SOUS EXEMPTION / A RISQUE)
                    _export_status(ins, rate, seuil),
                ])

    # Sérialise le classeur en mémoire et le diffuse comme pièce jointe
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    response = HttpResponse(
        buf.read(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = 'attachment; filename="etudiants_a_risque.xlsx"'
    return response
