"""
Vues de création et de validation de séance — apps/absences/views/professor_session.py

Fournit la gestion du cycle de vie d'une séance côté professeur :

``session_create``
    Point d'entrée unifié où le professeur crée une séance (ou récupère une
    séance existante pour la même date et le même cours) puis choisit le
    mode de saisie de présence — formulaire manuel ou scanner de QR code.
    L'enregistrement ``Seance`` est persisté en base avant la redirection
    de mode pour que les deux chemins partagent une source de vérité unique.

``validate_session``
    Verrouille définitivement une séance. Après validation, le professeur
    ne peut plus modifier les absences pour cette séance ; l'enregistrement
    devient en lecture seule.

Notes de conception
-------------------
- ``session_create`` désactive tout token QR actif existant pour la séance
  avant d'en créer un nouveau, garantissant qu'un seul token actif existe
  à la fois.
- ``validate_session`` utilise ``select_for_update()`` pour empêcher deux
  requêtes simultanées de double-valider la même séance.
- Les coordonnées GPS et le drapeau ``verify_location`` sont transmis du
  formulaire au nouveau ``QRAttendanceToken`` afin que le point d'entrée
  de scan QR puisse imposer la vérification de proximité au campus.

Fait partie du système d'absences UniAbsences.
"""
import datetime
import logging
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_POST

from ..models import QRAttendanceToken
from apps.academic_sessions.models import AnneeAcademique, Seance
from apps.academics.models import Cours
from apps.audits.utils import log_action
from apps.dashboard.decorators import professor_required

logger = logging.getLogger(__name__)


@login_required
@professor_required
@require_http_methods(["GET", "POST"])
def session_create(request, course_id):
    """
    Point d'entrée unifié de création de séance pour les professeurs.

    GET
        Affiche le formulaire de création de séance avec la date du jour et
        les horaires par défaut pré-remplis. Le professeur sélectionne la
        date, les horaires de début/fin et le mode de saisie de présence
        (manuel ou QR).

    POST
        1. Valide la date et les horaires soumis.
        2. Crée ou met à jour l'enregistrement ``Seance`` pour la date et le
           cours donnés.
        3. Redirige selon le mode choisi :
           - ``manual`` → redirige vers ``mark_absence`` (formulaire pleine page).
           - ``qr``     → crée (ou reprend) un ``QRAttendanceToken`` et
                          redirige vers ``qr_dashboard``.

    Détails du mode QR
    ------------------
    - Si un token actif et non expiré existe déjà pour la séance, le
      professeur est redirigé pour le reprendre plutôt que d'en créer un en doublon.
    - Tout token actif antérieur pour la séance est désactivé avant la
      création d'un nouveau token (un seul token actif par séance à la fois).
    - Les coordonnées GPS et le drapeau ``verify_location`` sont transmis au
      nouveau token s'ils sont fournis par le client.

    Paramètres
    ----------
    request : HttpRequest
        La requête HTTP entrante.
    course_id : int
        Clé primaire du ``Cours`` pour lequel la séance est créée.

    Retour
    ------
    HttpResponse
        Formulaire rendu sur GET, ou redirection vers la vue de présence
        appropriée sur POST.

    Lève
    ----
    Http404
        Quand aucun ``Cours`` n'existe avec ``course_id``.
    """
    course = get_object_or_404(Cours, id_cours=course_id)

    # Contrôle de propriété — le décorateur ne vérifie que le rôle PROFESSEUR.
    if course.professeur is None or course.professeur.pk != request.user.pk:
        messages.error(request, "Accès non autorisé à ce cours.")
        return redirect("dashboard:instructor_dashboard")

    academic_year = AnneeAcademique.objects.filter(active=True).first()
    if not academic_year:
        messages.error(request, "Aucune année académique active.")
        return redirect("dashboard:instructor_course_detail", course_id)

    if request.method == "POST":
        date_seance = request.POST.get("date_seance", "").strip()
        heure_debut = request.POST.get("heure_debut", "").strip()
        heure_fin = request.POST.get("heure_fin", "").strip()
        mode = request.POST.get("mode", "manual")

        if not all([date_seance, heure_debut, heure_fin]):
            messages.error(request, "Veuillez remplir tous les champs obligatoires.")
            return redirect("absences:session_create", course_id=course_id)

        # Valide le format des horaires avant de toucher à la base de données.
        try:
            fmt = "%H:%M"
            t_debut = datetime.datetime.strptime(heure_debut, fmt)
            t_fin = datetime.datetime.strptime(heure_fin, fmt)
        except (TypeError, ValueError):
            messages.error(request, "Format d'heure invalide (HH:MM attendu).")
            return redirect("absences:session_create", course_id=course_id)

        if t_fin <= t_debut:
            messages.error(request, "L'heure de fin doit être postérieure à l'heure de début.")
            return redirect("absences:session_create", course_id=course_id)

        # Récupère une séance existante pour cette date ou en crée une nouvelle.
        try:
            seance = Seance.objects.get(id_cours=course, date_seance=date_seance)
            # Met à jour les horaires uniquement s'ils diffèrent pour éviter des écritures inutiles.
            updated_fields = []
            if seance.heure_debut != t_debut.time():
                seance.heure_debut = heure_debut
                updated_fields.append("heure_debut")
            if seance.heure_fin != t_fin.time():
                seance.heure_fin = heure_fin
                updated_fields.append("heure_fin")
            if updated_fields:
                seance.save(update_fields=updated_fields)
            messages.info(request, "Séance existante récupérée.")
        except Seance.DoesNotExist:
            seance = Seance.objects.create(
                id_cours=course,
                date_seance=date_seance,
                heure_debut=heure_debut,
                heure_fin=heure_fin,
                id_annee=academic_year,
            )

        # Empêche toute modification sur une séance déjà validée.
        if seance.validated:
            messages.error(request, "Cette séance est déjà validée et verrouillée.")
            return redirect("dashboard:instructor_course_detail", course_id)

        if mode == "qr":
            # Reprend un token actif s'il en existe déjà un pour cette séance,
            # plutôt que d'en créer un en doublon.
            existing_token = (
                QRAttendanceToken.objects.filter(
                    seance=seance,
                    is_active=True,
                    expires_at__gt=timezone.now(),
                )
                .order_by("-created_at")
                .first()
            )
            if existing_token:
                messages.info(request, "Un QR de présence est déjà actif — reprise en cours.")
                return redirect("absences:qr_dashboard", token=existing_token.token)

            from apps.dashboard.models import SystemSettings
            sys_settings = SystemSettings.get_settings()
            verify_location = request.POST.get("verify_location") == "on"

            # Désactive tout token actif obsolète avant de créer le nouveau.
            QRAttendanceToken.objects.filter(seance=seance, is_active=True).update(is_active=False)

            token_kwargs = {
                "seance": seance,
                "created_by": request.user,
                "expires_at": timezone.now() + timedelta(seconds=sys_settings.qr_token_duration_seconds),
                "verify_location": verify_location,
            }

            # Attache les coordonnées GPS au token uniquement si lat et lng sont fournies
            # et peuvent être analysées comme floats ; ignore silencieusement les valeurs invalides.
            try:
                lat = request.POST.get("latitude")
                lng = request.POST.get("longitude")
                if lat and lng:
                    token_kwargs["latitude"] = float(lat)
                    token_kwargs["longitude"] = float(lng)
            except (ValueError, TypeError):
                pass

            new_token = QRAttendanceToken.objects.create(**token_kwargs)
            log_action(
                request.user,
                f"Séance créée (QR) — {course.code_cours} {date_seance}",
                request,
                niveau="INFO",
                objet_type="SEANCE",
                objet_id=seance.id_seance,
            )
            return redirect("absences:qr_dashboard", token=new_token.token)
        else:
            # Mode manuel — envoie directement le professeur vers le formulaire de présence.
            log_action(
                request.user,
                f"Séance créée (manuel) — {course.code_cours} {date_seance}",
                request,
                niveau="INFO",
                objet_type="SEANCE",
                objet_id=seance.id_seance,
            )
            return redirect(
                f"{reverse('absences:mark_absence', args=[course_id])}?date={date_seance}"
            )

    # GET — rend le formulaire avec la date du jour et des horaires par défaut raisonnables.
    today = timezone.localdate().isoformat()
    return render(request, "absences/session_create.html", {
        "course": course,
        "today": today,
        "default_start": "08:30",
        "default_end": "10:30",
    })


