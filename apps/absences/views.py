import datetime
import logging
from pathlib import Path

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from apps.absences.models import Absence, Justification
from apps.absences.services import calculer_absence_stats, get_absences_queryset
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

logger = logging.getLogger(__name__)


@login_required
@student_required
def absence_details(request, id_inscription):
    """
    Affiche les dÃ©tails des absences pour un Ã©tudiant - Lecture seule.
    STRICT: Les Ã©tudiants peuvent uniquement consulter leurs absences et soumettre des justificatifs via la vue upload_justification.
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
            if justification.state == "ACCEPTEE":
                status = "JUSTIFIÃ‰E"
                status_color = "success"
            elif justification.state == "REFUSEE":
                status = "NON JUSTIFIÃ‰E"
                status_color = "danger"
            else:  # EN_ATTENTE
                status = "EN ATTENTE"
                status_color = "warning"
        else:
            if absence.statut == "JUSTIFIEE":
                status = "JUSTIFIÃ‰E"
                status_color = "success"
            else:
                status = "NON JUSTIFIÃ‰E"
                status_color = "danger"

        # CORRECTION BUG CRITIQUE #2a — Logique can_submit corrigée
        # AVANT : "and not justification" empêchait la resoumission après refus
        # APRÈS : on distingue explicitement chaque état
        # - Pas encore soumis (absence NON_JUSTIFIEE sans justificatif) → peut soumettre
        # - Justificatif refusé (state=REFUSEE) → peut resoumettre
        # - En attente → ne peut pas soumettre (déjà en cours d'examen)
        # - Accepté → ne peut pas soumettre (déjà validé)
        is_refused = justification is not None and justification.state == "REFUSEE"
        is_not_yet_submitted = justification is None and absence.statut not in (
            "JUSTIFIEE",
            "EN_ATTENTE",
        )
        can_submit = is_not_yet_submitted or is_refused

        absences_data.append(
            {
                "absence": absence,
                "status": status,
                "status_color": status_color,
                "justification": justification,
                "can_submit": can_submit,
            }
        )

    # Get course and professor info
    course = inscription.id_cours
    prof_name = "Non assignÃ©"
    if course.professeur:
        prof_name = course.professeur.get_full_name()

    # Calculate absence statistics
    stats = calculer_absence_stats(inscription)
    absence_rate = stats["taux"]
    # CORRECTION BUG CRITIQUE #4a — Utiliser le seuil configuré du cours
    # Avant : seuil fixe 40% ignorant la personnalisation par cours
    # Après : cours.get_seuil_absence() retourne le seuil configuré ou le défaut système
    seuil = inscription.id_cours.get_seuil_absence()
    is_blocked = absence_rate >= seuil and not inscription.exemption_40

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
        },
    )


@login_required
@student_required
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
    if absence.statut == "JUSTIFIEE":
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
    if justification and justification.state == "ACCEPTEE":
        messages.success(
            request,
            "Votre justificatif a ete accepte par le secretariat. Cette absence est maintenant justifiee.",
        )
        return redirect(
            "absences:details", id_inscription=absence.id_inscription.id_inscription
        )

    # STRICT: If justification is EN_ATTENTE, cannot modify (already submitted)
    if justification and justification.state == "EN_ATTENTE":
        messages.warning(
            request,
            "Un justificatif a deja ete soumis pour cette absence et est actuellement en cours d'examen par le secretariat. "
            "Vous ne pouvez plus le modifier. Vous serez notifie une fois la decision prise.",
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
            if justification and justification.state == "REFUSEE":
                # Resubmit if previous was refused - update existing justification
                justification.document = file
                justification.commentaire = comment
                justification.state = "EN_ATTENTE"
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
                    state="EN_ATTENTE",
                )
            else:
                # Should not happen due to checks above, but handle gracefully
                messages.error(
                    request,
                    "Impossible de soumettre le justificatif dans l'etat actuel.",
                )
                return redirect("absences:upload", absence_id=absence_id)

            # Update absence status to EN_ATTENTE (for display purposes)
            absence.statut = "EN_ATTENTE"
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

        messages.success(
            request,
            "Votre justificatif a ete envoye avec succes. Il sera examine par le secretariat dans les plus brefs delais. "
            "Vous serez notifie une fois la decision prise. Vous ne pourrez plus modifier ce justificatif.",
        )
        return redirect(
            "absences:details", id_inscription=absence.id_inscription.id_inscription
        )

    return render(
        request,
        "absences/justify.html",
        {"absence": absence, "justification": justification},
    )


@login_required
@secretary_required
@require_POST
def valider_justificatif(request, absence_id):
    """Valide une justification et met a jour l'etat de l'absence."""
    # FIX ORANGE #11a — Check de rôle supprimé car redondant :
    # Le décorateur @secretary_required gère déjà l'exclusion des non-secrétaires
    # (y compris le message d'avertissement spécifique pour les admins).

    absence = get_object_or_404(Absence, id_absence=absence_id)
    justification = Justification.objects.filter(id_absence=absence).first()
    if not justification:
        messages.error(request, "Aucun justificatif trouve pour cette absence.")
        return redirect("dashboard:index")

    with transaction.atomic():
        absence.statut = "JUSTIFIEE"
        absence.save()

        justification.state = "ACCEPTEE"
        justification.validee_par = request.user
        justification.date_validation = timezone.now()
        justification.save()

    messages.success(
        request,
        f"L'absence de {absence.id_inscription.id_etudiant.email} a ete validee.",
    )
    return redirect("dashboard:index")


@login_required
@secretary_required
@require_POST
def refuser_justificatif(request, absence_id):
    """Refuse un justificatif et remet l'absence en NON_JUSTIFIEE."""
    # FIX ORANGE #11b — Check de rôle supprimé car redondant :
    # Le décorateur @secretary_required gère déjà l'exclusion des non-secrétaires
    # (y compris le message d'avertissement spécifique pour les admins).

    absence = get_object_or_404(Absence, id_absence=absence_id)
    justification = Justification.objects.filter(id_absence=absence).first()
    if not justification:
        messages.error(request, "Aucun justificatif trouve pour cette absence.")
        return redirect("dashboard:index")

    with transaction.atomic():
        absence.statut = "NON_JUSTIFIEE"
        absence.save()

        justification.state = "REFUSEE"
        justification.validee_par = request.user
        justification.date_validation = timezone.now()
        justification.save()

    messages.warning(request, "Le justificatif a ete refuse.")
    return redirect("dashboard:index")


