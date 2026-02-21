import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.files.base import ContentFile
from django.core.paginator import Paginator
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.academic_sessions.models import AnneeAcademique, Seance
from apps.academics.models import Cours
from apps.audits.utils import log_action
from apps.dashboard.decorators import secretary_required
from apps.enrollments.models import Inscription
from apps.notifications.models import Notification

from .forms import SecretaryJustifiedAbsenceForm
from .models import Absence, Justification
from .utils_upload import (
    UploadValidationError,
    generate_safe_upload_filename,
    validate_uploaded_file,
)

logger = logging.getLogger(__name__)


@login_required
@secretary_required
def validation_list(request):
    """
    Liste des justificatifs nécessitant une validation.
    """
    # FIX VERT #18 — Validation du paramètre status_filter contre les choix valides.
    # Avant : n'importe quelle valeur pouvait être injectée → résultats vides silencieux.
    # Après : valeur non reconnue → repli sur EN_ATTENTE (comportement sûr et attendu).
    _VALID_JUSTIFICATION_STATES = {"EN_ATTENTE", "ACCEPTEE", "REFUSEE"}
    status_filter = request.GET.get("status", "EN_ATTENTE")
    if status_filter not in _VALID_JUSTIFICATION_STATES:
        status_filter = "EN_ATTENTE"

    justifications = (
        Justification.objects.filter(state=status_filter)
        .select_related(
            "id_absence",
            "id_absence__id_inscription",
            "id_absence__id_inscription__id_etudiant",
            "id_absence__id_seance__id_cours",
        )
        .order_by("-id_justification")
    )

    # Pagination
    paginator = Paginator(justifications, 20)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    return render(
        request,
        "absences/validation_list.html",
        {"page_obj": page_obj, "current_status": status_filter},
    )


@login_required
@secretary_required
@require_POST
def process_justification(request, pk):
    """
    Traite une justification d'absence (Approuver/Refuser).

    IMPORTANT POUR LA SOUTENANCE :
    Cette fonction permet au secrétariat de valider ou refuser un justificatif
    soumis par un étudiant.

    Logique métier :
    1. Récupération de la justification à traiter
    2. Selon l'action (approve/reject) :
       - APPROUVER :
         * Mise à jour du statut de la justification à ACCEPTEE
         * Mise à jour du statut de l'absence à JUSTIFIEE
         * Notification à l'étudiant (acceptation)
         * Log d'audit
       - REFUSER :
         * Mise à jour du statut de la justification à REFUSEE
         * Mise à jour du statut de l'absence à NON_JUSTIFIEE
         * Notification à l'étudiant avec le motif du refus
         * Log d'audit

    SÉCURITÉ :
    - @secretary_required : SEUL le secrétariat peut valider/refuser
    - @require_POST : Seulement via formulaire POST (pas d'accès direct par URL)
    - ADMIN est explicitement exclu (gère la configuration, pas les opérations)

    TRAÇABILITÉ :
    - Toutes les actions sont enregistrées dans le journal d'audit
    - Le motif du refus est enregistré et communiqué à l'étudiant

    Args:
        request: Objet HttpRequest contenant l'action (approve/reject) et le commentaire
        pk: ID de la justification à traiter

    Returns:
        Redirection vers la liste des justificatifs
    """
    justification = get_object_or_404(Justification, pk=pk)
    action = request.POST.get("action")
    comment = request.POST.get("comment", "")

    previous_state = justification.state

    if action == "approve":
        with transaction.atomic():
            justification.state = "ACCEPTEE"
            justification.validee = True  # Legacy support
            justification.commentaire_gestion = comment
            justification.validee_par = request.user
            justification.date_validation = timezone.now()
            justification.save()

            # Update Absence Status
            absence = justification.id_absence
            absence.statut = "JUSTIFIEE"
            absence.save()

        # Determine Notification Message
        msg_text = f"Votre justification pour l'absence du {absence.id_seance.date_seance} a été ACCEPTÉE."

        log_action(
            request.user,
            f"Secrétaire a APPROUVÉ la justification {justification.pk} pour l'absence {absence.pk} - {absence.id_seance.id_cours.code_cours}. Motif: {comment}",
            request,
            niveau="INFO",
            objet_type="JUSTIFICATION",
            objet_id=justification.id_justification,
        )

    elif action == "reject":
        with transaction.atomic():
            justification.state = "REFUSEE"
            justification.validee = False  # Legacy support
            justification.commentaire_gestion = comment
            justification.validee_par = request.user
            justification.date_validation = timezone.now()
            justification.save()

            # Update Absence Status
            absence = justification.id_absence
            absence.statut = "NON_JUSTIFIEE"
            absence.save()

        msg_text = f"Votre justification pour l'absence du {absence.id_seance.date_seance} a été REFUSÉE. Motif : {comment}"

        log_action(
            request.user,
            f"Secrétaire a REFUSÉ la justification {justification.pk} pour l'absence {absence.pk} - {absence.id_seance.id_cours.code_cours}. Motif: {comment}",
            request,
            niveau="WARNING",
            objet_type="JUSTIFICATION",
            objet_id=justification.id_justification,
        )

    else:
        messages.error(request, "Action invalide.")
        return redirect("absences:validation_list")

    # Send Notification (if state changed)
    if previous_state != justification.state:
        Notification.objects.create(
            id_utilisateur=justification.id_absence.id_inscription.id_etudiant,
            message=msg_text,
            date_envoi=timezone.now(),
            lue=False,
        )
        if action == "approve":
            messages.success(
                request,
                f"Le justificatif a été accepté avec succès. L'absence de {absence.id_inscription.id_etudiant.get_full_name()} "
                f"pour le cours {absence.id_seance.id_cours.code_cours} est maintenant justifiée. L'étudiant a été notifié.",
            )
        else:
            messages.warning(
                request,
                f"Le justificatif a été refusé. L'absence de {absence.id_inscription.id_etudiant.get_full_name()} "
                f"reste non justifiée. L'étudiant a été notifié avec le motif indiqué.",
            )

    return redirect("absences:validation_list")