@login_required
@professor_required
@require_POST
def validate_session(request, seance_id):
    """
    Verrouille définitivement une séance afin que ses enregistrements de présence deviennent en lecture seule.

    Une fois validée, le professeur ne peut plus créer, mettre à jour ou
    supprimer des absences pour la séance. Cette action est irréversible
    via l'interface normale.

    Un verrou ``select_for_update()`` est acquis dans la transaction pour
    empêcher deux requêtes concurrentes de double-valider la même séance
    (ex. le professeur clique deux fois sur « Valider » en succession rapide).

    Paramètres
    ----------
    request : HttpRequest
        La requête POST entrante.
    seance_id : int
        Clé primaire de la ``Seance`` à valider.

    Retour
    ------
    HttpResponse
        Redirige vers le formulaire de présence pour le cours de la séance
        en cas de succès ou si la séance était déjà validée.

    Lève
    ----
    Http404
        Quand aucune ``Seance`` n'existe avec ``seance_id``.
    """
    seance = get_object_or_404(Seance, pk=seance_id)

    # Vérifie que le professeur est propriétaire du cours de cette séance.
    if seance.id_cours.professeur != request.user:
        messages.error(request, "Accès non autorisé à cette séance.")
        return redirect("dashboard:instructor_dashboard")

    with transaction.atomic():
        # Recharge avec un verrou au niveau ligne pour empêcher la double-validation concurrente.
        seance = Seance.objects.select_for_update().get(pk=seance_id)
        if seance.validated:
            messages.info(request, "Cette séance est déjà validée.")
            return redirect("absences:mark_absence", course_id=seance.id_cours.pk)

        seance.validated = True
        seance.validated_by = request.user
        seance.date_validated = timezone.now()
        seance.save(update_fields=["validated", "validated_by", "date_validated"])

        log_action(
            request.user,
            f"Professeur a validé la séance du {seance.date_seance} pour {seance.id_cours.code_cours}",
            request,
            niveau="INFO",
            objet_type="SEANCE",
            objet_id=seance.id_seance,
        )

    messages.success(
        request,
        f"La séance du {seance.date_seance} a été validée. Les présences sont verrouillées.",
    )
    return redirect("absences:mark_absence", course_id=seance.id_cours.pk)
