from django.db.models import Sum

from apps.audits.models import LogAudit
from apps.notifications.models import Notification

from .models import Absence


def calculer_absence_stats(inscription):
    """
    Calcule les statistiques d'absence pour une inscription.

    Retourne:
        dict: {
            'total_absence': float,
            'taux': float,
            'total_periodes': int,
        }
    """
    # CORRECTION BUG CRITIQUE #3 — EN_ATTENTE compte comme NON_JUSTIFIEE
    # Un étudiant soumettant un justificatif non validé ne doit pas voir son taux
    # d'absence baisser. L'absence est décomptée UNIQUEMENT après acceptation
    # (state=ACCEPTEE → statut=JUSTIFIEE). Jusqu'alors, EN_ATTENTE = non justifiée.
    total_absence = (
        Absence.objects.filter(
            id_inscription=inscription, statut__in=["NON_JUSTIFIEE", "EN_ATTENTE"]
        ).aggregate(total=Sum("duree_absence"))["total"]
        or 0
    )

    total_periodes = inscription.id_cours.nombre_total_periodes or 0
    taux = (total_absence / total_periodes) * 100 if total_periodes else 0

    return {
        "total_absence": total_absence,
        "taux": taux,
        "total_periodes": total_periodes,
    }


def get_absences_queryset(inscription):
    """
    Retourne un queryset optimisé pour afficher les absences d'une inscription.
    Évite les N+1 via select_related/prefetch_related.
    """
    return (
        Absence.objects.filter(id_inscription=inscription)
        .select_related("id_seance", "id_seance__id_cours")
        .prefetch_related("justification")
        .order_by("-id_seance__date_seance")
    )


def recalculer_eligibilite(inscription):
    """
    Recalcule l'éligibilité d'un étudiant à l'examen basé sur ses absences non justifiées.

    IMPORTANT POUR LA SOUTENANCE :
    Cette fonction implémente la règle métier du seuil d'absence :
    - Un étudiant est bloqué (non éligible) si son taux d'absence >= seuil (40% par défaut)
    - Exception : si l'étudiant a une exemption (exemption_40 = True)
    - Le calcul se base UNIQUEMENT sur les absences NON JUSTIFIÉES

    Logique métier :
    1. Calculer le total des heures d'absences NON JUSTIFIÉES
    2. Calculer le taux : (heures absences / total périodes) * 100
    3. Comparer avec le seuil (personnalisé par cours ou défaut système)
    4. Si taux >= seuil ET pas d'exemption :
       - Bloquer l'étudiant (eligible_examen = False)
       - Envoyer une notification
       - Logger dans l'audit
    5. Sinon :
       - Débloquer l'étudiant si nécessaire (eligible_examen = True)
       - Envoyer une notification de déblocage

    Appel automatique :
    - Cette fonction est appelée automatiquement via un signal Django
    - Signal : post_save sur le modèle Absence
    - Garantit la cohérence des données après chaque modification d'absence

    Args:
        inscription: Instance de Inscription à recalculer

    Returns:
        None (modifie directement l'objet inscription)
    """
    stats = calculer_absence_stats(inscription)
    total_absence = stats["total_absence"]
    taux = stats["taux"]
    total_periodes = stats["total_periodes"]

    cours = inscription.id_cours

    # Vérifier que le cours a des périodes
    if total_periodes == 0:
        # Si pas de périodes, l'étudiant est éligible
        if not inscription.eligible_examen:
            inscription.eligible_examen = True
            inscription.save(update_fields=["eligible_examen"])
        return

    # Utiliser le seuil du cours (ou le seuil par défaut)
    seuil = cours.get_seuil_absence()

    # 2. Logique de blocage / déblocage
    if taux >= seuil and not inscription.exemption_40:
        # Étudiant dépasse le seuil et n'a pas d'exemption
        if inscription.eligible_examen:
            inscription.eligible_examen = False
            inscription.save(update_fields=["eligible_examen"])

            # Notification à l'étudiant
            Notification.objects.create(
                id_utilisateur=inscription.id_etudiant,
                message=f"ALERTE : Seuil de {seuil}% dépassé pour {cours.nom_cours}. Examen bloqué.",
                type="ALERTE",
            )

            # Log d'Audit
            LogAudit.objects.create(
                id_utilisateur=inscription.id_etudiant,
                action=f"CRITIQUE: Blocage automatique examen - {cours.nom_cours} (Taux: {taux:.1f}%, Seuil: {seuil}%)",
                # CORRECTION BUG CRITIQUE #5 — IP système (action automatique, pas d'utilisateur connecté)
                # "0.0.0.0" est la convention pour les actions système automatiques dans ce projet.
                adresse_ip="0.0.0.0",
                niveau="CRITIQUE",
                objet_type="INSCRIPTION",
                objet_id=inscription.id_inscription,
            )
    else:
        # Étudiant est sous le seuil ou a une exemption
        if not inscription.eligible_examen:
            inscription.eligible_examen = True
            inscription.save(update_fields=["eligible_examen"])

            # Notification de déblocage
            Notification.objects.create(
                id_utilisateur=inscription.id_etudiant,
                message=f"Information : Vous êtes à nouveau éligible à l'examen pour {cours.nom_cours}.",
                type="INFO",
            )


