"""
Vues de cycle de vie d'une séance QR — apps/absences/views/qr_professor_session.py

Gère la séance de présence QR active après la création du token initial
par ``qr_generate``.

``qr_dashboard``
    Tableau de bord des scans en temps réel. Affiche l'image du QR et la liste
    en direct des étudiants ayant scanné, rafraîchie par polling HTMX. Quand
    l'en-tête ``HX-Request`` est présent, la vue retourne seulement le partiel
    ``_qr_scan_list.html`` au lieu de la page complète (swap HTMX).

``qr_refresh_token``
    Point d'entrée de rotation du token. Invalide le token en cours, génère un
    nouveau token signé avec les mêmes paramètres GPS, et retourne soit une
    charge utile JSON (appel AJAX), soit une redirection (soumission de
    formulaire classique). Les enregistrements de scans existants sont
    préservés — seule l'URL que les étudiants scannent change.

``qr_finalize``
    Point d'entrée de clôture de la séance. Marque comme ABSENT chaque
    étudiant inscrit n'ayant pas scanné, désactive tous les tokens QR
    restants, et verrouille la séance. S'exécute entièrement dans une seule
    transaction atomique pour garantir la cohérence.

Contrôles de sécurité
---------------------
- ``@professor_required`` sur les trois vues.
- Contrôle de propriété : ``course.professeur == request.user`` à chaque requête.
- ``select_for_update()`` dans ``qr_finalize`` empêche qu'une finalisation
  concurrente en doublon ne crée des absences en doublon.

Fait partie du système d'absences UniAbsences.
"""
import logging
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from apps.academic_sessions.models import Seance
from apps.audits.utils import log_action
from apps.dashboard.decorators import professor_required
from apps.enrollments.models import Inscription
from ..models import Absence, QRAttendanceToken, QRScanRecord
from .qr_utils import _generate_qr_data_uri

logger = logging.getLogger(__name__)


@login_required
@professor_required
@require_GET
def qr_dashboard(request, token):
    """
    Tableau de bord en temps réel de la présence QR pour le professeur.

    Rend l'image du QR code aux côtés de deux listes d'étudiants : ceux qui
    ont déjà scanné et ceux qui n'ont pas encore scanné. Les scans suspects
    (étudiants dont la position GPS était éloignée de la salle de cours) sont
    mis en évidence.

    Polling HTMX
    ------------
    Quand la requête porte un en-tête ``HX-Request`` (c.-à-d. un polling HTMX
    périodique depuis la page du tableau de bord), seul le partiel
    ``_qr_scan_list.html`` est retourné afin que le navigateur puisse
    remplacer la liste des scans sur place sans rechargement complet.

    Paramètres
    ----------
    request : HttpRequest
        La requête GET entrante.
    token : UUID
        La valeur ``QRAttendanceToken.token`` issue de l'URL.

    Retour
    ------
    HttpResponse
        Page complète du tableau de bord, ou partiel ``_qr_scan_list.html``
        pour HTMX.

    Lève
    ----
    Http404
        Quand aucun token n'existe avec l'UUID fourni.
    """
    qr_token = get_object_or_404(QRAttendanceToken, token=token)
    seance = qr_token.seance
    course = seance.id_cours

    # Contrôle de propriété — empêche un professeur de consulter le tableau de bord d'un autre cours.
    if course.professeur is None or course.professeur.pk != request.user.pk:
        messages.error(request, "Accès non autorisé.")
        return redirect("dashboard:instructor_dashboard")

    # Construit l'URL de scan absolue qui sera encodée dans l'image du QR.
    scan_url = request.build_absolute_uri(
        reverse("absences:qr_scan", kwargs={"token": str(token)})
    )
    qr_data_uri = _generate_qr_data_uri(scan_url)

    # Récupère toutes les inscriptions pour ce cours et cette année académique.
    inscriptions = list(
        Inscription.objects.filter(
            id_cours=course,
            id_annee=seance.id_annee,
            status=Inscription.Status.EN_COURS,
        ).select_related("id_etudiant")
    )

    # Construit un dictionnaire des scans indexé par la PK d'inscription pour des lookups O(1).
    scan_records = {
        sr.inscription.pk if sr.inscription else None: sr
        for sr in QRScanRecord.objects.filter(seance=seance).select_related("inscription")
    }
    scanned_ids = set(scan_records.keys())

    # Partitionne les inscriptions en listes scanné/non scanné et compte les suspicions.
    scanned = []
    suspicious_count = 0
    for ins in inscriptions:
        if ins.id_inscription in scanned_ids:
            sr = scan_records[ins.id_inscription]
            # Attache l'enregistrement de scan pour que le template puisse accéder au GPS et à l'horodatage.
            setattr(ins, "scan_record", sr)
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
        # Transmet la durée configurée du QR pour que le JavaScript puisse afficher un compte à rebours.
        "qr_duration_seconds": sys_settings.qr_token_duration_seconds,
    }

    # Réponse partielle HTMX : ne retourne que le fragment de liste des scans en cas de polling.
    if request.headers.get("HX-Request"):
        return render(request, "absences/_qr_scan_list.html", ctx)

    return render(request, "absences/qr_dashboard.html", ctx)


