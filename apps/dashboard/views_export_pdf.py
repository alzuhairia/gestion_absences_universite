"""
Vue d'export PDF pour le tableau de bord administrateur / secrétaire UniAbsences.

Ce module expose une vue unique qui génère un rapport PDF d'absences par étudiant
à l'aide de ReportLab et le diffuse en tant que réponse HTTP ``application/pdf``.

``export_student_pdf``
    Génère un rapport PDF d'absences par étudiant. Le rapport est limité à
    l'année académique active et n'inclut que les absences non justifiées
    survenues à la date du jour ou avant.

    Règles d'accès (appliquées par ``@roles_required`` et vérifications internes) :
        - ``ETUDIANT`` — ne peut exporter que son propre rapport (student_id est
          ignoré et l'utilisateur de la requête est utilisé directement).
        - ``ADMIN`` / ``SECRETAIRE`` — doivent fournir un ``student_id`` en
          paramètre d'URL ou en paramètre de requête ; l'export est enregistré
          dans le journal d'audit.
        - ``PROFESSEUR`` — exclu par ``@roles_required``.

    Le téléchargement PDF en libre-service depuis la page de profil étudiant
    est géré par une vue séparée dans ``accounts.views_profile.download_report_pdf``.

Fait partie du système de tableau de bord UniAbsences.
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
from apps.utils import pdf_check_page_break


@login_required
@roles_required(User.Role.ETUDIANT, User.Role.ADMIN, User.Role.SECRETAIRE)
@require_GET
def export_student_pdf(request, student_id=None):
    """
    Génère et diffuse un rapport PDF d'absences pour un étudiant spécifique.

    Le rapport contient :
        1. Un en-tête avec le nom de l'étudiant, son email, l'année académique
           active et la date de génération du rapport.
        2. Une section de résumé listant le total des heures non justifiées par
           cours auquel l'étudiant est inscrit.
        3. Une section détaillée listant chaque absence non justifiée individuelle
           avec date, code du cours, durée et statut.

    Contrôle d'accès basé sur le rôle
    ---------------------------------
    - Les étudiants sont strictement restreints à leurs propres données ;
      ``student_id`` est ignoré.
    - Les administrateurs et secrétaires doivent fournir un ``student_id`` valide
      (segment d'URL ou paramètre de requête ``?student_id=``). L'action est
      enregistrée dans le journal d'audit.

    Parameters
    ----------
    request : HttpRequest
        Doit être une requête GET émise par un utilisateur authentifié avec un
        rôle autorisé.
    student_id : int or None
        Clé primaire de l'étudiant cible. Requise pour admin/secrétaire ; ignorée
        pour le rôle étudiant.

    Returns
    -------
    HttpResponse
        Une réponse ``application/pdf`` avec ``Content-Disposition: attachment``.

    Raises
    ------
    HttpResponseBadRequest
        Retournée (et non levée) lorsqu'un administrateur ou un secrétaire omet
        ``student_id``.
    Http404
        Lorsque le ``student_id`` fourni ne correspond à aucun étudiant existant.
    """
    # Import différé pour éviter les dépendances circulaires au chargement du module.
    from apps.academic_sessions.models import AnneeAcademique

    # --- Résolution de l'étudiant basée sur le rôle ---

    if request.user.role == User.Role.ETUDIANT:
        # Les étudiants ne peuvent accéder qu'à leur propre rapport — ignorer tout student_id.
        student = request.user
    else:
        # Administrateur ou secrétaire : student_id est obligatoire.
        effective_student_id = student_id or request.GET.get("student_id")
        if not effective_student_id:
            return HttpResponseBadRequest("student_id requis")
        student = get_object_or_404(User, pk=effective_student_id, role=User.Role.ETUDIANT)

    # --- Résolution de l'année académique active (repli sur la plus récente) ---
    academic_year = AnneeAcademique.objects.filter(active=True).first()
    if not academic_year:
        academic_year = AnneeAcademique.objects.order_by("-id_annee").first()

    response = HttpResponse(content_type="application/pdf")

    # Assainir l'email de l'étudiant pour qu'il soit utilisable en toute sécurité
    # dans un nom de fichier d'en-tête Content-Disposition — supprimer tout
    # caractère qui n'est pas alphanumérique, '.', '_', '-', ou '@'.
    safe_email = "".join(c if c.isalnum() or c in "._-@" else "_" for c in student.email)
    response["Content-Disposition"] = (
        f'attachment; filename="rapport_absences_{safe_email}.pdf"'
    )

    # --- Construction du PDF ---
    buffer = io.BytesIO()
    p = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    def _page_break(y, margin=80):
        """
        Délègue à l'utilitaire partagé ``pdf_check_page_break``.

        Démarre une nouvelle page lorsque ``y`` approche de la marge inférieure
        et retourne la nouvelle coordonnée y en haut de la page fraîche.

        Parameters
        ----------
        y : float
            Position de dessin verticale actuelle (points depuis le bas de page).
        margin : int
            Dégagement minimal avant de déclencher un saut de page (défaut 80 pt).

        Returns
        -------
        float
            Position y mise à jour (réinitialisée près du haut si une nouvelle
            page a été démarrée, inchangée sinon).
        """
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

    # Séparateur horizontal sous le bloc d'en-tête.
    p.line(50, height - 160, width - 50, height - 160)
    y_position = height - 180

    # --- Requête d'inscription limitée à l'année académique active ---
    insc_filter = {"id_etudiant": student, "status": Inscription.Status.EN_COURS}
    if academic_year:
        insc_filter["id_annee"] = academic_year
    inscriptions = Inscription.objects.filter(**insc_filter).select_related("id_cours")
    inscription_ids = list(inscriptions.values_list("id_inscription", flat=True))

    today = timezone.localdate()

    # Agréger les heures non justifiées par inscription en une seule requête BD.
    # Les séances futures sont exclues pour ne pas compter les cours non encore tenus.
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

    # --- Section 1 : résumé par cours ---
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
            # Démarrer automatiquement une nouvelle page en approchant la marge inférieure.
            y_position = _page_break(y_position)

    # --- Section 2 : liste détaillée des absences ---
    y_position = _page_break(y_position - 10)
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
            y_position = _page_break(y_position)

    p.showPage()
    p.save()

    buffer.seek(0)
    response.write(buffer.read())

    # --- Journal d'audit ---
    # Ne journaliser que lorsqu'un administrateur ou un secrétaire accède aux
    # données d'un étudiant — les téléchargements par l'étudiant lui-même ne
    # sont pas journalisés ici afin d'éviter le bruit dans le journal d'audit.
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
