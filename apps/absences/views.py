import datetime
import logging
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST, require_http_methods

from apps.absences.models import Absence, Justification, QRAttendanceToken, QRScanLog, QRScanRecord
from apps.absences.services import (
    calculer_absence_stats,
    calculer_pourcentage_absence,
    get_absences_queryset,
    get_justification_deadline,
    is_justification_expired,
)
from apps.absences.utils_upload import (
    UploadValidationError,
    generate_safe_upload_filename,
    validate_uploaded_file,
)
from apps.academic_sessions.models import AnneeAcademique, Seance
from apps.academics.models import Cours
from apps.accounts.models import User
from apps.audits.utils import log_action
from apps.dashboard.decorators import (
    professor_required,
    secretary_required,
    student_required,
)
from apps.enrollments.models import Inscription
from apps.notifications.email import (
    build_absence_recorded_email,
    build_justification_submitted_professor_email,
    send_notification_email,
    send_with_dedup,
)

logger = logging.getLogger(__name__)


@login_required
@student_required
@require_GET
def absence_details(request, id_inscription):
    """
    Affiche les détails des absences pour un étudiant - Lecture seule.
    STRICT: Les étudiants peuvent uniquement consulter leurs absences et soumettre des justificatifs via la vue upload_justification.
    """
    # STRICT: Verify the inscription belongs to the logged-in student
    inscription = get_object_or_404(
        Inscription, id_inscription=id_inscription, id_etudiant=request.user
    )

    # Get all absences for this inscription (optimized queryset)
    absences = get_absences_queryset(inscription)

    # Prepare absence data with justification status
    absences_data = []
    for absence in absences:
        justification = getattr(absence, "justification", None)

        if justification:
            if justification.state == Justification.State.ACCEPTEE:
                status = "JUSTIFIÉE"
                status_color = "success"
            elif justification.state == Justification.State.REFUSEE:
                status = "NON JUSTIFIÉE"
                status_color = "danger"
            else:  # EN_ATTENTE
                status = "EN ATTENTE"
                status_color = "warning"
        else:
            if absence.statut == Absence.Statut.JUSTIFIEE:
                status = "JUSTIFIÉE"
                status_color = "success"
            else:
                status = "NON JUSTIFIÉE"
                status_color = "danger"

        # Determine if the student can submit a justification
        is_refused = justification is not None and justification.state == Justification.State.REFUSEE
        is_not_yet_submitted = justification is None and absence.statut not in (
            Absence.Statut.JUSTIFIEE,
            Absence.Statut.EN_ATTENTE,
        )
        can_submit_status = is_not_yet_submitted or is_refused

        # Deadline check: student can only submit within JUSTIFICATION_DEADLINE_DAYS
        deadline = get_justification_deadline(absence)
        expired = is_justification_expired(absence)
        can_submit = can_submit_status and not expired

        absences_data.append(
            {
                "absence": absence,
                "status": status,
                "status_color": status_color,
                "justification": justification,
                "can_submit": can_submit,
                "deadline": deadline,
                "is_expired": expired and can_submit_status,
            }
        )

    # Get course and professor info
    course = inscription.id_cours
    prof_name = "Non assigné"
    if course.professeur:
        prof_name = course.professeur.get_full_name()

    # Calculate absence statistics (legacy + hours-based)
    stats = calculer_absence_stats(inscription)
    absence_rate = stats["taux"]
    # CORRECTION BUG CRITIQUE #4a — Utiliser le seuil configuré du cours
    seuil = inscription.id_cours.get_seuil_absence()
    seuil_effectif = min(seuil + inscription.exemption_margin, 100) if inscription.exemption_40 else seuil
    is_blocked = absence_rate >= seuil_effectif

    # New hours-based percentage calculation
    pct_stats = calculer_pourcentage_absence(request.user, course)

    return render(
        request,
        "absences/details.html",
        {
            "inscription": inscription,
            "course": course,
            "absences_data": absences_data,
            "prof_name": prof_name,
            "absence_rate": round(absence_rate, 1),
            "is_blocked": is_blocked,
            "is_exempted": inscription.exemption_40,
            "total_heures_cours": pct_stats["total_heures_cours"],
            "total_heures_absence": pct_stats["total_heures_absence"],
            "pourcentage_absence": pct_stats["pourcentage_absence"],
            "pourcentage_presence": pct_stats["pourcentage_presence"],
        },
    )


@login_required
@student_required
@require_http_methods(["GET", "POST"])
def upload_justification(request, absence_id):
    """
    Telechargement de justificatif - STRICT: Uniquement pour les etudiants, uniquement pour les absences NON JUSTIFIEES ou EN ATTENTE.
    """
    absence = get_object_or_404(Absence, id_absence=absence_id)

    # STRICT: Verify the absence belongs to the logged-in student
    if absence.id_inscription.id_etudiant != request.user:
        messages.error(
            request,
            "Acces non autorise. Vous ne pouvez consulter que vos propres absences.",
        )
        return redirect("dashboard:student_dashboard")

    # STRICT: Can only submit justification for UNJUSTIFIED or PENDING absences
    if absence.statut == Absence.Statut.JUSTIFIEE:
        messages.info(
            request,
            "Cette absence est deja justifiee. Vous ne pouvez plus soumettre de justificatif pour cette absence.",
        )
        return redirect(
            "absences:details", id_inscription=absence.id_inscription.id_inscription
        )

    # Retrieve existing justification if any
    justification = Justification.objects.filter(id_absence=absence).first()

    # STRICT: If justification exists and is ACCEPTED, cannot modify
    if justification and justification.state == Justification.State.ACCEPTEE:
        messages.success(
            request,
            "Votre justificatif a ete accepte par le secretariat. Cette absence est maintenant justifiee.",
        )
        return redirect(
            "absences:details", id_inscription=absence.id_inscription.id_inscription
        )

    # STRICT: If justification is EN_ATTENTE, cannot modify (already submitted)
    if justification and justification.state == Justification.State.EN_ATTENTE:
        messages.warning(
            request,
            "Un justificatif a deja ete soumis pour cette absence et est actuellement en cours d'examen par le secretariat. "
            "Vous ne pouvez plus le modifier. Vous serez notifie une fois la decision prise.",
        )
        return redirect(
            "absences:details", id_inscription=absence.id_inscription.id_inscription
        )

    # STRICT: Deadline check — student cannot submit after JUSTIFICATION_DEADLINE_DAYS
    deadline = get_justification_deadline(absence)
    if is_justification_expired(absence):
        messages.error(
            request,
            f"Le delai de justification est depasse. "
            f"Vous aviez jusqu'au {deadline.strftime('%d/%m/%Y')} pour soumettre un justificatif.",
        )
        return redirect(
            "absences:details", id_inscription=absence.id_inscription.id_inscription
        )

    if request.method == "POST":
        file = request.FILES.get("document")
        if not file:
            messages.error(
                request,
                "Aucun fichier n'a ete recu. Veuillez selectionner un PDF, JPG ou PNG.",
            )
            return redirect("absences:upload", absence_id=absence_id)

        comment = request.POST.get("comment", "")

        try:
            meta = validate_uploaded_file(file)
            file.name = generate_safe_upload_filename(meta["extension"])
        except UploadValidationError as exc:
            messages.error(request, " ".join(exc.messages))
            return redirect("absences:upload", absence_id=absence_id)

        # Create or update justification
        new_justification = None
        with transaction.atomic():
            if justification and justification.state == Justification.State.REFUSEE:
                # Resubmit if previous was refused - update existing justification
                justification.document = file
                justification.commentaire = comment
                justification.state = Justification.State.EN_ATTENTE
                justification.validee_par = None
                justification.date_validation = None
                justification.save()
                new_justification = justification
            elif not justification:
                # Create new justification
                new_justification = Justification.objects.create(
                    id_absence=absence,
                    document=file,
                    commentaire=comment,
                    state=Justification.State.EN_ATTENTE,
                )
            else:
                # Should not happen due to checks above, but handle gracefully
                messages.error(
                    request,
                    "Impossible de soumettre le justificatif dans l'etat actuel.",
                )
                return redirect("absences:upload", absence_id=absence_id)

            # Update absence status to EN_ATTENTE (for display purposes)
            absence.statut = Absence.Statut.EN_ATTENTE
            absence.save()

        # Audit logging
        if new_justification:
            log_action(
                request.user,
                f"Etudiant a soumis une justification pour l'absence {absence.id_absence} - {absence.id_seance.id_cours.code_cours}",
                request,
                niveau="INFO",
                objet_type="JUSTIFICATION",
                objet_id=new_justification.id_justification,
            )

            # Email to professor (outside transaction — failure must not block)
            professor = absence.id_seance.id_cours.professeur
            if professor:
                subj, body, html_body = build_justification_submitted_professor_email(
                    professor,
                    request.user,
                    absence.id_seance.id_cours.code_cours,
                    str(absence.id_seance.date_seance),
                )
                send_notification_email(professor, subj, body, html_body)

        messages.success(
            request,
            "Votre justificatif a été envoyé et est en attente de validation par le secrétariat. "
            "Vous serez notifié une fois la décision prise.",
        )
        return redirect(
            "absences:details", id_inscription=absence.id_inscription.id_inscription
        )

    return render(
        request,
        "absences/justify.html",
        {"absence": absence, "justification": justification, "deadline": deadline},
    )