@login_required
@professor_required
@require_POST
def qr_refresh_token(request, token):
    """
    Effectue la rotation du token QR actif pour empêcher les étudiants de partager l'image du QR.

    Désactive le token en cours et crée un nouveau token signé avec les mêmes
    paramètres GPS. Les entrées ``QRScanRecord`` existantes sont préservées
    car elles sont liées à la séance, et non au token.

    Format de réponse
    -----------------
    - ``XMLHttpRequest`` (AJAX) — retourne une charge utile JSON contenant
      l'UUID du nouveau token, un data URI du QR fraîchement rendu, toutes les
      URLs pertinentes du tableau de bord, et le nouvel horodatage d'expiration.
    - POST classique (sans en-tête ``X-Requested-With: XMLHttpRequest``) —
      redirige vers le ``qr_dashboard`` mis à jour.

    Paramètres
    ----------
    request : HttpRequest
        La requête POST entrante.
    token : UUID
        La valeur ``QRAttendanceToken.token`` en cours.

    Retour
    ------
    JsonResponse | HttpResponseRedirect
        JSON avec les données du nouveau token pour les appels AJAX, ou
        redirection pour les soumissions de formulaires.

    Lève
    ----
    Http404
        Quand aucun token n'existe avec l'UUID fourni.
    """
    from apps.dashboard.models import SystemSettings

    qr_token = get_object_or_404(QRAttendanceToken, token=token)
    seance = qr_token.seance
    course = seance.id_cours

    # Contrôle de propriété — retourne un JSON 403 pour les appels AJAX, une redirection pour les autres.
    if course.professeur_id != request.user.pk:
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return JsonResponse({"error": "Accès non autorisé."}, status=403)
        messages.error(request, "Accès non autorisé.")
        return redirect("dashboard:instructor_dashboard")

    sys_settings = SystemSettings.get_settings()

    # Préserve les paramètres GPS de l'ancien token pour que l'application de la localisation continue.
    old_verify_location = qr_token.verify_location
    old_lat = qr_token.latitude
    old_lng = qr_token.longitude

    # Désactive tous les tokens actifs pour cette séance avant d'en émettre un nouveau.
    QRAttendanceToken.objects.filter(seance=seance, is_active=True).update(is_active=False)

    new_token = QRAttendanceToken.objects.create(
        seance=seance,
        created_by=request.user,
        expires_at=timezone.now() + timedelta(seconds=sys_settings.qr_token_duration_seconds),
        verify_location=old_verify_location,
        latitude=old_lat,
        longitude=old_lng,
    )

    # Chemin AJAX : retourne du JSON pour que le JavaScript du tableau de bord puisse mettre
    # à jour l'image du QR et le compte à rebours sans rechargement de page.
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
            # URLs pré-construites pour que le client puisse mettre à jour tous les liens du DOM en une fois.
            "refresh_url": reverse("absences:qr_refresh_token", kwargs={"token": str(new_token.token)}),
            "dashboard_url": reverse("absences:qr_dashboard", kwargs={"token": str(new_token.token)}),
            "finalize_url": reverse("absences:qr_finalize", kwargs={"token": str(new_token.token)}),
        })

    # Repli pour soumission de formulaire non-AJAX : redirige vers le tableau de bord mis à jour.
    messages.success(request, "QR code rafraîchi avec un nouveau token.")
    return redirect("absences:qr_dashboard", token=new_token.token)