@login_required
@secretary_required
def create_justified_absence(request):
    """
    Vue pour que le secretariat encode directement une absence justifiee.

    IMPORTANT POUR LA SOUTENANCE :
    Cette fonction permet au secretariat d'encoder directement une absence justifiee,
    sans passer par le processus normal de soumission de justificatif par l'etudiant.

    Cas d'usage :
    - Un etudiant envoie un email au secretariat avec un justificatif
    - Le secretariat encode directement l'absence comme justifiee
    - L'absence est officielle et prioritaire (le professeur ne peut pas la modifier)

    Logique metier :
    1. Selection de l'etudiant, de la date et des cours concernes
    2. Possibilite d'encoder pour plusieurs cours le meme jour
    3. Creation automatique de la seance si elle n'existe pas
    4. Creation de l'absence avec statut JUSTIFIEE
    5. Creation de la justification associee (si document fourni)
    6. Tracabilite complete (journal d'audit)

    SECURITE :
    - @secretary_required : seul le secretariat peut encoder
    - Transaction atomique : toutes les absences ou aucune
    - Verification que l'etudiant est inscrit au cours

    Args:
        request: Objet HttpRequest contenant les donnees du formulaire

    Returns:
        HttpResponse avec le formulaire ou redirection vers la liste des absences justifiees
    """
    if request.method == "POST":
        form = SecretaryJustifiedAbsenceForm(request.POST, request.FILES)
        if form.is_valid():
            etudiant = form.cleaned_data["etudiant"]
            date_absence = form.cleaned_data["date_absence"]
            cours_list = form.cleaned_data["cours"]
            type_absence = form.cleaned_data["type_absence"]
            duree_absence = form.cleaned_data.get("duree_absence", 0)
            heure_debut_raw = form.cleaned_data.get("heure_debut")
            heure_fin_raw = form.cleaned_data.get("heure_fin")
            commentaire = form.cleaned_data.get("commentaire", "")
            document_file = form.cleaned_data.get("document")

            # Recuperer l'annee academique active
            annee_active = AnneeAcademique.objects.filter(active=True).first()
            if not annee_active:
                messages.error(request, "Aucune annee academique active n'est definie.")
                return render(
                    request, "absences/create_justified_absence.html", {"form": form}
                )

            # Traiter le document si fourni
            document_bytes = None
            document_name = None
            if document_file:
                try:
                    meta = validate_uploaded_file(document_file)
                    document_name = generate_safe_upload_filename(meta["extension"])
                    document_file.name = document_name
                except UploadValidationError as exc:
                    messages.error(request, " ".join(exc.messages))
                    return render(
                        request,
                        "absences/create_justified_absence.html",
                        {"form": form},
                    )

                document_bytes = document_file.read()

            # Creer les absences pour chaque cours selectionne
            absences_created = []
            with transaction.atomic():
                for cours in cours_list:
                    # Verifier que l'etudiant est inscrit a ce cours
                    inscription = Inscription.objects.filter(
                        id_etudiant=etudiant,
                        id_cours=cours,
                        id_annee=annee_active,
                        status="EN_COURS",
                    ).first()

                    if not inscription:
                        messages.warning(
                            request,
                            f"L'etudiant {etudiant.get_full_name()} n'est pas inscrit au cours {cours.code_cours} pour l'annee {annee_active.libelle}.",
                        )
                        continue

                    # Determiner les heures de la seance
                    # Si heures non specifiees, utiliser les heures par defaut (8h-10h)
                    from datetime import time as dt_time

                    seance_heure_debut = (
                        heure_debut_raw if heure_debut_raw else dt_time(8, 0)
                    )
                    seance_heure_fin = (
                        heure_fin_raw if heure_fin_raw else dt_time(10, 0)
                    )

                    # Verifier que l'heure de fin est apres l'heure de debut
                    # Si ce n'est pas le cas, ajuster automatiquement
                    if seance_heure_fin <= seance_heure_debut:
                        from datetime import datetime, timedelta

                        date_ref = datetime(2000, 1, 1)
                        debut = datetime.combine(date_ref, seance_heure_debut)
                        fin = datetime.combine(date_ref, seance_heure_fin)
                        if fin <= debut:
                            # Ajouter 2 heures a l'heure de debut si l'heure de fin est invalide
                            fin = debut + timedelta(hours=2)
                        seance_heure_fin = fin.time()

                    # Creer ou recuperer la seance
                    seance, _ = Seance.objects.get_or_create(
                        date_seance=date_absence,
                        heure_debut=seance_heure_debut,
                        heure_fin=seance_heure_fin,
                        id_cours=cours,
                        id_annee=annee_active,
                        defaults={},
                    )

                    # Calculer la duree si necessaire
                    if type_absence == "SEANCE":
                        # Calculer la duree de la seance
                        from datetime import datetime, timedelta

                        date_ref = datetime(2000, 1, 1)
                        debut = datetime.combine(date_ref, seance_heure_debut)
                        fin = datetime.combine(date_ref, seance_heure_fin)
                        if fin < debut:
                            fin += timedelta(days=1)
                        duree = (fin - debut).total_seconds() / 3600.0
                    elif type_absence == "HEURE":
                        duree = duree_absence if duree_absence > 0 else 1.0
                    else:  # JOURNEE
                        duree = 8.0

                    # Creer ou mettre a jour l'absence (justifiee directement)
                    absence, created = Absence.objects.update_or_create(
                        id_inscription=inscription,
                        id_seance=seance,
                        defaults={
                            "type_absence": type_absence,
                            "duree_absence": duree,
                            "statut": "JUSTIFIEE",  # Directement justifiee
                            "encodee_par": request.user,
                        },
                    )

                    # Creer la justification associee si document fourni ou commentaire
                    if document_bytes or commentaire:
                        document_to_save = None
                        if document_bytes:
                            document_to_save = ContentFile(document_bytes)
                            document_to_save.name = document_name or "justificatif.bin"

                        Justification.objects.update_or_create(
                            id_absence=absence,
                            defaults={
                                "document": document_to_save,
                                "commentaire": commentaire,
                                "commentaire_gestion": f"Absence encodee directement par le secretariat le {timezone.now().strftime('%d/%m/%Y a %H:%M')}",
                                "state": "ACCEPTEE",
                                "validee": True,
                                "validee_par": request.user,
                                "date_validation": timezone.now(),
                            },
                        )

                    absences_created.append(
                        {"cours": cours.code_cours, "absence": absence}
                    )

                    # Audit logging
                    log_action(
                        request.user,
                        f"Secretaire a encode une absence justifiee pour {etudiant.get_full_name()} - {cours.code_cours} le {date_absence}",
                        request,
                        niveau="INFO",
                        objet_type="ABSENCE",
                        objet_id=absence.id_absence,
                    )

            if absences_created:
                messages.success(
                    request,
                    f"Absence(s) justifiee(s) encodee(s) avec succes pour {etudiant.get_full_name()} "
                    f"le {date_absence} ({len(absences_created)} cours).",
                )
                return redirect("absences:validation_list")
            else:
                messages.error(
                    request,
                    "Aucune absence n'a pu etre creee. Verifiez que l'etudiant est bien inscrit aux cours selectionnes.",
                )
    else:
        form = SecretaryJustifiedAbsenceForm()

    return render(request, "absences/create_justified_absence.html", {"form": form})