@login_required
@secretary_required
@require_http_methods(["GET", "POST"])
def review_justification(request, absence_id):
    """
    Review absence details and justification (if any).
    Handles both absences with and without a submitted justification.
    """
    absence = get_object_or_404(
        Absence.objects.select_related(
            "id_inscription__id_etudiant",
            "id_seance__id_cours",
        ),
        id_absence=absence_id,
    )
    justification = Justification.objects.filter(id_absence=absence).first()

    if request.method == "POST" and justification:
        if justification.state != Justification.State.EN_ATTENTE:
            messages.warning(
                request,
                "Le commentaire ne peut plus etre modifie apres validation ou refus.",
            )
            return redirect("absences:review_justification", absence_id=absence_id)
        new_comment = request.POST.get("commentaire_gestion")
        justification.commentaire_gestion = new_comment
        justification.save()
        messages.success(request, "Commentaire mis a jour.")
        return redirect("absences:review_justification", absence_id=absence_id)

    # Document link (only if justification with document exists)
    document_url = None
    document_name = None
    if justification and justification.document:
        document_url = reverse(
            "absences:download_justification", args=[justification.id_justification]
        )
        suffix = Path(justification.document.name).suffix
        document_name = (
            f"justificatif_{absence.id_absence}{suffix}"
            if suffix
            else f"justificatif_{absence.id_absence}"
        )

    is_secretary = request.user.role == User.Role.SECRETAIRE

    return render(
        request,
        "absences/review_justification.html",
        {
            "absence": absence,
            "justification": justification,
            "document_url": document_url,
            "document_name": document_name,
            "is_secretary": is_secretary,
        },
    )


@login_required
@require_GET
def download_justification(request, justification_id):
    """
    Telecharger un justificatif avec controle d'acces.
    - Secretaire/Admin: acces autorise
    - Etudiant: seulement ses propres justificatifs
    - Professeur: refuse
    """
    justification = get_object_or_404(Justification, id_justification=justification_id)
    absence = justification.id_absence

    if request.user.role in [User.Role.SECRETAIRE, User.Role.ADMIN]:
        pass
    elif request.user.role == User.Role.ETUDIANT:
        if absence.id_inscription.id_etudiant != request.user:
            raise PermissionDenied("Acces non autorise")
    else:
        raise PermissionDenied("Acces non autorise")

    if not justification.document or not justification.document.name:
        raise Http404("Aucun document")

    try:
        justification.document.open("rb")
    except FileNotFoundError as exc:
        raise Http404(
            "Le fichier justificatif est introuvable sur le serveur."
        ) from exc
    except OSError as exc:
        raise Http404("Impossible d'ouvrir le fichier justificatif.") from exc

    return FileResponse(
        justification.document,
        as_attachment=True,
        filename=Path(justification.document.name).name,
    )


@login_required
@professor_required
@require_http_methods(["GET", "POST"])
def session_create(request, course_id):
    """
    Unified entry point: professor creates a séance first, then chooses
    attendance mode (manual or QR).  The Seance is created upfront so
    that both modes start from a known, persisted session.
    """
    course = get_object_or_404(Cours, id_cours=course_id)
    if course.professeur_id != request.user.pk:
        messages.error(request, "Accès non autorisé à ce cours.")
        return redirect("dashboard:instructor_dashboard")

    academic_year = AnneeAcademique.objects.filter(active=True).first()
    if not academic_year:
        messages.error(request, "Aucune année académique active.")
        return redirect("dashboard:instructor_course_detail", course_id)

    if request.method == "POST":
        date_seance = request.POST.get("date_seance", "").strip()
        heure_debut = request.POST.get("heure_debut", "").strip()
        heure_fin = request.POST.get("heure_fin", "").strip()
        mode = request.POST.get("mode", "manual")

        # --- Validation ---
        if not all([date_seance, heure_debut, heure_fin]):
            messages.error(request, "Veuillez remplir tous les champs obligatoires.")
            return redirect("absences:session_create", course_id=course_id)

        try:
            fmt = "%H:%M"
            t_debut = datetime.datetime.strptime(heure_debut, fmt)
            t_fin = datetime.datetime.strptime(heure_fin, fmt)
        except (TypeError, ValueError):
            messages.error(request, "Format d'heure invalide (HH:MM attendu).")
            return redirect("absences:session_create", course_id=course_id)

        if t_fin <= t_debut:
            messages.error(request, "L'heure de fin doit être postérieure à l'heure de début.")
            return redirect("absences:session_create", course_id=course_id)

        # --- Create or retrieve seance (unique par cours + date) ---
        try:
            seance = Seance.objects.get(id_cours=course, date_seance=date_seance)
            updated_fields = []
            if seance.heure_debut != t_debut.time():
                seance.heure_debut = heure_debut
                updated_fields.append("heure_debut")
            if seance.heure_fin != t_fin.time():
                seance.heure_fin = heure_fin
                updated_fields.append("heure_fin")
            if updated_fields:
                seance.save(update_fields=updated_fields)
            messages.info(request, "Séance existante récupérée.")
            created = False
        except Seance.DoesNotExist:
            seance = Seance.objects.create(
                id_cours=course,
                date_seance=date_seance,
                heure_debut=heure_debut,
                heure_fin=heure_fin,
                id_annee=academic_year,
            )
            created = True

        if seance.validated:
            messages.error(request, "Cette séance est déjà validée et verrouillée.")
            return redirect("dashboard:instructor_course_detail", course_id)

        # --- Redirect based on mode ---
        if mode == "qr":
            # Create QR token and redirect to dashboard
            from apps.dashboard.models import SystemSettings
            sys_settings = SystemSettings.get_settings()
            qr_duration_seconds = sys_settings.qr_token_duration_seconds

            verify_location = request.POST.get("verify_location") == "on"

            QRAttendanceToken.objects.filter(seance=seance, is_active=True).update(is_active=False)

            token_kwargs = {
                "seance": seance,
                "created_by": request.user,
                "expires_at": timezone.now() + timedelta(seconds=qr_duration_seconds),
                "verify_location": verify_location,
            }
            try:
                lat = request.POST.get("latitude")
                lng = request.POST.get("longitude")
                if lat and lng:
                    token_kwargs["latitude"] = float(lat)
                    token_kwargs["longitude"] = float(lng)
            except (ValueError, TypeError):
                pass

            new_token = QRAttendanceToken.objects.create(**token_kwargs)

            log_action(
                request.user,
                f"Séance créée (QR) — {course.code_cours} {date_seance}",
                request,
                niveau="INFO",
                objet_type="SEANCE",
                objet_id=seance.id_seance,
            )
            return redirect("absences:qr_dashboard", token=new_token.token)
        else:
            # Manual mode → redirect to mark_absence with date pre-filled
            log_action(
                request.user,
                f"Séance créée (manuel) — {course.code_cours} {date_seance}",
                request,
                niveau="INFO",
                objet_type="SEANCE",
                objet_id=seance.id_seance,
            )
            return redirect(
                f"{reverse('absences:mark_absence', args=[course_id])}?date={date_seance}"
            )

    # --- GET: render creation form ---
    today = timezone.localdate().isoformat()
    return render(request, "absences/session_create.html", {
        "course": course,
        "today": today,
        "default_start": "08:30",
        "default_end": "10:30",
    })


