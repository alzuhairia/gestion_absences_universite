"""
Saisie des présences — formulaire complet (appel manuel).

mark_absence : saisie de présence pour toute la classe (formulaire principal).

RÈGLE MÉTIER CRITIQUE :
  Les absences encodées par le secrétariat (statut JUSTIFIEE / EN_ATTENTE) sont
  PROTÉGÉES : le professeur peut les voir mais pas les modifier.
"""
import datetime
import logging
from decimal import ROUND_HALF_UP, Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from ..models import Absence
from ..services import calculer_absence_stats
from apps.academic_sessions.models import AnneeAcademique, Seance
from apps.academics.models import Cours
from apps.accounts.models import User
from apps.audits.utils import log_action
from apps.dashboard.decorators import professor_required
from apps.enrollments.models import Inscription
from apps.notifications.email import build_absence_recorded_email, send_with_dedup

logger = logging.getLogger(__name__)


@login_required
@professor_required
@require_http_methods(["GET", "POST"])
def mark_absence(request, course_id):
    """
    Saisie de présence / absence pour toute la classe (appel manuel).

    LOGIQUE MÉTIER :
    1. Vérification que le cours appartient au professeur (double sécurité)
    2. Création ou récupération de la séance (unique par cours + date)
    3. Pour chaque étudiant : PRÉSENT (supprime l'absence) ou ABSENT (crée/met à jour)
    4. PARTIEL : absence de durée réduite (retard, départ anticipé)
    5. Validation optionnelle en fin de formulaire (verrouille la séance)

    PROTECTION DES ABSENCES OFFICIELLES :
    Les absences JUSTIFIEE / EN_ATTENTE ne peuvent pas être modifiées
    par le professeur — elles sont encodées par le secrétariat.
    """
    course = get_object_or_404(Cours, id_cours=course_id)
    if course.professeur != request.user:
        messages.error(request, "Accès non autorisé à ce cours.")
        return redirect("dashboard:instructor_dashboard")

    active_year = AnneeAcademique.objects.filter(active=True).first()
    inscriptions_qs = Inscription.objects.filter(
        id_cours=course, status=Inscription.Status.EN_COURS
    ).select_related("id_etudiant")
    if active_year:
        inscriptions_qs = inscriptions_qs.filter(id_annee=active_year)
    inscriptions_by_id = {str(ins.id_inscription): ins for ins in inscriptions_qs}

    if request.method == "POST":
        check_date = request.POST.get("date_seance", "").strip()
        if check_date:
            validated_seance = Seance.objects.filter(
                id_cours=course, date_seance=check_date, validated=True
            ).first()
            if validated_seance:
                messages.error(request, "Cette séance a déjà été validée.")
                return redirect("absences:mark_absence", course_id=course_id)

        invalid_ids = [
            key.split("_", 1)[1]
            for key in request.POST.keys()
            if key.startswith("status_") and key.split("_", 1)[1] not in inscriptions_by_id
        ]
        if invalid_ids:
            log_action(
                request.user,
                f"Tentative d'accès à des inscriptions non autorisées: {', '.join(invalid_ids)}",
                request,
                niveau="WARNING",
                objet_type="INSCRIPTION",
                objet_id=None,
            )
            raise PermissionDenied("Accès non autorisé à une ou plusieurs inscriptions.")

        date_seance = request.POST.get("date_seance", "").strip()
        heure_debut = request.POST.get("heure_debut", "").strip()
        heure_fin = request.POST.get("heure_fin", "").strip()

        if not date_seance or not heure_debut or not heure_fin:
            messages.error(request, "Date et horaires de séance invalides.")
            return redirect("absences:mark_absence", course_id=course_id)

        try:
            fmt = "%H:%M"
            t_debut = datetime.datetime.strptime(heure_debut, fmt)
            t_fin = datetime.datetime.strptime(heure_fin, fmt)
        except (TypeError, ValueError):
            messages.error(request, "Format d'heure invalide (HH:MM attendu).")
            return redirect("absences:mark_absence", course_id=course_id)

        if t_fin <= t_debut:
            messages.error(request, "L'heure de fin doit être postérieure à l'heure de début.")
            return redirect("absences:mark_absence", course_id=course_id)

        duree_seance = Decimal((t_fin - t_debut).seconds) / Decimal(3600)
        duree_seance = duree_seance.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        annee = AnneeAcademique.objects.filter(active=True).first()
        if not annee:
            messages.error(request, "Aucune année académique active.")
            return redirect("absences:mark_absence", course_id=course_id)

        with transaction.atomic():
            seance_created = False
            try:
                seance = Seance.objects.select_for_update().get(date_seance=date_seance, id_cours=course)
                if seance.validated:
                    messages.error(request, "Cette séance a été validée entre-temps.")
                    return redirect("absences:mark_absence", course_id=course_id)

                updated_fields = []
                if seance.heure_debut != heure_debut:
                    seance.heure_debut = heure_debut
                    updated_fields.append("heure_debut")
                if seance.heure_fin != heure_fin:
                    seance.heure_fin = heure_fin
                    updated_fields.append("heure_fin")
                if updated_fields:
                    seance.save(update_fields=updated_fields)
                messages.info(request, "Séance existante récupérée — absences mises à jour.")
            except Seance.DoesNotExist:
                seance = Seance.objects.create(
                    date_seance=date_seance,
                    heure_debut=heure_debut,
                    heure_fin=heure_fin,
                    id_cours=course,
                    id_annee=annee,
                )
                seance_created = True

            for key, value in request.POST.items():
                if not key.startswith("status_"):
                    continue

                inscription_id = key.split("_", 1)[1]
                status = value
                inscription = inscriptions_by_id.get(inscription_id)
                if not inscription:
                    continue

                existing_absence = Absence.objects.filter(
                    id_inscription=inscription, id_seance=seance
                ).first()
                is_prof = request.user.role == User.Role.PROFESSEUR

                if status == "ABSENT":
                    _ALLOWED_TYPES = {Absence.TypeAbsence.ABSENT, Absence.TypeAbsence.PARTIEL}
                    type_absence = request.POST.get(f"type_{inscription_id}", Absence.TypeAbsence.ABSENT)
                    if type_absence not in _ALLOWED_TYPES:
                        type_absence = Absence.TypeAbsence.ABSENT

                    duree = duree_seance
                    if type_absence == Absence.TypeAbsence.PARTIEL:
                        try:
                            duree = Decimal(
                                str(float(request.POST.get(f"duree_{inscription_id}", 0)))
                            ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                            if duree <= 0 or duree > duree_seance:
                                raise ValueError("invalid range")
                        except (TypeError, ValueError):
                            duree = duree_seance
                            messages.warning(
                                request,
                                f"Durée invalide pour {inscription.id_etudiant.get_full_name()} "
                                f"— absence complète ({duree_seance}h) appliquée par défaut.",
                            )

                    if existing_absence and existing_absence.statut in (
                        Absence.Statut.JUSTIFIEE, Absence.Statut.EN_ATTENTE
                    ):
                        continue

                    note = request.POST.get(f"note_{inscription_id}", "").strip()[:500]

                    try:
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
                    except IntegrityError:
                        messages.warning(
                            request,
                            f"Absence déjà enregistrée pour {inscription.id_etudiant.get_full_name()} (doublon ignoré).",
                        )
                        continue

                    if is_prof:
                        log_action(
                            request.user,
                            f"Professeur a enregistré une absence pour "
                            f"{inscription.id_etudiant.get_full_name()} - {course.code_cours} le {date_seance}",
                            request,
                            niveau="INFO",
                            objet_type="ABSENCE",
                            objet_id=absence.id_absence,
                        )

                    if created:
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
                    if existing_absence:
                        if existing_absence.statut in (Absence.Statut.JUSTIFIEE, Absence.Statut.EN_ATTENTE):
                            continue
                        existing_absence.delete()

            if request.user.role == User.Role.PROFESSEUR:
                if seance_created:
                    log_action(
                        request.user,
                        f"Professeur a créé une séance pour {course.code_cours} le {date_seance}",
                        request,
                        niveau="INFO",
                        objet_type="SEANCE",
                        objet_id=seance.id_seance if hasattr(seance, "id_seance") else None,
                    )
                log_action(
                    request.user,
                    f"Professeur a enregistré la présence pour {course.code_cours} le {date_seance}",
                    request,
                    niveau="INFO",
                    objet_type="SEANCE",
                    objet_id=seance.id_seance if hasattr(seance, "id_seance") else None,
                )

            post_action = request.POST.get("form_action", "draft")
            if post_action == "validate":
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
                    f"L'appel du {date_seance} a été validé et verrouillé. La séance ne peut plus être modifiée.",
                )
            else:
                messages.success(
                    request,
                    f"Brouillon enregistré pour la séance du {date_seance}. Vous pourrez le modifier ultérieurement.",
                )

            return redirect(f"{reverse('absences:mark_absence', args=[course_id])}?date={date_seance}")

    # --- GET ---
    students = inscriptions_qs.order_by("id_etudiant__nom")

    today = request.GET.get("date", "")
    try:
        datetime.date.fromisoformat(today)
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
            existing_absences[ab.id_inscription.pk] = {
                "type": ab.type_absence,
                "duree": ab.duree_absence,
                "statut": ab.statut,
                "note_professeur": ab.note_professeur,
                "encodee_par": ab.encodee_par,
            }

    for ins in students:
        setattr(ins, "absence_data", existing_absences.get(ins.id_inscription))

    recap_absent_count = len(existing_absences)
    recap_present_count = len(students) - recap_absent_count

    return render(request, "absences/mark_absence.html", {
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
    })