@login_required
@secretary_required
def justified_absences_list(request):
    """
    Liste des absences justifiées encodées par le secrétariat.
    Permet de consulter toutes les absences justifiées avec leurs détails.
    """
    try:
        # Filtrer les absences justifiées
        absences = (
            Absence.objects.filter(statut="JUSTIFIEE")
            .select_related(
                "id_inscription__id_etudiant",
                "id_seance__id_cours",
                "id_seance__id_cours__id_departement",
                "id_seance__id_cours__id_departement__id_faculte",
                "encodee_par",
            )
            .prefetch_related("justification")
            .order_by("-id_seance__date_seance", "-id_absence")
        )

        # Filtrer par étudiant si demandé
        student_filter = request.GET.get("student")
        if student_filter:
            absences = absences.filter(
                id_inscription__id_etudiant__email__icontains=student_filter
            )

        # Filtrer par date si demandé
        date_filter = request.GET.get("date")
        if date_filter:
            absences = absences.filter(id_seance__date_seance=date_filter)

        # Filtrer par cours si demandé
        course_filter = request.GET.get("course")
        if course_filter:
            absences = absences.filter(
                id_seance__id_cours__code_cours__icontains=course_filter
            )

        # Grouper par étudiant et date pour faciliter la lecture
        # On va créer une structure de données groupée
        grouped_absences = {}
        for absence in absences:
            key = f"{absence.id_inscription.id_etudiant.id_utilisateur}_{absence.id_seance.date_seance}"
            if key not in grouped_absences:
                # Récupérer la justification pour avoir la date de validation si elle existe
                date_encodage = None
                try:
                    justification = absence.justification
                    if justification and justification.date_validation:
                        date_encodage = justification.date_validation
                except Justification.DoesNotExist:
                    # Pas de justification associée, on laisse date_encodage à None
                    pass

                grouped_absences[key] = {
                    "etudiant": absence.id_inscription.id_etudiant,
                    "date": absence.id_seance.date_seance,
                    "absences": [],
                    "encodee_par": absence.encodee_par,
                    "date_encodage": date_encodage,
                    "total_duree": 0.0,
                }
            grouped_absences[key]["absences"].append(absence)
            grouped_absences[key]["total_duree"] += absence.duree_absence

        # Convertir en liste triée
        absences_list = sorted(
            grouped_absences.values(),
            key=lambda x: (x["date"], x["etudiant"].nom or ""),
            reverse=True,
        )

        # Pagination
        paginator = Paginator(absences_list, 20)
        page_number = request.GET.get("page")
        page_obj = paginator.get_page(page_number)

        return render(
            request,
            "absences/justified_absences_list.html",
            {
                "page_obj": page_obj,
                "student_filter": student_filter or "",
                "date_filter": date_filter or "",
                "course_filter": course_filter or "",
            },
        )
    except Exception:
        messages.error(request, "Une erreur interne est survenue.")
        # Log l'erreur avec le système de logging Django
        logger.exception("Error in justified_absences_list")
        return render(
            request,
            "absences/justified_absences_list.html",
            {
                "page_obj": None,
                "student_filter": "",
                "date_filter": "",
                "course_filter": "",
            },
        )