@login_required
@professor_required
@require_http_methods(["GET", "POST"])
def mark_absence(request, course_id):
    """
    Vue pour qu'un professeur puisse noter les absences d'une séance.

    IMPORTANT POUR LA SOUTENANCE :
    Cette fonction implémente la saisie des présences/absences par le professeur.

    Logique métier :
    1. Vérification que le cours appartient au professeur (sécurité)
    2. Création ou récupération de la séance
    3. Pour chaque étudiant inscrit :
       - Marquer comme PRÉSENT, ABSENT, ou ABSENT JUSTIFIÉ
       - Si absent, définir le type (séance complète, retard/partiel, journée)
       - Calculer la durée de l'absence

    RÈGLE CRITIQUE - PROTECTION DES ABSENCES JUSTIFIÉES :
    - Les absences encodées par le secrétariat (statut JUSTIFIEE) sont PROTÉGÉES
    - Le professeur peut les VOIR mais ne peut PAS les modifier
    - Cette règle garantit l'intégrité des absences officielles

    SÉCURITÉ :
    - @professor_required : seul un professeur peut accéder
    - Vérification supplémentaire : course.professeur == request.user
    - Double vérification pour garantir que le professeur ne peut accéder qu'à ses cours

    Args:
        request: Objet HttpRequest contenant les données du formulaire
        course_id: ID du cours pour lequel faire l'appel

    Returns:
        HttpResponse avec le formulaire ou redirection après sauvegarde
    """
    # ============================================
    # VÉRIFICATION DE SÉCURITÉ
    # ============================================
    # IMPORTANT : Double vérification (décorateur + vérification de propriété)
    # Un professeur ne peut accéder qu'à SES propres cours

    course = get_object_or_404(Cours, id_cours=course_id)
    if course.professeur != request.user:
        messages.error(request, "Accès non autorisé à ce cours.")
        return redirect("dashboard:instructor_dashboard")

    # Filter by active year and EN_COURS status to exclude past/inactive students
    active_year = AnneeAcademique.objects.filter(active=True).first()
    inscriptions_qs = Inscription.objects.filter(
        id_cours=course, status=Inscription.Status.EN_COURS
    ).select_related("id_etudiant")
    if active_year:
        inscriptions_qs = inscriptions_qs.filter(id_annee=active_year)
    inscriptions_by_id = {str(ins.id_inscription): ins for ins in inscriptions_qs}

    if request.method == "POST":
        # Block if this is a validated session
        check_date = request.POST.get("date_seance", "").strip()
        if check_date:
            validated_seance = Seance.objects.filter(
                id_cours=course, date_seance=check_date, validated=True
            ).first()
            if validated_seance:
                messages.error(
                    request,
                    "Cette séance a déjà été validée. Vous ne pouvez plus modifier les présences.",
                )
                return redirect("absences:mark_absence", course_id=course_id)

        # Verifier que les inscriptions envoyees appartiennent au cours
        invalid_ids = []
        for key in request.POST.keys():
            if key.startswith("status_"):
                raw_id = key.split("_", 1)[1]
                if raw_id not in inscriptions_by_id:
                    invalid_ids.append(raw_id)

        if invalid_ids:
            log_action(
                request.user,
                f"Tentative d'acces a des inscriptions non autorisees: {', '.join(invalid_ids)}",
                request,
                niveau="WARNING",
                objet_type="INSCRIPTION",
                objet_id=None,
            )
            raise PermissionDenied(
                "Acces non autorise a une ou plusieurs inscriptions."
            )

        # ============================================================
        # CORRECTION BUG CRITIQUE #1 — VALIDATION AVANT TOUTE OPÉRATION DB
        # Avant cette correction : Seance.objects.get_or_create() s'exécutait
        # AVANT la validation des champs. Un return à l'intérieur d'un bloc
        # transaction.atomic() committe la transaction → des séances "fantômes"
        # avec des données invalides pouvaient être persistées en base de données.
        # Correction : toute validation est effectuée AVANT d'entrer dans atomic().
        # ============================================================
        date_seance = request.POST.get("date_seance", "").strip()
        heure_debut = request.POST.get("heure_debut", "").strip()
        heure_fin = request.POST.get("heure_fin", "").strip()

        if not date_seance or not heure_debut or not heure_fin:
            messages.error(
                request,
                "Date et horaires de séance invalides. Veuillez vérifier les champs saisis.",
            )
            return redirect("absences:mark_absence", course_id=course_id)

        try:
            fmt = "%H:%M"
            t_debut = datetime.datetime.strptime(heure_debut, fmt)
            t_fin = datetime.datetime.strptime(heure_fin, fmt)
        except (TypeError, ValueError):
            messages.error(
                request, "Format d'heure invalide. Veuillez utiliser le format HH:MM."
            )
            return redirect("absences:mark_absence", course_id=course_id)

        if t_fin <= t_debut:
            messages.error(
                request,
                "L'heure de fin doit être strictement postérieure à l'heure de début.",
            )
            return redirect("absences:mark_absence", course_id=course_id)

        # Durée calculée une seule fois, avant le bloc transactionnel
        duree_seance = Decimal((t_fin - t_debut).seconds) / Decimal(3600)
        duree_seance = duree_seance.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        # Vérification de l'année active AVANT la transaction
        annee = AnneeAcademique.objects.filter(active=True).first()
        if not annee:
            messages.error(
                request,
                "Aucune année académique active. Veuillez contacter le secrétariat.",
            )
            return redirect("absences:mark_absence", course_id=course_id)

        with transaction.atomic():
            # --- OPÉRATIONS DB (données validées, aucun risque de séance fantôme) ---
            # Unique par cours + date — .get() crashe si doublon (fail fast)
            try:
                seance = Seance.objects.get(date_seance=date_seance, id_cours=course)
                # Mettre à jour les heures si le prof les a modifiées
                updated_fields = []
                if seance.heure_debut != heure_debut:
                    seance.heure_debut = heure_debut
                    updated_fields.append("heure_debut")
                if seance.heure_fin != heure_fin:
                    seance.heure_fin = heure_fin
                    updated_fields.append("heure_fin")
                if updated_fields:
                    seance.save(update_fields=updated_fields)
                messages.info(
                    request,
                    "Une séance existe déjà pour cette date. Les absences seront mises à jour pour cette séance existante.",
                )
            except Seance.DoesNotExist:
                seance = Seance.objects.create(
                    date_seance=date_seance,
                    heure_debut=heure_debut,
                    heure_fin=heure_fin,
                    id_cours=course,
                    id_annee=annee,
                )

            # Traitement des etudiants
            # On itere sur les cles POST qui commencent par 'status_'
            # Format attendu : status_{inscription_id}
            for key, value in request.POST.items():
                if not key.startswith("status_"):
                    continue

                inscription_id = key.split("_", 1)[1]
                status = value  # 'PRESENT' ou 'ABSENT'
                inscription = inscriptions_by_id.get(inscription_id)
                if not inscription:
                    # Should not happen thanks to the upfront validation
                    continue

                # ============================================
                # PROTECTION DES ABSENCES JUSTIFIEES
                # ============================================
                # REGLE METIER CRITIQUE :
                # Les absences encodees par le secretariat (statut JUSTIFIEE) sont OFFICIELLES
                # Le professeur peut les CONSULTER mais ne peut PAS les modifier
                # Cela garantit l'integrite des donnees et la hierarchie des roles

                existing_absence = Absence.objects.filter(
                    id_inscription=inscription, id_seance=seance
                ).first()
                is_prof = request.user.role == User.Role.PROFESSEUR

                if status == "ABSENT":
                    # CORRECTION FIX ORANGE #8 — Protection correctement ciblée
                    # AVANT : deux checks erronés :
                    #   1. "if is_prof and existing_absence: continue" → trop large, bloquait
                    #      même la correction d'une erreur de saisie NON_JUSTIFIEE.
                    #   2. "if is_prof and ... JUSTIFIEE: continue" → code mort (jamais atteint).
                    # APRÈS : la protection JUSTIFIEE est gérée ligne ~584 pour TOUS les rôles.
                    #         Un professeur peut corriger ses propres absences NON_JUSTIFIEE.

                    _ALLOWED_TYPES = {Absence.TypeAbsence.ABSENT, Absence.TypeAbsence.PARTIEL}
                    type_absence = request.POST.get(f"type_{inscription_id}", Absence.TypeAbsence.ABSENT)
                    if type_absence not in _ALLOWED_TYPES:
                        logger.warning(
                            "Type d'absence invalide recu (%s) pour inscription %s. Fallback ABSENT.",
                            type_absence,
                            inscription_id,
                        )
                        type_absence = Absence.TypeAbsence.ABSENT

                    # Determiner la duree
                    duree = duree_seance  # Default for ABSENT (= full session)
                    if type_absence == Absence.TypeAbsence.PARTIEL:
                        try:
                            duree = Decimal(
                                str(float(request.POST.get(f"duree_{inscription_id}", 0)))
                            ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                            if duree <= 0 or duree > duree_seance:
                                raise ValueError("invalid duration range")
                        except (TypeError, ValueError):
                            logger.warning(
                                "Duree d'absence invalide pour inscription %s. Utilisation de la duree de seance.",
                                inscription_id,
                            )
                            duree = duree_seance
                            student_name = inscription.id_etudiant.get_full_name()
                            messages.warning(
                                request,
                                f"Durée invalide pour {student_name} — absence complète ({duree_seance}h) "
                                f"appliquée par défaut. Corrigez si nécessaire.",
                            )

                    # Creation ou Mise a jour Absence (only if not validated/pending)
                    if existing_absence and existing_absence.statut in (Absence.Statut.JUSTIFIEE, Absence.Statut.EN_ATTENTE):
                        # Skip validated or pending absences - professors cannot modify them
                        continue

                    note = request.POST.get(
                        f"note_{inscription_id}", ""
                    ).strip()[:500]

                    absence, created = Absence.objects.update_or_create(
                        id_inscription=inscription,
                        id_seance=seance,
                        defaults={
                            "type_absence": type_absence,
                            "duree_absence": duree,
                            "statut": Absence.Statut.NON_JUSTIFIEE,
                            "encodee_par": request.user,
                            "note_professeur": note,
                        },
                    )

                    # Audit logging for professor actions
                    if is_prof:
                        action_desc = (
                            f"Professeur a enregistre une absence pour "
                            f"{inscription.id_etudiant.get_full_name()} - {course.code_cours} le {date_seance}"
                        )
                        log_action(
                            request.user,
                            action_desc,
                            request,
                            niveau="INFO",
                            objet_type="ABSENCE",
                            objet_id=absence.id_absence,
                        )

                    # Email notification to student (with dedup to avoid spam)
                    if created:
                        from apps.absences.services import calculer_absence_stats

                        stats = calculer_absence_stats(inscription)
                        student = inscription.id_etudiant
                        subj, body, html_body = build_absence_recorded_email(
                            student, course.nom_cours, date_seance, stats["taux"]
                        )
                        event_key = f"{inscription.id_inscription}-{seance.id_seance}"
                        send_with_dedup(
                            student, subj, body, html_body,
                            event_type="absence_recorded",
                            event_key=event_key,
                        )
                else:
                    # Si marque PRESENT, on supprime une eventuelle absence existante pour cette seance
                    if existing_absence:
                        # PROTECTION: JUSTIFIEE and EN_ATTENTE absences cannot be deleted
                        if existing_absence.statut in (Absence.Statut.JUSTIFIEE, Absence.Statut.EN_ATTENTE):
                            continue
                        # Professors can correct their own NON_JUSTIFIEE absences
                        # (e.g., marked absent by mistake, now correcting to present)
                        existing_absence.delete()

            # Audit logging for session creation/attendance
            if request.user.role == User.Role.PROFESSEUR:
                if created:
                    log_action(
                        request.user,
                        f"Professeur a créé une séance pour {course.code_cours} le {date_seance}",
                        request,
                        niveau="INFO",
                        objet_type="SEANCE",
                        objet_id=(
                            seance.id_seance if hasattr(seance, "id_seance") else None
                        ),
                    )
                log_action(
                    request.user,
                    f"Professeur a enregistré la présence pour {course.code_cours} le {date_seance}",
                    request,
                    niveau="INFO",
                    objet_type="SEANCE",
                    objet_id=seance.id_seance if hasattr(seance, "id_seance") else None,
                )

            # --- Validate or Draft? ---
            post_action = request.POST.get("form_action", "draft")

            if post_action == "validate":
                # Save + lock in one step
                seance.validated = True
                seance.validated_by = request.user
                seance.date_validated = timezone.now()
                seance.save(update_fields=["validated", "validated_by", "date_validated"])

                log_action(
                    request.user,
                    f"Professeur a validé la séance du {date_seance} pour {course.code_cours}",
                    request,
                    niveau="INFO",
                    objet_type="SEANCE",
                    objet_id=seance.id_seance,
                )

                messages.success(
                    request,
                    f"L'appel du {date_seance} a été validé et verrouillé. "
                    "La séance ne peut plus être modifiée.",
                )
            else:
                messages.success(
                    request,
                    f"Brouillon enregistré pour la séance du {date_seance}. "
                    "Vous pourrez le modifier et le valider ultérieurement.",
                )

            return redirect(
                f"{reverse('absences:mark_absence', args=[course_id])}?date={date_seance}"
            )

    # --- AFFICHAGE DU FORMULAIRE (GET) ---
    students = inscriptions_qs.order_by("id_etudiant__nom")

    # Check for date in GET (from dashboard link)
    from datetime import date as date_type
    today = request.GET.get("date", "")
    try:
        date_type.fromisoformat(today)
    except (ValueError, TypeError):
        today = timezone.now().strftime("%Y-%m-%d")
    default_start = "08:30"
    default_end = "10:30"

    try:
        existing_seance = Seance.objects.get(id_cours=course, date_seance=today)
    except Seance.DoesNotExist:
        existing_seance = None

    existing_absences = {}
    is_edit_mode = False
    is_validated = False

    if existing_seance:
        is_edit_mode = True
        is_validated = existing_seance.validated
        if existing_seance.heure_debut:
            default_start = existing_seance.heure_debut.strftime("%H:%M")
        if existing_seance.heure_fin:
            default_end = existing_seance.heure_fin.strftime("%H:%M")

        abs_list = Absence.objects.filter(id_seance=existing_seance).select_related("encodee_par")
        for ab in abs_list:
            # ab.id_inscription_id is the raw FK int — no extra query per row
            existing_absences[ab.id_inscription_id] = {
                "type": ab.type_absence,
                "duree": ab.duree_absence,
                "statut": ab.statut,
                "note_professeur": ab.note_professeur,
                "encodee_par": ab.encodee_par,
            }

    # Attach absence data to students for template usage
    for ins in students:
        ins.absence_data = existing_absences.get(ins.id_inscription)

    # Recap counts for post-submission summary
    recap_absent_count = len(existing_absences)
    recap_present_count = len(students) - recap_absent_count

    return render(
        request,
        "absences/mark_absence.html",
        {
            "course": course,
            "students": students,
            "today": today,
            "default_start": default_start,
            "default_end": default_end,
            "is_edit_mode": is_edit_mode,
            "is_validated": is_validated,
            "existing_seance": existing_seance,
            "recap_present_count": recap_present_count,
            "recap_absent_count": recap_absent_count,
        },
    )


@login_required
@professor_required
@require_POST
def mark_absence_htmx(request, course_id):
    """
    HTMX endpoint — update a single student's attendance status without full page reload.
    Returns the updated <tr> partial for the student row.
    """
    course = get_object_or_404(Cours, id_cours=course_id)
    if course.professeur != request.user:
        return HttpResponse("Accès non autorisé.", status=403)

    inscription_id = request.POST.get("inscription_id", "")
    status = request.POST.get("status", "")

    active_year = AnneeAcademique.objects.filter(active=True).first()
    ins_qs = Inscription.objects.filter(
        id_inscription=inscription_id,
        id_cours=course,
        status=Inscription.Status.EN_COURS,
    ).select_related("id_etudiant", "id_cours")
    if active_year:
        ins_qs = ins_qs.filter(id_annee=active_year)
    inscription = ins_qs.first()

    if not inscription:
        return HttpResponse("Inscription introuvable.", status=404)

    # Validate session fields
    date_seance = request.POST.get("date_seance", "").strip()
    heure_debut = request.POST.get("heure_debut", "").strip()
    heure_fin = request.POST.get("heure_fin", "").strip()

    if not date_seance or not heure_debut or not heure_fin:
        return HttpResponse("Date et horaires requis.", status=400)

    try:
        fmt = "%H:%M"
        t_debut = datetime.datetime.strptime(heure_debut, fmt)
        t_fin = datetime.datetime.strptime(heure_fin, fmt)
    except (TypeError, ValueError):
        return HttpResponse("Format d'heure invalide.", status=400)

    if t_fin <= t_debut:
        return HttpResponse("L'heure de fin doit être après l'heure de début.", status=400)

    duree_seance = Decimal((t_fin - t_debut).seconds) / Decimal(3600)
    duree_seance = duree_seance.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    annee = active_year
    if not annee:
        return HttpResponse("Aucune année académique active.", status=400)

    with transaction.atomic():
        # Unique par cours + date — .get() crashe si doublon (fail fast)
        try:
            seance = Seance.objects.get(date_seance=date_seance, id_cours=course)
            updated_fields = []
            if seance.heure_debut != heure_debut:
                seance.heure_debut = heure_debut
                updated_fields.append("heure_debut")
            if seance.heure_fin != heure_fin:
                seance.heure_fin = heure_fin
                updated_fields.append("heure_fin")
            if updated_fields:
                seance.save(update_fields=updated_fields)
        except Seance.DoesNotExist:
            seance = Seance.objects.create(
                date_seance=date_seance,
                heure_debut=heure_debut,
                heure_fin=heure_fin,
                id_cours=course,
                id_annee=annee,
            )

        if seance.validated:
            return HttpResponse("Séance déjà validée.", status=403)

        existing_absence = Absence.objects.filter(
            id_inscription=inscription, id_seance=seance
        ).first()

        if status == "ABSENT":
            # Protected absences
            if existing_absence and existing_absence.statut in (
                Absence.Statut.JUSTIFIEE, Absence.Statut.EN_ATTENTE
            ):
                pass  # Skip, don't modify
            else:
                _ALLOWED_TYPES_HTMX = {Absence.TypeAbsence.ABSENT, Absence.TypeAbsence.PARTIEL}
                type_absence = request.POST.get(
                    f"type_{inscription_id}", Absence.TypeAbsence.ABSENT
                )
                if type_absence not in _ALLOWED_TYPES_HTMX:
                    type_absence = Absence.TypeAbsence.ABSENT

                duree = duree_seance
                if type_absence == Absence.TypeAbsence.PARTIEL:
                    try:
                        duree = Decimal(
                            str(float(request.POST.get(f"duree_{inscription_id}", 0)))
                        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                        if duree <= 0 or duree > duree_seance:
                            raise ValueError
                    except (TypeError, ValueError):
                        logger.warning(
                            "HTMX: Duree d'absence invalide pour inscription %s. Fallback duree_seance.",
                            inscription_id,
                        )
                        duree = duree_seance

                note = request.POST.get(
                    f"note_{inscription_id}", ""
                ).strip()[:500]

                Absence.objects.update_or_create(
                    id_inscription=inscription,
                    id_seance=seance,
                    defaults={
                        "type_absence": type_absence,
                        "duree_absence": duree,
                        "statut": Absence.Statut.NON_JUSTIFIEE,
                        "encodee_par": request.user,
                        "note_professeur": note,
                    },
                )

        elif status == "PRESENT":
            if existing_absence:
                if existing_absence.statut in (
                    Absence.Statut.JUSTIFIEE, Absence.Statut.EN_ATTENTE
                ):
                    pass  # Protected
                else:
                    existing_absence.delete()

    # Re-fetch absence data for the partial render
    absence = Absence.objects.select_related(
        "id_inscription__id_etudiant", "id_seance"
    ).filter(
        id_inscription=inscription, id_seance=seance
    ).first()
    if absence:
        inscription.absence_data = {
            "type": absence.type_absence,
            "duree": absence.duree_absence,
            "statut": absence.statut,
            "note_professeur": absence.note_professeur,
            "encodee_par": absence.encodee_par,
        }
    else:
        inscription.absence_data = None

    return render(
        request,
        "absences/_student_row.html",
        {
            "ins": inscription,
            "is_validated": False,
            "course": course,
            "seance_id": seance.id_seance,
        },
    )


@login_required
@professor_required
@require_POST
def validate_session(request, seance_id):
    """
    Valide une séance — verrouille la présence.
    Après validation, le professeur ne peut plus modifier les absences de cette séance.
    """
    seance = get_object_or_404(Seance, pk=seance_id)

    # Vérifier que le cours appartient au professeur
    if seance.id_cours.professeur != request.user:
        messages.error(request, "Accès non autorisé à cette séance.")
        return redirect("dashboard:instructor_dashboard")

    if seance.validated:
        messages.info(request, "Cette séance est déjà validée.")
        return redirect("absences:mark_absence", course_id=seance.id_cours_id)

    with transaction.atomic():
        seance.validated = True
        seance.validated_by = request.user
        seance.date_validated = timezone.now()
        seance.save(update_fields=["validated", "validated_by", "date_validated"])

        log_action(
            request.user,
            f"Professeur a validé la séance du {seance.date_seance} pour {seance.id_cours.code_cours}",
            request,
            niveau="INFO",
            objet_type="SEANCE",
            objet_id=seance.id_seance,
        )

    messages.success(
        request,
        f"La séance du {seance.date_seance} a été validée. Les présences sont maintenant verrouillées.",
    )
    return redirect("absences:mark_absence", course_id=seance.id_cours_id)


# =====================================================================
# QR Code Attendance
# =====================================================================

import base64
import io
import math

import qrcode

from apps.audits.utils import get_client_ip


def _haversine(lat1, lon1, lat2, lon2):
    """Return distance in metres between two GPS points (Haversine formula)."""
    R = 6_371_000  # Earth radius in metres
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _generate_qr_data_uri(url):
    """Generate a QR code PNG as a base64 data-URI (no file storage needed)."""
    qr = qrcode.QRCode(version=1, box_size=10, border=4)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return f"data:image/png;base64,{base64.b64encode(buf.getvalue()).decode()}"


@login_required
@professor_required
@require_http_methods(["GET", "POST"])
def qr_generate(request, course_id):
    """Professor creates a session and generates a QR code for student scanning."""
    course = get_object_or_404(Cours, id_cours=course_id)
    if course.professeur_id != request.user.pk:
        messages.error(request, "Accès non autorisé à ce cours.")
        return redirect("dashboard:instructor_dashboard")

    academic_year = AnneeAcademique.objects.filter(active=True).first()
    if not academic_year:
        messages.error(request, "Aucune année académique active.")
        return redirect("dashboard:instructor_course_detail", course_id)

    if request.method == "POST":
        date_seance = request.POST.get("date_seance")
        heure_debut = request.POST.get("heure_debut")
        heure_fin = request.POST.get("heure_fin")

        if not all([date_seance, heure_debut, heure_fin]):
            messages.error(request, "Veuillez remplir tous les champs.")
            return redirect("absences:qr_generate", course_id=course_id)

        # Unique par cours + date — .get() crashe si doublon (fail fast)
        try:
            seance = Seance.objects.get(id_cours=course, date_seance=date_seance)
            updated_fields = []
            if str(seance.heure_debut)[:5] != heure_debut:
                seance.heure_debut = heure_debut
                updated_fields.append("heure_debut")
            if str(seance.heure_fin)[:5] != heure_fin:
                seance.heure_fin = heure_fin
                updated_fields.append("heure_fin")
            if updated_fields:
                seance.save(update_fields=updated_fields)
        except Seance.DoesNotExist:
            seance = Seance.objects.create(
                id_cours=course,
                date_seance=date_seance,
                heure_debut=heure_debut,
                heure_fin=heure_fin,
                id_annee=academic_year,
            )

        if seance.validated:
            messages.error(request, "Cette séance est déjà validée et verrouillée.")
            return redirect("dashboard:instructor_course_detail", course_id)

        # GPS anti-fraud: professor's location (optional, sent by JS)
        prof_lat = request.POST.get("latitude")
        prof_lng = request.POST.get("longitude")
        verify_location = request.POST.get("verify_location") == "on"

        # Use system-configured QR duration if available
        from apps.dashboard.models import SystemSettings
        sys_settings = SystemSettings.get_settings()
        qr_duration_seconds = sys_settings.qr_token_duration_seconds

        # Deactivate any previous active tokens for this seance
        QRAttendanceToken.objects.filter(seance=seance, is_active=True).update(is_active=False)

        token_kwargs = {
            "seance": seance,
            "created_by": request.user,
            "expires_at": timezone.now() + timedelta(seconds=qr_duration_seconds),
            "verify_location": verify_location,
        }
        try:
            if prof_lat and prof_lng:
                token_kwargs["latitude"] = float(prof_lat)
                token_kwargs["longitude"] = float(prof_lng)
        except (ValueError, TypeError):
            pass  # GPS optional — skip silently

        token = QRAttendanceToken.objects.create(**token_kwargs)

        log_action(
            request.user,
            f"QR généré pour {course.code_cours} — séance {date_seance}",
            request,
            niveau="INFO",
            objet_type="SEANCE",
            objet_id=seance.id_seance,
        )

        return redirect("absences:qr_dashboard", token=token.token)

    today = timezone.localdate().isoformat()
    return render(request, "absences/qr_generate.html", {
        "course": course,
        "today": today,
        "default_start": "08:00",
        "default_end": "09:30",
    })


@login_required
@professor_required
@require_GET
def qr_dashboard(request, token):
    """Live dashboard: QR image + real-time scan list (HTMX polling)."""
    qr_token = get_object_or_404(QRAttendanceToken, token=token)
    seance = qr_token.seance
    course = seance.id_cours

    if course.professeur_id != request.user.pk:
        messages.error(request, "Accès non autorisé.")
        return redirect("dashboard:instructor_dashboard")

    scan_url = request.build_absolute_uri(
        reverse("absences:qr_scan", kwargs={"token": str(token)})
    )
    qr_data_uri = _generate_qr_data_uri(scan_url)

    inscriptions = list(
        Inscription.objects.filter(
            id_cours=course,
            id_annee=seance.id_annee,
            status=Inscription.Status.EN_COURS,
        ).select_related("id_etudiant")
    )

    scan_records = {
        sr.inscription_id: sr
        for sr in QRScanRecord.objects.filter(seance=seance).select_related("inscription")
    }
    scanned_ids = set(scan_records.keys())

    scanned = []
    suspicious_count = 0
    for ins in inscriptions:
        if ins.id_inscription in scanned_ids:
            sr = scan_records[ins.id_inscription]
            ins.scan_record = sr
            if sr.is_suspicious:
                suspicious_count += 1
            scanned.append(ins)
    not_scanned = [ins for ins in inscriptions if ins.id_inscription not in scanned_ids]

    from apps.dashboard.models import SystemSettings
    sys_settings = SystemSettings.get_settings()

    ctx = {
        "qr_token": qr_token,
        "seance": seance,
        "course": course,
        "qr_data_uri": qr_data_uri,
        "scan_url": scan_url,
        "scanned": scanned,
        "not_scanned": not_scanned,
        "total_students": len(inscriptions),
        "scanned_count": len(scanned),
        "suspicious_count": suspicious_count,
        "is_expired": qr_token.is_expired,
        "has_gps": qr_token.latitude is not None,
        "verify_location": qr_token.verify_location,
        "qr_duration_seconds": sys_settings.qr_token_duration_seconds,
    }

    # HTMX partial refresh (student list only)
    if request.headers.get("HX-Request"):
        return render(request, "absences/_qr_scan_list.html", ctx)

    return render(request, "absences/qr_dashboard.html", ctx)


@login_required
@professor_required
@require_POST
def qr_refresh_token(request, token):
    """Deactivate current token and create a fresh one (preserves scans)."""
    from django.http import JsonResponse
    from apps.dashboard.models import SystemSettings

    qr_token = get_object_or_404(QRAttendanceToken, token=token)
    seance = qr_token.seance
    course = seance.id_cours

    if course.professeur_id != request.user.pk:
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return JsonResponse({"error": "Accès non autorisé."}, status=403)
        messages.error(request, "Accès non autorisé.")
        return redirect("dashboard:instructor_dashboard")

    sys_settings = SystemSettings.get_settings()
    qr_duration_seconds = sys_settings.qr_token_duration_seconds

    # Preserve verify_location and professor GPS from the original token
    old_verify_location = qr_token.verify_location
    old_lat = qr_token.latitude
    old_lng = qr_token.longitude

    QRAttendanceToken.objects.filter(seance=seance, is_active=True).update(is_active=False)

    new_token = QRAttendanceToken.objects.create(
        seance=seance,
        created_by=request.user,
        expires_at=timezone.now() + timedelta(seconds=qr_duration_seconds),
        verify_location=old_verify_location,
        latitude=old_lat,
        longitude=old_lng,
    )

    # AJAX response for auto-refresh
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        scan_url = request.build_absolute_uri(
            reverse("absences:qr_scan", kwargs={"token": str(new_token.token)})
        )
        qr_data_uri = _generate_qr_data_uri(scan_url)
        return JsonResponse({
            "token": str(new_token.token),
            "qr_data_uri": qr_data_uri,
            "scan_url": scan_url,
            "expires_at": new_token.expires_at.isoformat(),
            "refresh_url": reverse("absences:qr_refresh_token", kwargs={"token": str(new_token.token)}),
            "dashboard_url": reverse("absences:qr_dashboard", kwargs={"token": str(new_token.token)}),
            "finalize_url": reverse("absences:qr_finalize", kwargs={"token": str(new_token.token)}),
        })

    messages.success(request, "QR code rafraîchi avec un nouveau token.")
    return redirect("absences:qr_dashboard", token=new_token.token)


@login_required
@professor_required
@require_POST
def qr_finalize(request, token):
    """Finalize QR session: students who did NOT scan are marked absent."""
    qr_token = get_object_or_404(QRAttendanceToken, token=token)
    seance = qr_token.seance
    course = seance.id_cours

    if course.professeur_id != request.user.pk:
        messages.error(request, "Accès non autorisé.")
        return redirect("dashboard:instructor_dashboard")

    if seance.validated:
        messages.warning(request, "Cette séance est déjà validée.")
        return redirect("dashboard:instructor_course_detail", course.id_cours)

    inscriptions = list(
        Inscription.objects.filter(
            id_cours=course,
            id_annee=seance.id_annee,
            status=Inscription.Status.EN_COURS,
        ).select_related("id_etudiant", "id_cours")
    )

    scanned_ids = set(
        QRScanRecord.objects.filter(seance=seance).values_list("inscription_id", flat=True)
    )

    with transaction.atomic():
        # Deactivate token
        QRAttendanceToken.objects.filter(seance=seance, is_active=True).update(is_active=False)

        absent_count = 0
        for ins in inscriptions:
            if ins.id_inscription not in scanned_ids:
                _absence, created = Absence.objects.get_or_create(
                    id_inscription=ins,
                    id_seance=seance,
                    defaults={
                        "type_absence": Absence.TypeAbsence.ABSENT,
                        "duree_absence": seance.duree_heures(),
                        "statut": Absence.Statut.NON_JUSTIFIEE,
                        "encodee_par": request.user,
                        "note_professeur": "Absent (QR non scanné)",
                    },
                )
                if created:
                    absent_count += 1

        seance.validated = True
        seance.validated_by = request.user
        seance.date_validated = timezone.now()
        seance.save(update_fields=["validated", "validated_by", "date_validated"])

        log_action(
            request.user,
            f"QR finalisé — {course.code_cours} {seance.date_seance}: "
            f"{len(scanned_ids)} présent(s), {absent_count} absent(s)",
            request,
            niveau="INFO",
            objet_type="SEANCE",
            objet_id=seance.id_seance,
        )

    messages.success(
        request,
        f"Séance finalisée : {len(scanned_ids)} présent(s), {absent_count} absent(s).",
    )
    return redirect("dashboard:instructor_course_detail", course.id_cours)


def _log_scan_attempt(request, seance, qr_token, gps_status, scan_result,
                      latitude=None, longitude=None, distance=None):
    """Log every QR scan attempt for audit."""
    QRScanLog.objects.create(
        etudiant=request.user,
        seance=seance,
        ip_address=get_client_ip(request),
        latitude=latitude,
        longitude=longitude,
        distance_meters=round(distance, 1) if distance is not None else None,
        gps_status=gps_status,
        scan_result=scan_result,
        qr_token_used=str(qr_token.token) if qr_token else "",
        user_agent=request.META.get("HTTP_USER_AGENT", "")[:500],
    )


def _get_establishment_gps():
    """Return (latitude, longitude, radius) from SystemSettings, or (None, None, 100)."""
    from apps.dashboard.models import SystemSettings
    settings = SystemSettings.get_settings()
    return settings.gps_latitude, settings.gps_longitude, settings.gps_radius_meters


@login_required
@student_required
@require_http_methods(["GET", "POST"])
def qr_scan(request, token):
    """Student scans QR → confirmation page (GET) → record attendance (POST)."""
    qr_token = get_object_or_404(QRAttendanceToken, token=token)
    seance = qr_token.seance
    course = seance.id_cours

    error_ctx = {"course": course, "seance": seance}

    # --- Guard checks with audit logging ---
    if not qr_token.is_active:
        _log_scan_attempt(request, seance, qr_token,
                          QRScanLog.GPSStatus.NOT_REQUIRED,
                          QRScanLog.ScanResult.REJECTED_INACTIVE)
        return render(request, "absences/qr_scan_result.html", {
            **error_ctx, "scan_status": "error",
            "message": "Ce QR code n'est plus actif.",
        })

    if qr_token.is_expired:
        _log_scan_attempt(request, seance, qr_token,
                          QRScanLog.GPSStatus.NOT_REQUIRED,
                          QRScanLog.ScanResult.REJECTED_EXPIRED)
        return render(request, "absences/qr_scan_result.html", {
            **error_ctx, "scan_status": "expired",
            "message": "Ce QR code a expiré. Scannez le nouveau QR affiché par le professeur.",
        })

    if seance.validated:
        _log_scan_attempt(request, seance, qr_token,
                          QRScanLog.GPSStatus.NOT_REQUIRED,
                          QRScanLog.ScanResult.REJECTED_LOCKED)
        return render(request, "absences/qr_scan_result.html", {
            **error_ctx, "scan_status": "error",
            "message": "Cette séance est déjà validée et verrouillée.",
        })

    inscription = Inscription.objects.filter(
        id_etudiant=request.user,
        id_cours=course,
        id_annee=seance.id_annee,
        status=Inscription.Status.EN_COURS,
    ).first()

    if not inscription:
        _log_scan_attempt(request, seance, qr_token,
                          QRScanLog.GPSStatus.NOT_REQUIRED,
                          QRScanLog.ScanResult.REJECTED_NOT_ENROLLED)
        return render(request, "absences/qr_scan_result.html", {
            **error_ctx, "scan_status": "error",
            "message": "Vous n'êtes pas inscrit(e) à ce cours.",
        })

    existing = QRScanRecord.objects.filter(seance=seance, inscription=inscription).first()
    if existing:
        _log_scan_attempt(request, seance, qr_token,
                          QRScanLog.GPSStatus.NOT_REQUIRED,
                          QRScanLog.ScanResult.REJECTED_DUPLICATE)
        return render(request, "absences/qr_scan_result.html", {
            **error_ctx, "scan_status": "duplicate",
            "message": "Votre présence a déjà été enregistrée.",
            "scanned_at": existing.scanned_at,
        })

    # Determine GPS requirement
    gps_required = qr_token.verify_location
    etab_lat, etab_lng, etab_radius = _get_establishment_gps()

    # --- GET: show confirmation page ---
    if request.method == "GET":
        return render(request, "absences/qr_scan.html", {
            "qr_token": qr_token,
            "course": course,
            "seance": seance,
            "gps_required": gps_required,
        })

    # --- POST: record attendance ---
    stu_lat_raw = request.POST.get("latitude", "").strip()
    stu_lng_raw = request.POST.get("longitude", "").strip()
    gps_status_val = request.POST.get("gps_status", "")

    stu_lat_f = None
    stu_lng_f = None
    distance = None
    try:
        if stu_lat_raw and stu_lng_raw:
            stu_lat_f = float(stu_lat_raw)
            stu_lng_f = float(stu_lng_raw)
    except (ValueError, TypeError):
        stu_lat_f = None
        stu_lng_f = None

    # --- MODE 2: GPS verification ENABLED ---
    if gps_required:
        # CAS C: GPS refused by student
        if gps_status_val == "refused":
            _log_scan_attempt(request, seance, qr_token,
                              QRScanLog.GPSStatus.REFUSED,
                              QRScanLog.ScanResult.REJECTED_GPS)
            return render(request, "absences/qr_scan_result.html", {
                **error_ctx, "scan_status": "error",
                "message": "La localisation est obligatoire pour cette séance. "
                           "Veuillez autoriser l'accès GPS et réessayer.",
            })

        # CAS D: GPS unavailable (error or no coords)
        if stu_lat_f is None or stu_lng_f is None:
            _log_scan_attempt(request, seance, qr_token,
                              QRScanLog.GPSStatus.UNAVAILABLE,
                              QRScanLog.ScanResult.REJECTED_GPS)
            return render(request, "absences/qr_scan_result.html", {
                **error_ctx, "scan_status": "error",
                "message": "Impossible d'obtenir votre position. "
                           "Réessayez ou contactez le professeur.",
            })

        # Calculate distance against establishment coordinates
        if etab_lat is not None and etab_lng is not None:
            distance = _haversine(etab_lat, etab_lng, stu_lat_f, stu_lng_f)

            # CAS B: GPS OK but outside radius
            if distance > etab_radius:
                _log_scan_attempt(request, seance, qr_token,
                                  QRScanLog.GPSStatus.ACCEPTED,
                                  QRScanLog.ScanResult.REJECTED_DISTANCE,
                                  stu_lat_f, stu_lng_f, distance)
                return render(request, "absences/qr_scan_result.html", {
                    **error_ctx, "scan_status": "error",
                    "message": f"Vous n'êtes pas dans la zone autorisée. "
                               f"Distance : {distance:.0f} m (max : {etab_radius} m).",
                    "distance": round(distance, 0),
                    "radius": etab_radius,
                })
        # If establishment GPS not configured, fall back to professor GPS
        elif qr_token.latitude is not None and qr_token.longitude is not None:
            distance = _haversine(qr_token.latitude, qr_token.longitude, stu_lat_f, stu_lng_f)
            if distance > QRAttendanceToken.DISTANCE_THRESHOLD_METERS:
                _log_scan_attempt(request, seance, qr_token,
                                  QRScanLog.GPSStatus.ACCEPTED,
                                  QRScanLog.ScanResult.REJECTED_DISTANCE,
                                  stu_lat_f, stu_lng_f, distance)
                return render(request, "absences/qr_scan_result.html", {
                    **error_ctx, "scan_status": "error",
                    "message": f"Vous n'êtes pas dans la zone autorisée. "
                               f"Distance : {distance:.0f} m (max : {QRAttendanceToken.DISTANCE_THRESHOLD_METERS} m).",
                    "distance": round(distance, 0),
                    "radius": QRAttendanceToken.DISTANCE_THRESHOLD_METERS,
                })
        # CAS A: GPS OK + within radius → proceed to record

    # --- Build scan record ---
    scan_kwargs = {
        "seance": seance,
        "student": request.user,
        "inscription": inscription,
        "ip_address": get_client_ip(request),
    }
    is_suspicious = False
    if stu_lat_f is not None and stu_lng_f is not None:
        scan_kwargs["latitude"] = stu_lat_f
        scan_kwargs["longitude"] = stu_lng_f
        # Calculate distance for record if not already done
        if distance is None and qr_token.latitude is not None:
            distance = _haversine(qr_token.latitude, qr_token.longitude, stu_lat_f, stu_lng_f)
        if distance is not None:
            scan_kwargs["distance_meters"] = round(distance, 1)
            is_suspicious = distance > QRAttendanceToken.DISTANCE_THRESHOLD_METERS
            scan_kwargs["is_suspicious"] = is_suspicious

    QRScanRecord.objects.create(**scan_kwargs)

    # Log successful scan
    gps_log_status = (
        QRScanLog.GPSStatus.ACCEPTED if stu_lat_f is not None
        else QRScanLog.GPSStatus.NOT_REQUIRED
    )
    _log_scan_attempt(request, seance, qr_token,
                      gps_log_status,
                      QRScanLog.ScanResult.VALIDATED,
                      stu_lat_f, stu_lng_f, distance)

    result_ctx = {**error_ctx, "scan_status": "success"}
    if is_suspicious:
        result_ctx["message"] = "Présence enregistrée, mais votre position est éloignée de la salle."
        result_ctx["distance"] = round(distance, 0)
    else:
        result_ctx["message"] = "Présence enregistrée avec succès !"

    return render(request, "absences/qr_scan_result.html", result_ctx)