def get_system_threshold():
    """
    FIX VERT #15 — Récupère le seuil d'absence par défaut du système en une seule requête.
    Centralisé ici pour éviter de répéter l'import et l'appel dans chaque vue.
    """
    from apps.dashboard.models import SystemSettings

    return SystemSettings.get_settings().default_absence_threshold


def calculer_risque_inscription(inscription, system_threshold=None):
    """
    FIX VERT #15 — Calcul centralisé du statut de risque d'une inscription.

    Avant : logique dupliquée dans 8+ vues (student_dashboard, secretary_rules_40,
    instructor_courses, etc.), chacune réimplémentant le même calcul parfois de façon
    incohérente (seuil hardcodé 40% avant les corrections critiques).

    Après : source unique de vérité pour le calcul de risque.

    Args:
        inscription: Instance d'Inscription (doit avoir id_cours chargé)
        system_threshold: Seuil système pré-chargé (optionnel, évite N appels DB en boucle)

    Returns:
        dict: {
            'is_at_risk': bool,
            'is_blocked': bool,      # Bloqué = à risque ET pas exempté
            'taux': float,           # Taux d'absence en %
            'seuil': int,            # Seuil applicable (cours ou système)
            'total_absence': float,  # Heures d'absence comptabilisées
            'total_periodes': int,   # Total périodes du cours
        }
    """
    if system_threshold is None:
        system_threshold = get_system_threshold()

    cours = inscription.id_cours
    # Seuil personnalisé du cours, ou seuil système par défaut
    seuil = cours.seuil_absence if cours.seuil_absence is not None else system_threshold

    stats = calculer_absence_stats(inscription)
    taux = stats["taux"]
    is_at_risk = taux >= seuil
    is_blocked = is_at_risk and not inscription.exemption_40

    return {
        "is_at_risk": is_at_risk,
        "is_blocked": is_blocked,
        "taux": round(taux, 1),
        "seuil": seuil,
        "total_absence": stats["total_absence"],
        "total_periodes": stats["total_periodes"],
    }


def get_at_risk_count_for_queryset(inscriptions_qs, system_threshold=None):
    """
    FIX VERT #15 — Compte les inscriptions à risque dans un queryset.

    Optimisé pour les vues dashboard : pré-charge le seuil système une seule fois,
    et effectue la sommation des absences en une seule requête SQL agrégée.

    Args:
        inscriptions_qs: QuerySet d'Inscription filtré (doit inclure select_related id_cours)
        system_threshold: Seuil système pré-chargé (optionnel)

    Returns:
        tuple: (at_risk_count: int, absence_sums: dict {id_inscription: total_heures})
    """
    if system_threshold is None:
        system_threshold = get_system_threshold()

    inscription_ids = list(inscriptions_qs.values_list("id_inscription", flat=True))
    if not inscription_ids:
        return 0, {}

    # Agrégation SQL unique pour toutes les absences (EN_ATTENTE + NON_JUSTIFIEE)
    absence_sums = dict(
        Absence.objects.filter(
            id_inscription__in=inscription_ids,
            statut__in=[
                "NON_JUSTIFIEE",
                "EN_ATTENTE",
            ],  # EN_ATTENTE compte (loophole fermé)
        )
        .values("id_inscription")
        .annotate(total=Sum("duree_absence"))
        .values_list("id_inscription", "total")
    )

    at_risk_count = 0
    for ins in inscriptions_qs:
        cours = ins.id_cours
        if not cours.nombre_total_periodes:
            continue
        seuil = (
            cours.seuil_absence if cours.seuil_absence is not None else system_threshold
        )
        total_abs = absence_sums.get(ins.id_inscription, 0) or 0
        taux = (total_abs / cours.nombre_total_periodes) * 100
        if taux >= seuil and not ins.exemption_40:
            at_risk_count += 1

    return at_risk_count, absence_sums
