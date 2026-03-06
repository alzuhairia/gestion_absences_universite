from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.absences.models import Absence
from apps.absences.services import get_system_threshold, recalculer_eligibilite
from apps.accounts.models import User
from apps.audits.utils import log_action
from apps.dashboard.decorators import secretary_required
from apps.enrollments.models import Inscription


@login_required
@secretary_required
def rules_management(request):
    """
    List students violating the absence threshold rule (per-course or system default).
    """
    from apps.academic_sessions.models import AnneeAcademique

    active_year = AnneeAcademique.objects.filter(active=True).first()
    system_threshold = get_system_threshold()

    inscriptions_qs = Inscription.objects.select_related("id_cours", "id_etudiant")
    if active_year:
        inscriptions_qs = inscriptions_qs.filter(id_annee=active_year)

    inscription_ids = list(inscriptions_qs.values_list("id_inscription", flat=True))
    # EN_ATTENTE counts as non-justified (loophole closed — consistent with
    # all other views: services.py, views_professor.py, views_student.py).
    absence_sums = dict(
        Absence.objects.filter(
            id_inscription__in=inscription_ids,
            statut__in=["NON_JUSTIFIEE", "EN_ATTENTE"],
        )
        .values("id_inscription")
        .annotate(total=Sum("duree_absence"))
        .values_list("id_inscription", "total")
    )
    at_risk_list = []

    for ins in inscriptions_qs:
        cours = ins.id_cours
        if cours.nombre_total_periodes > 0:
            total_abs = absence_sums.get(ins.id_inscription, 0) or 0

            rate = (total_abs / cours.nombre_total_periodes) * 100
            seuil = (
                cours.seuil_absence
                if cours.seuil_absence is not None
                else system_threshold
            )

            if rate >= seuil:
                at_risk_list.append(
                    {
                        "inscription": ins,
                        "etudiant": ins.id_etudiant,
                        "cours": cours,
                        "total_abs": total_abs,
                        "rate": round(rate, 1),
                        "is_blocked": not ins.exemption_40,
                        "exemption": ins.exemption_40,
                    }
                )

    # Calculate statistics
    blocked_count = sum(1 for item in at_risk_list if item["is_blocked"])
    exempted_count = len(at_risk_list) - blocked_count

    return render(
        request,
        "enrollments/rules_list.html",
        {
            "at_risk_list": at_risk_list,
            "blocked_count": blocked_count,
            "exempted_count": exempted_count,
        },
    )


@login_required
@secretary_required
@require_POST
def toggle_exemption(request, pk):
    """
    Grant or Revoke 40% Exemption.
    """

    inscription = get_object_or_404(Inscription, pk=pk)
    action = request.POST.get("action")  # 'grant' or 'revoke'
    motif = request.POST.get("motif", "").strip()

    if action == "grant":
        if not motif:
            messages.error(request, "Un motif est requis pour accorder une exemption.")
            return redirect("enrollments:rules_management")

        inscription.exemption_40 = True
        inscription.motif_exemption = motif
        inscription.save()
        recalculer_eligibilite(inscription)
        log_action(
            request.user,
            f"Secrétaire a accordé une EXEMPTION 40% à {inscription.id_etudiant.get_full_name()} pour le cours {inscription.id_cours.code_cours}. Motif: {motif}",
            request,
            niveau="WARNING",
            objet_type="INSCRIPTION",
            objet_id=inscription.id_inscription,
        )
        messages.success(
            request,
            f"L'exemption 40% a été accordée avec succès à {inscription.id_etudiant.get_full_name()} pour le cours {inscription.id_cours.code_cours}. "
            f"L'étudiant peut maintenant passer les examens malgré le dépassement du seuil.",
        )

    elif action == "revoke":
        inscription.exemption_40 = False
        inscription.motif_exemption = None
        inscription.save()
        recalculer_eligibilite(inscription)
        log_action(
            request.user,
            f"Secrétaire a RÉVOQUÉ l'exemption 40% de {inscription.id_etudiant.get_full_name()} pour le cours {inscription.id_cours.code_cours}",
            request,
            niveau="WARNING",
            objet_type="INSCRIPTION",
            objet_id=inscription.id_inscription,
        )
        messages.warning(
            request,
            f"L'exemption 40% a été révoquée pour {inscription.id_etudiant.get_full_name()} dans le cours {inscription.id_cours.code_cours}. "
            f"L'étudiant est maintenant bloqué pour les examens.",
        )

    return redirect("enrollments:rules_management")
