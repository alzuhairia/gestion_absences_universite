"""
Context processors pour exposer l'etat des sessions de presence (QR + appel manuel)
dans les templates.
"""

from django.urls import reverse
from django.utils import timezone


def active_qr_session(request):
    """
    Expose les sessions de presence actives (QR ou appel manuel) du professeur
    connecte, afin que la sidebar puisse afficher un indicateur "Reprendre".

    Cles ajoutees au contexte :
      - active_qr_token : instance QRAttendanceToken ou None
      - active_qr_url : URL vers le qr_dashboard correspondant ou ""
      - active_manual_seance : Seance brouillon (validated=False) du jour ou None
      - active_manual_url : URL vers mark_absence?date=... ou ""

    Une session manuelle est consideree active si une Seance pour aujourd'hui
    a ete enregistree comme brouillon par le professeur sans avoir ete validee
    et sans QR actif (pour eviter de doubler la banniere QR/Manuel).

    Limite aux utilisateurs ayant le role PROFESSEUR pour eviter des requetes
    inutiles sur les autres roles.
    """
    empty = {
        "active_qr_token": None,
        "active_qr_url": "",
        "active_manual_seance": None,
        "active_manual_url": "",
    }

    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return empty

    if getattr(user, "role", None) != "PROFESSEUR":
        return empty

    from apps.absences.models import QRAttendanceToken
    from apps.academic_sessions.models import Seance

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

    excluded_seance_id = token.seance_id if token else None

    today = timezone.localdate()
    manual_qs = Seance.objects.filter(
        id_cours__professeur=user,
        date_seance=today,
        validated=False,
    ).select_related("id_cours")
    if excluded_seance_id:
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
                kwargs={"course_id": manual_seance.id_cours_id},
            )
            + f"?date={manual_seance.date_seance.isoformat()}"
        )
    return result
