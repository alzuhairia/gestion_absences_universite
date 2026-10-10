"""
Vues pour les règles de seuil d'absence et la gestion des exemptions d'inscription.

Ce module fournit au secrétariat deux capacités :

1. ``rules_management`` — affiche une liste paginée des inscriptions où le
   taux d'absence non justifiée de l'étudiant atteint ou dépasse le seuil
   du cours (ou du système). Chaque ligne indique si l'étudiant est bloqué
   pour l'examen ou s'il est actuellement protégé par une exemption active.

2. ``toggle_exemption`` — accorde ou révoque l'exemption de 40 % sur une
   inscription donnée. L'octroi nécessite une justification écrite (motif).
   Quand une exemption est accordée, l'étudiant reçoit une notification par
   e-mail et l'action est consignée dans le journal d'audit.

Sécurité : les deux vues exigent ``@secretary_required``.

Appartient à : UniAbsences — application enrollments.
"""

from typing import Any

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction

from apps.utils import safe_get_page
from django.db.models import Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from apps.absences.models import Absence
from apps.absences.services import get_system_threshold, recalculer_eligibilite
from apps.audits.utils import log_action
from apps.dashboard.decorators import secretary_required
from apps.enrollments.models import Inscription
from apps.notifications.email import send_with_dedup