@login_required
@secretary_required
def review_justification(request, absence_id):
    """
    Review justification - STRICT: Only for secretaries, NOT for professors or admins.
    Professors should NEVER see or modify justifications.
    Administrators manage configuration, not daily operations.
    """
    # FIX ORANGE #11c — Check de rôle supprimé car redondant avec @secretary_required.
    # Le décorateur gère : SECRETAIRE autorisé, ADMIN → message avertissement,
    # autres rôles → message erreur + redirection. Comportement identique, code centralisé.
    absence = get_object_or_404(Absence, id_absence=absence_id)
    justification = get_object_or_404(Justification, id_absence=absence)

    if request.method == "POST":
        # Mise a jour du commentaire de gestion
        new_comment = request.POST.get("commentaire_gestion")
        justification.commentaire_gestion = new_comment
        justification.save()
        messages.success(request, "Commentaire mis a jour.")
        # On redirige vers la meme page pour voir le resultat
        return redirect("absences:review_justification", absence_id=absence_id)

    # Document lie (FileField)
    document_url = None
    document_name = None
    if justification.document:
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
def mark_absence(request, course_id):
    """
    Vue pour qu'un professeur puisse noter les absences d'une sÃ©ance.

    IMPORTANT POUR LA SOUTENANCE :
    Cette fonction implÃ©mente la saisie des prÃ©sences/absences par le professeur.

    Logique mÃ©tier :
    1. VÃ©rification que le cours appartient au professeur (sÃ©curitÃ©)
    2. CrÃ©ation ou rÃ©cupÃ©ration de la sÃ©ance
    3. Pour chaque Ã©tudiant inscrit :
       - Marquer comme PRÃ‰SENT, ABSENT, ou ABSENT JUSTIFIÃ‰
       - Si absent, dÃ©finir le type (sÃ©ance complÃ¨te, retard/partiel, journÃ©e)
       - Calculer la durÃ©e de l'absence

    RÃˆGLE CRITIQUE - PROTECTION DES ABSENCES JUSTIFIÃ‰ES :
    - Les absences encodÃ©es par le secrÃ©tariat (statut JUSTIFIEE) sont PROTÃ‰GÃ‰ES
    - Le professeur peut les VOIR mais ne peut PAS les modifier
    - Cette rÃ¨gle garantit l'intÃ©gritÃ© des absences officielles

    SÃ‰CURITÃ‰ :
    - @professor_required : seul un professeur peut accÃ©der
    - VÃ©rification supplÃ©mentaire : course.professeur == request.user
    - Double vÃ©rification pour garantir que le professeur ne peut accÃ©der qu'Ã  ses cours

    Args:
        request: Objet HttpRequest contenant les donnÃ©es du formulaire
        course_id: ID du cours pour lequel faire l'appel

    Returns:
        HttpResponse avec le formulaire ou redirection aprÃ¨s sauvegarde
    """
    # ============================================
    # VÃ‰RIFICATION DE SÃ‰CURITÃ‰
    # ============================================
    # IMPORTANT : Double vÃ©rification (dÃ©corateur + vÃ©rification de propriÃ©tÃ©)
    # Un professeur ne peut accÃ©der qu'Ã  SES propres cours

    course = get_object_or_404(Cours, id_cours=course_id)
    if course.professeur != request.user:
        messages.error(request, "AccÃ¨s non autorisÃ© Ã  ce cours.")
        return redirect("dashboard:instructor_dashboard")

    inscriptions_qs = Inscription.objects.filter(id_cours=course).select_related(
        "id_etudiant"
    )
    inscriptions_by_id = {str(ins.id_inscription): ins for ins in inscriptions_qs}

    if request.method == "POST":
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
        duree_seance = (t_fin - t_debut).seconds / 3600.0

        with transaction.atomic():
            # --- OPÉRATIONS DB (données validées, aucun risque de séance fantôme) ---
            # Récupération de l'année active (mock ou réelle)
            annee = AnneeAcademique.objects.filter(active=True).first()
            if not annee:
                # Fallback si pas d'année active définie
                annee, _ = AnneeAcademique.objects.get_or_create(
                    libelle="2024-2025", defaults={"active": True}
                )

            # Création ou Récupération de la séance (données déjà validées en amont)
            seance, created = Seance.objects.get_or_create(
                date_seance=date_seance,
                heure_debut=heure_debut,
                heure_fin=heure_fin,
                id_cours=course,
                defaults={"id_annee": annee},
            )

            if not created:
                messages.info(
                    request,
                    "Une séance existe déjà pour cette date. Les absences seront mises à jour pour cette séance existante.",
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

                    type_absence = request.POST.get(f"type_{inscription_id}", "SEANCE")
                    if type_absence not in {"SEANCE", "HEURE", "JOURNEE"}:
                        logger.warning(
                            "Type d'absence invalide recu (%s) pour inscription %s. Fallback SEANCE.",
                            type_absence,
                            inscription_id,
                        )
                        type_absence = "SEANCE"

                    # Determiner la duree
                    duree = duree_seance  # Default for SEANCE
                    if type_absence == "HEURE":
                        try:
                            duree = float(
                                request.POST.get(f"duree_{inscription_id}", 0)
                            )
                            if duree <= 0 or duree > 24:
                                raise ValueError("invalid duration range")
                        except (TypeError, ValueError):
                            logger.warning(
                                "Duree d'absence invalide pour inscription %s. Utilisation de la duree de seance.",
                                inscription_id,
                            )
                            duree = duree_seance
                    elif type_absence == "JOURNEE":
                        duree = 8.0  # Valeur arbitraire pour journee

                    # Creation ou Mise a jour Absence (only if not validated)
                    if existing_absence and existing_absence.statut == "JUSTIFIEE":
                        # Skip validated absences - professors cannot modify them
                        continue

                    absence, created = Absence.objects.update_or_create(
                        id_inscription=inscription,
                        id_seance=seance,
                        defaults={
                            "type_absence": type_absence,
                            "duree_absence": duree,
                            "statut": "NON_JUSTIFIEE",
                            "encodee_par": request.user,
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
                else:
                    # Si marque PRESENT, on supprime une eventuelle absence existante pour cette seance
                    # STRICT: Professors CANNOT delete or modify existing absences
                    if existing_absence:
                        if is_prof:
                            # Professors cannot delete absences (especially validated ones)
                            continue
                        # Only admins/secretaries can delete
                        if existing_absence.statut != "JUSTIFIEE":
                            existing_absence.delete()

            # Audit logging for session creation/attendance
            if request.user.role == User.Role.PROFESSEUR:
                if created:
                    log_action(
                        request.user,
                        f"Professeur a crÃ©Ã© une sÃ©ance pour {course.code_cours} le {date_seance}",
                        request,
                        niveau="INFO",
                        objet_type="SEANCE",
                        objet_id=(
                            seance.id_seance if hasattr(seance, "id_seance") else None
                        ),
                    )
                log_action(
                    request.user,
                    f"Professeur a enregistrÃ© la prÃ©sence pour {course.code_cours} le {date_seance}",
                    request,
                    niveau="INFO",
                    objet_type="SEANCE",
                    objet_id=seance.id_seance if hasattr(seance, "id_seance") else None,
                )

            messages.success(
                request,
                f"Les absences ont Ã©tÃ© enregistrÃ©es avec succÃ¨s pour la sÃ©ance du {date_seance}. "
                "Vous pouvez consulter les dÃ©tails dans la page du cours.",
            )
            return redirect("dashboard:instructor_dashboard")

    # --- AFFICHAGE DU FORMULAIRE (GET) ---
    students = inscriptions_qs.order_by("id_etudiant__nom")

    # Check for date in GET (from dashboard link)
    today = request.GET.get("date", timezone.now().strftime("%Y-%m-%d"))
    default_start = "08:30"
    default_end = "10:30"

    existing_seance = (
        Seance.objects.filter(id_cours=course, date_seance=today)
        .order_by("-id_seance")
        .first()
    )

    existing_absences = {}
    is_edit_mode = False

    if existing_seance:
        is_edit_mode = True
        default_start = existing_seance.heure_debut.strftime("%H:%M")
        default_end = existing_seance.heure_fin.strftime("%H:%M")

        abs_list = Absence.objects.filter(id_seance=existing_seance)
        for ab in abs_list:
            existing_absences[ab.id_inscription.id_inscription] = {
                "type": ab.type_absence,
                "duree": ab.duree_absence,
                "statut": ab.statut,
            }

    # Attach absence data to students for template usage
    for ins in students:
        ins.absence_data = existing_absences.get(ins.id_inscription)

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
        },
    )