@login_required
@professor_required
@require_POST
def qr_finalize(request, token):
    """
    Clôture la séance de présence QR et la verrouille définitivement.

    Étapes réalisées dans une seule transaction atomique :

    1. Acquérir un verrou au niveau de la ligne sur l'enregistrement ``Seance``.
    2. Collecter l'ensemble des identifiants d'inscriptions ayant un
       ``QRScanRecord`` (c.-à-d. les étudiants ayant scanné avec succès).
    3. Pour chaque étudiant inscrit **n'étant pas** dans cet ensemble, créer
       un enregistrement ``Absence`` avec
       ``note_professeur = "Absent (QR non scanné)"``.
    4. Désactiver tous les tokens actifs restants pour la séance.
    5. Marquer la séance comme validée (verrouillée définitivement).

    Paramètres
    ----------
    request : HttpRequest
        La requête POST entrante.
    token : UUID
        La valeur ``QRAttendanceToken.token`` identifiant la séance.

    Retour
    ------
    HttpResponseRedirect
        Redirection vers la page de détail du cours pour l'instructeur après
        la finalisation, ou vers le tableau de bord si la séance était déjà
        validée.

    Lève
    ----
    Http404
        Quand aucun token n'existe avec l'UUID fourni.
    """
    qr_token = get_object_or_404(QRAttendanceToken, token=token)
    course = qr_token.seance.id_cours

    # Contrôle de propriété.
    if course.professeur is None or course.professeur.pk != request.user.pk:
        messages.error(request, "Accès non autorisé.")
        return redirect("dashboard:instructor_dashboard")

    with transaction.atomic():
        # Verrouille la ligne de séance pour empêcher une finalisation concurrente.
        seance = Seance.objects.select_for_update().get(pk=qr_token.seance.pk)

        if seance.validated:
            messages.warning(request, "Cette séance est déjà validée.")
            return redirect("dashboard:instructor_course_detail", course.id_cours)

        # Charge toutes les inscriptions actives pour le cours et l'année académique.
        inscriptions = list(
            Inscription.objects.filter(
                id_cours=course,
                id_annee=seance.id_annee,
                status=Inscription.Status.EN_COURS,
            ).select_related("id_etudiant", "id_cours")
        )

        # Collecte toutes les PK d'inscriptions ayant un enregistrement de scan réussi.
        scanned_ids = set(
            QRScanRecord.objects.filter(seance=seance).values_list("inscription_id", flat=True)
        )

        # Désactive tous les tokens dès maintenant — aucun scan n'est plus autorisé après la finalisation.
        QRAttendanceToken.objects.filter(seance=seance, is_active=True).update(is_active=False)

        # Crée un enregistrement d'absence pour chaque étudiant n'ayant pas scanné.
        absent_count = 0
        for ins in inscriptions:
            if ins.id_inscription not in scanned_ids:
                # Utilise la durée calculée de la séance ; replie sur 2h si indisponible.
                duree = seance.duree_heures() or 2.0
                _absence, created = Absence.objects.get_or_create(
                    id_inscription=ins,
                    id_seance=seance,
                    defaults={
                        "type_absence": Absence.TypeAbsence.ABSENT,
                        "duree_absence": duree,
                        "statut": Absence.Statut.NON_JUSTIFIEE,
                        "encodee_par": request.user,
                        "note_professeur": "Absent (QR non scanné)",
                    },
                )
                if created:
                    absent_count += 1

        # Verrouille la séance définitivement.
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
