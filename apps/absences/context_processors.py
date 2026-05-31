"""
Processeurs de contexte de template pour les indicateurs de séances de présence actives.

Ce module expose les séances de présence actives du professeur courant
(basées sur QR ou manuelles) à chaque template via le mécanisme de
context-processor de Django, afin que la barre latérale puisse afficher
une bannière "Reprendre" persistante sans que chaque vue ait à transmettre
explicitement les données.

Responsabilités :
  - Détecter le QRAttendanceToken actif, non expiré, le plus récemment créé
    appartenant au professeur connecté.
  - Détecter les Seances manuelles non validées (brouillons) créées par le
    professeur aujourd'hui.
  - Injecter quatre clés de contexte (active_qr_token, active_qr_url,
    active_manual_seance, active_manual_url) consommées par les templates
    pour afficher l'élément d'UI de reprise de séance.

Seuls les professeurs déclenchent des requêtes BDD ; tous les autres rôles
reçoivent le dict vide de repli, sans surcoût de performance pour les
étudiants, secrétaires ou administrateurs.

Fait partie du système d'absences UniAbsences.
"""

from django.urls import reverse
from django.utils import timezone


def active_qr_session(request):
    """
    Injecte le contexte de séance de présence active dans chaque template pour les professeurs.

    Effectue au maximum deux requêtes BDD légères par requête (une pour le
    token QR actif, une pour les séances manuelles en brouillon) et
    uniquement pour les utilisateurs dont le rôle est PROFESSEUR. Tous les
    autres rôles reçoivent immédiatement des valeurs vides.

    Clés de contexte ajoutées :
      - ``active_qr_token`` (QRAttendanceToken | None) : le token le plus
        récemment créé encore actif et non expiré, ou ``None``.
      - ``active_qr_url`` (str) : URL inverse vers la vue
        ``absences:qr_dashboard`` pour ce token, ou ``""`` si aucun token
        actif.
      - ``active_manual_seance`` (Seance | None) : une séance brouillon
        (``validated=False``) planifiée pour aujourd'hui qui n'a pas déjà un
        token QR actif (pour éviter d'afficher en double les bannières QR
        et manuelle), ou ``None``.
      - ``active_manual_url`` (str) : URL inverse vers la vue
        ``absences:mark_absence`` pour cette séance avec le paramètre de
        query-string ``?date=``, ou ``""`` si aucune séance manuelle active.

    Une séance manuelle est considérée comme active lorsqu'une Seance pour
    aujourd'hui a été créée par le professeur et n'a pas encore été validée
    (``validated=False``), et qu'aucun token QR n'est actuellement actif
    pour la même séance.

    Paramètres :
        request : L'objet Django HttpRequest courant.

    Retourne :
        dict : Un dictionnaire plat de quatre clés de contexte prêt à être
            fusionné dans le contexte de template par le pipeline de
            context-processor de Django.
    """
    # Payload vide par défaut renvoyé pour les utilisateurs non-professeurs et les requêtes non authentifiées.
    empty = {
        "active_qr_token": None,
        "active_qr_url": "",
        "active_manual_seance": None,
        "active_manual_url": "",
    }

    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return empty

    # Skip all DB queries for roles that never have attendance sessions.
    if getattr(user, "role", None) != "PROFESSEUR":
        return empty

    from apps.absences.models import QRAttendanceToken
    from apps.academic_sessions.models import Seance

    # Fetch the most recent non-expired active token for this professor.
    # expires_at__gt=now() is the authoritative expiry check; is_expired
    # (computed property) is not used here to stay within a single DB query.
    token = (
        QRAttendanceToken.objects.filter(
            created_by_id=user.pk,
            is_active=True,
            expires_at__gt=timezone.now(),
        )
        .select_related("seance__id_cours")
        .order_by("-created_at")
        .first()
    )

    # Exclude the session already covered by the QR token to prevent a
    # duplicate "Resume" banner appearing for both QR and manual modes.
    excluded_seance_id = token.seance.pk if token else None

    today = timezone.localdate()
    manual_qs = Seance.objects.filter(
        id_cours__professeur=user,
        date_seance=today,
        validated=False,
    ).select_related("id_cours")
    if excluded_seance_id:
        # Exclude the session that already has an active QR token.
        manual_qs = manual_qs.exclude(id_seance=excluded_seance_id)
    manual_seance = manual_qs.order_by("-id_seance").first()

    result = dict(empty)
    if token:
        result["active_qr_token"] = token
        result["active_qr_url"] = reverse(
            "absences:qr_dashboard", kwargs={"token": str(token.token)}
        )
    if manual_seance:
        result["active_manual_seance"] = manual_seance
        result["active_manual_url"] = (
            reverse(
                "absences:mark_absence",
                kwargs={"course_id": manual_seance.id_cours.pk},
            )
            + f"?date={manual_seance.date_seance.isoformat()}"
        )
    return result
