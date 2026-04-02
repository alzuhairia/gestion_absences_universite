"""
FICHIER : apps/enrollments/views_rules.py
RESPONSABILITE : Gestion des regles d'absence et exemptions (secretaire)
FONCTIONNALITES PRINCIPALES :
  - Liste des etudiants en infraction de seuil
  - Attribution/revocation des exemptions avec motif
DEPENDANCES CLES : enrollments.models, absences.services, audits.utils
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction

from apps.utils import safe_get_page
from django.db.models import Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_POST

from apps.absences.models import Absence
from apps.absences.services import get_system_threshold, recalculer_eligibilite
from apps.accounts.models import User
from apps.audits.utils import log_action
from apps.dashboard.decorators import secretary_required
from apps.enrollments.models import Inscription
from apps.notifications.email import send_with_dedup


@login_required
@secretary_required
@require_GET
def rules_management(request):
    """
    List students violating the absence threshold rule (per-course or system default).
    """
    from apps.academic_sessions.models import AnneeAcademique

    active_year = AnneeAcademique.objects.filter(active=True).first()
    system_threshold = get_system_threshold()

    inscriptions_qs = Inscription.objects.filter(
        status=Inscription.Status.EN_COURS,
    ).select_related("id_cours", "id_etudiant")
    if active_year:
        inscriptions_qs = inscriptions_qs.filter(id_annee=active_year)

    # Evaluate once: extract IDs from Python objects instead of an extra query.
    inscriptions_list = list(inscriptions_qs)
    inscription_ids = [ins.id_inscription for ins in inscriptions_list]
    # EN_ATTENTE counts as non-justified (loophole closed — consistent with
    # all other views: services.py, views_professor.py, views_student.py).
    absence_sums = dict(
        Absence.objects.filter(
            id_inscription__in=inscription_ids,
            statut__in=[Absence.Statut.NON_JUSTIFIEE, Absence.Statut.EN_ATTENTE],
        )
        .values("id_inscription")
        .annotate(total=Sum("duree_absence"))
        .values_list("id_inscription", "total")
    )
    at_risk_list = []

    for ins in inscriptions_list:
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
                is_blocked = rate >= seuil_effectif
                is_under_exemption = ins.exemption_40 and not is_blocked
                at_risk_list.append(
                    {
                        "inscription": ins,
                        "etudiant": ins.id_etudiant,
                        "cours": cours,
                        "total_abs": total_abs,
                        "rate": round(rate, 1),
                        "seuil": seuil,
                        "seuil_effectif": seuil_effectif,
                        "is_blocked": is_blocked,
                        "is_under_exemption": is_under_exemption,
                        "exemption": ins.exemption_40,
                        "exemption_margin": ins.exemption_margin,
                    }
                )

    # Calculate statistics
    blocked_count = sum(1 for item in at_risk_list if item["is_blocked"])
    exempted_count = sum(1 for item in at_risk_list if item["is_under_exemption"])

    # Pagination
    paginator = Paginator(at_risk_list, 25)
    page_obj = safe_get_page(paginator, request.GET.get("page"))

    return render(
        request,
        "enrollments/rules_list.html",
        {
            "at_risk_list": page_obj,
            "page_obj": page_obj,
            "blocked_count": blocked_count,
            "exempted_count": exempted_count,
        },
    )


@login_required
@secretary_required
@require_POST
def toggle_exemption(request, pk):
    """
    Grant or Revoke absence threshold exemption.
    """
    # Verify existence (404 if not found) before proceeding
    get_object_or_404(Inscription, pk=pk)

    action = request.POST.get("action")  # 'grant' or 'revoke'
    motif = request.POST.get("motif", "").strip()

    if action == "grant":
        if not motif:
            messages.error(request, "Un motif est requis pour accorder une exemption.")
            return redirect("dashboard:secretary_seuils_absence")
        if len(motif) > 2000:
            messages.error(request, "Le motif ne peut pas dépasser 2000 caractères.")
            return redirect("dashboard:secretary_seuils_absence")

        # Parse margin (default 10, clamped 1-100)
        try:
            margin = int(request.POST.get("exemption_margin", 10))
        except (ValueError, TypeError):
            margin = 10
        margin = max(1, min(margin, 100))

        with transaction.atomic():
            # select_related prefetches FK chains used in log_action/messages below
            inscription = (
                Inscription.objects
                .select_related("id_etudiant", "id_cours")
                .select_for_update()
                .get(pk=pk)
            )
            inscription.exemption_40 = True
            inscription.motif_exemption = motif
            inscription.exemption_margin = margin
            inscription.save()
            recalculer_eligibilite(inscription)
            log_action(
                request.user,
                f"Secrétaire a accordé une EXEMPTION à {inscription.id_etudiant.get_full_name()} pour le cours {inscription.id_cours.code_cours}. Motif: {motif[:200]}",
                request,
                niveau="WARNING",
                objet_type="INSCRIPTION",
                objet_id=inscription.id_inscription,
            )

            # Email notification to student (deferred until transaction commits)
            student = inscription.id_etudiant
            course_name = inscription.id_cours.nom_cours
            insc_pk = inscription.id_inscription
            subject = f"[UniAbsences] Exemption accordée — {course_name}"
            body = (
                f"Bonjour {student.get_full_name()},\n\n"
                f"Une exemption au seuil d'absence a été accordée pour le cours "
                f"« {course_name} ».\n\n"
                f"Vous êtes désormais autorisé(e) à passer l'examen malgré le "
                f"dépassement du seuil d'absence.\n\n"
                f"— UniAbsences Notification System"
            )
            transaction.on_commit(lambda: send_with_dedup(
                student, subject, body, None,
                event_type="exemption_granted",
                event_key=str(insc_pk),
            ))

        messages.success(
            request,
            f"L'exemption a été accordée avec succès à {inscription.id_etudiant.get_full_name()} pour le cours {inscription.id_cours.code_cours}. "
            f"L'étudiant peut maintenant passer les examens malgré le dépassement du seuil.",
        )

    elif action != "revoke":
        messages.error(request, "Action invalide.")
        return redirect("dashboard:secretary_seuils_absence")

    if action == "revoke":
        with transaction.atomic():
            inscription = (
                Inscription.objects
                .select_related("id_etudiant", "id_cours")
                .select_for_update()
                .get(pk=pk)
            )
            inscription.exemption_40 = False
            inscription.motif_exemption = None
            inscription.save()
            recalculer_eligibilite(inscription)
            log_action(
                request.user,
                f"Secrétaire a RÉVOQUÉ l'exemption de {inscription.id_etudiant.get_full_name()} pour le cours {inscription.id_cours.code_cours}",
                request,
                niveau="WARNING",
                objet_type="INSCRIPTION",
                objet_id=inscription.id_inscription,
            )
        messages.warning(
            request,
            f"L'exemption a été révoquée pour {inscription.id_etudiant.get_full_name()} dans le cours {inscription.id_cours.code_cours}. "
            f"L'étudiant est maintenant bloqué pour les examens.",
        )

    return redirect("dashboard:secretary_seuils_absence")