@login_required
@secretary_required
@require_GET
def rules_management(request):
    """
    Affiche les inscriptions où les étudiants atteignent ou dépassent le seuil d'absence.

    Seules les inscriptions ayant le statut ``EN_COURS`` pour l'année
    académique actuellement active sont évaluées. Pour chaque inscription,
    la vue calcule :

    - Le total d'heures d'absences non justifiées sur les séances passées
      (uniquement NON_JUSTIFIEE — les absences au statut EN_ATTENTE sont
      exclues afin qu'une justification en cours d'examen ne signale pas
      à tort un étudiant comme bloqué).
    - Le taux d'absence en pourcentage du nombre total de périodes du cours.
    - Le seuil effectif (``seuil_absence`` au niveau du cours s'il est
      défini, sinon le seuil système renvoyé par ``get_system_threshold()``).
    - Si une exemption est active et sa marge effective.

    Les inscriptions ne sont incluses dans ``at_risk_list`` que lorsque le
    taux brut atteint ou dépasse le seuil de base (même si une exemption
    élève le seuil de blocage effectif au-dessus du taux actuel).

    Paramètres
    ----------
    request : HttpRequest
        Doit être authentifié en tant que secrétaire (GET uniquement).

    Retour
    ------
    HttpResponse
        Rend ``enrollments/rules_list.html`` avec le contexte :
          - ``at_risk_list``    — liste paginée des dicts d'évaluation de risque
          - ``page_obj``        — objet de pagination
          - ``blocked_count``   — nombre d'étudiants entièrement bloqués pour les examens
          - ``exempted_count``  — nombre d'étudiants dont l'exemption les maintient
                                  sous le seuil de blocage effectif
    """
    from apps.academic_sessions.models import AnneeAcademique

    active_year = AnneeAcademique.objects.filter(active=True).first()
    system_threshold = get_system_threshold()

    # Récupère toutes les inscriptions EN_COURS de l'année active, avec les données de cours et d'étudiant.
    inscriptions_qs = Inscription.objects.filter(
        status=Inscription.Status.EN_COURS,
    ).select_related("id_cours", "id_etudiant")
    if active_year:
        inscriptions_qs = inscriptions_qs.filter(id_annee=active_year)

    # Matérialise en liste une seule fois pour pouvoir itérer deux fois (IDs + boucle)
    # sans frapper la base de données deux fois.
    inscriptions_list = list(inscriptions_qs)
    inscription_ids = [ins.id_inscription for ins in inscriptions_list]

    # Agrège les heures d'absence non justifiées par inscription en une seule requête.
    # Strictement NON_JUSTIFIEE — exclure EN_ATTENTE garantit qu'un étudiant dont la
    # justification est encore en cours d'examen ne soit pas pénalisé à tort.
    today = timezone.localdate()
    absence_sums: dict[int, Any] = dict(
        Absence.objects.filter(
            id_inscription__in=inscription_ids,
            statut=Absence.Statut.NON_JUSTIFIEE,
            id_seance__date_seance__lte=today,  # Seules les séances passées comptent.
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

            # Calcule le taux d'absence brut pour cette inscription.
            rate = (total_abs / cours.nombre_total_periodes) * 100

            # Utilise le seuil spécifique au cours s'il est défini ; sinon le défaut système.
            seuil = (
                cours.seuil_absence
                if cours.seuil_absence is not None
                else system_threshold
            )

            # Le seuil effectif est relevé de exemption_margin quand une exemption est
            # active, plafonné à 100 % pour éviter des valeurs absurdes.
            seuil_effectif = min(seuil + ins.exemption_margin, 100) if ins.exemption_40 else seuil

            # On n'inclut l'inscription que lorsque le taux brut atteint le seuil de base.
            if rate >= seuil:
                is_blocked = rate >= seuil_effectif
                # Sous exemption = taux supérieur au seuil de base mais pas au seuil effectif relevé.
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

    # Statistiques résumées pour les badges d'en-tête de page.
    blocked_count = sum(1 for item in at_risk_list if item["is_blocked"])
    exempted_count = sum(1 for item in at_risk_list if item["is_under_exemption"])

    # Pagination à 25 lignes par page.
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
    Accorde ou révoque l'exemption au seuil d'absence pour une inscription.

    Le paramètre POST ``action`` détermine l'opération :
      - ``"grant"`` — positionne ``exemption_40=True`` avec le motif et la marge
        fournis, recalcule l'éligibilité à l'examen, envoie un e-mail à
        l'étudiant et consigne l'action au niveau d'audit WARNING.
      - ``"revoke"`` — efface l'exemption, recalcule l'éligibilité à l'examen
        et consigne l'action au niveau d'audit WARNING.

    L'enregistrement d'inscription est verrouillé avec ``select_for_update()``
    dans une transaction atomique afin d'éviter les conditions de course
    lorsque deux secrétaires agissent simultanément sur la même inscription.

    L'e-mail à l'étudiant est envoyé via ``send_with_dedup`` enregistré comme
    callback ``on_commit`` afin que l'e-mail ne soit envoyé que si la
    transaction est validée avec succès.

    Paramètres
    ----------
    request : HttpRequest
        Paramètres POST :
          - ``action``           (str) — ``"grant"`` ou ``"revoke"``
          - ``motif``            (str) — requis lorsque l'action est ``"grant"``
          - ``exemption_margin`` (int, optionnel) — points de pourcentage
            additionnels au seuil (10 par défaut, borné à [1, 100])
    pk : int
        Clé primaire de l'``Inscription`` à modifier.

    Retour
    ------
    HttpResponseRedirect
        Redirige toujours vers ``dashboard:secretary_seuils_absence``.
    """
    # Vérifie que l'inscription existe avant d'acquérir le moindre verrou.
    get_object_or_404(Inscription, pk=pk)

    action = request.POST.get("action")  # Attendu : 'grant' ou 'revoke'
    motif = request.POST.get("motif", "").strip()

    if action == "grant":
        # Une justification écrite est obligatoire pour la traçabilité d'audit et légale.
        if not motif:
            messages.error(request, "Un motif est requis pour accorder une exemption.")
            return redirect("dashboard:secretary_seuils_absence")
        if len(motif) > 2000:
            messages.error(request, "Le motif ne peut pas dépasser 2000 caractères.")
            return redirect("dashboard:secretary_seuils_absence")

        # Parse la marge ; 10 points de pourcentage par défaut, borné à [1, 100].
        try:
            margin = int(request.POST.get("exemption_margin", 10))
        except (ValueError, TypeError):
            margin = 10
        margin = max(1, min(margin, 100))

        with transaction.atomic():
            # Verrouille la ligne pour empêcher un revoke/grant concurrent depuis une autre session.
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

            # Recalcule le drapeau eligible_examen avec le nouveau seuil effectif.
            recalculer_eligibilite(inscription)

            log_action(
                request.user,
                f"Secrétaire a accordé une EXEMPTION à {inscription.id_etudiant.get_full_name()} pour le cours {inscription.id_cours.code_cours}. Motif: {motif[:200]}",
                request,
                niveau="WARNING",
                objet_type="INSCRIPTION",
                objet_id=inscription.id_inscription,
            )

            # Construit les paramètres de l'e-mail de notification encore à l'intérieur
            # de la transaction afin que les données de FK soient toujours verrouillées et cohérentes.
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
                f"— Système de notification UniAbsences"
            )
            # Diffère l'envoi de l'e-mail jusqu'après la validation de la transaction afin
            # de ne pas notifier pour une transaction susceptible d'être annulée.
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
        # Toute action autre que 'grant' ou 'revoke' est invalide.
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

            # Recalcule l'éligibilité avec l'exemption supprimée — l'étudiant
            # peut désormais passer sous le seuil d'éligibilité à l'examen.
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
