"""
Marquage manuel des présences — vue formulaire pleine page.

``mark_absence``
    Affiche et traite la feuille de présence complète de la classe pour un
    cours donné. Le professeur sélectionne une date et des horaires de
    séance, puis marque chaque étudiant inscrit comme PRÉSENT, ABSENT ou
    PARTIEL (arrivée tardive / départ anticipé).

Règle métier critique
---------------------
Les absences qui ont été encodées par le secrétariat (statut ``JUSTIFIEE``
ou ``EN_ATTENTE``) sont **protégées** : le professeur peut les voir dans la
liste mais ne peut ni les écraser ni les supprimer. Toute soumission
``status_<id>`` ciblant une absence protégée est silencieusement ignorée
dans la transaction.

Flux de travail
---------------
1. Vérifie la propriété du cours (double sécurité au-delà du décorateur).
2. Charge toutes les inscriptions actives pour le cours et l'année académique en cours.
3. Sur POST :
   a. Vérifie qu'aucune clé ``status_*`` ne cible une inscription en dehors
      de ce cours (empêche le tamper de paramètres ; lève ``PermissionDenied``).
   b. Valide et analyse les horaires de séance ; calcule la durée de la séance.
   c. Dans une transaction atomique, ``get_or_create`` l'enregistrement
      ``Seance`` et ``update_or_create`` une ``Absence`` par étudiant absent.
   d. Valide (verrouille) la séance en option si ``form_action == "validate"``.
   e. Déclenche un email de notification pour chaque *nouvel* enregistrement d'absence créé.
4. Sur GET : charge les données de séance existantes pour la date sélectionnée
   afin que le formulaire s'affiche en « mode édition » lorsqu'une séance
   existe déjà.

Fait partie du système de présence UniAbsences.
"""
import datetime
import logging
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

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
    Affiche et traite le formulaire pleine page de présence manuelle pour un cours.

    GET
        Charge la feuille de présence pour la date demandée (``?date=AAAA-MM-JJ``).
        Si une séance existe déjà pour cette date, le formulaire pré-remplit
        avec les horaires enregistrés et toute donnée d'absence existante
        (mode édition).

    POST
        Traite la feuille de présence soumise de manière atomique :
        - Valide la date / les horaires de séance.
        - Crée ou met à jour l'enregistrement ``Seance``.
        - Pour chaque champ ``status_<inscription_id>`` :
            * ``ABSENT`` — ``update_or_create`` une ``Absence`` (ignore les protégées).
            * ``PRESENT`` — supprime toute ``Absence`` existante non protégée.
        - Verrouille la séance en option (``form_action=validate``).
        - Envoie un email de notification pour chaque absence nouvellement créée.

    Sécurité
    --------
    - La propriété du cours est vérifiée contre ``request.user`` avant traitement.
    - Les identifiants d'inscription dans les données POST sont validés contre
      le queryset propre au cours ; tout ID inconnu lève ``PermissionDenied``.

    Paramètres
    ----------
    request : HttpRequest
        La requête HTTP entrante.
    course_id : int
        Clé primaire de l'enregistrement ``Cours`` dont la présence est enregistrée.

    Retour
    ------
    HttpResponse
        Formulaire de présence rendu sur GET ou redirection sur POST réussi.

    Lève
    ----
    Http404
        Quand aucun ``Cours`` n'existe avec ``course_id``.
    PermissionDenied
        Quand une soumission POST contient des identifiants d'inscription
        en dehors de ce cours.
    """
    course = get_object_or_404(Cours, id_cours=course_id)

    # Contrôle de propriété secondaire — le décorateur ne vérifie que le rôle,
    # pas quel cours appartient à quel professeur.
    if course.professeur != request.user:
        messages.error(request, "Accès non autorisé à ce cours.")
        return redirect("dashboard:instructor_dashboard")

    active_year = AnneeAcademique.objects.filter(active=True).first()

    # Construit le queryset d'inscriptions filtré sur l'année académique active.
    inscriptions_qs = Inscription.objects.filter(
        id_cours=course, status=Inscription.Status.EN_COURS
    ).select_related("id_etudiant")
    if active_year:
        inscriptions_qs = inscriptions_qs.filter(id_annee=active_year)

    # Indexé par PK en chaîne pour un lookup O(1) lors de l'itération des champs POST.
    inscriptions_by_id = {str(ins.id_inscription): ins for ins in inscriptions_qs}

    if request.method == "POST":
        # Pré-vérification : si la séance est déjà validée pour cette date, on sort tôt
        # avant d'acquérir le moindre verrou — économise un aller-retour dans le cas commun.
        check_date = request.POST.get("date_seance", "").strip()
        if check_date:
            validated_seance = Seance.objects.filter(
                id_cours=course, date_seance=check_date, validated=True
            ).first()
            if validated_seance:
                messages.error(request, "Cette séance a déjà été validée.")
                return redirect("absences:mark_absence", course_id=course_id)

        # Sécurité : collecte tout identifiant d'inscription dans POST qui n'appartient pas
        # à ce cours. S'il en existe, journalise et lève immédiatement PermissionDenied.
        invalid_ids = [
            key.split("_", 1)[1]
            for key in request.POST.keys()
            if key.startswith("status_") and key.split("_", 1)[1] not in inscriptions_by_id
        ]
        if invalid_ids:
            log_action(
                request.user,
                f"Tentative d'accès à des inscriptions non autorisées : {', '.join(invalid_ids)}",
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

        # Analyse les horaires au format HH:MM ; rejette immédiatement tout autre format.
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

        # Calcule la durée de séance en heures décimales (utilisée comme durée d'absence par défaut).
        duree_seance = Decimal((t_fin - t_debut).seconds) / Decimal(3600)
        duree_seance = duree_seance.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        annee = AnneeAcademique.objects.filter(active=True).first()
        if not annee:
            messages.error(request, "Aucune année académique active.")
            return redirect("absences:mark_absence", course_id=course_id)

        with transaction.atomic():
            seance_created = False
            try:
                # Tente de récupérer une séance existante pour cette date et ce cours.
                # select_for_update() empêche une course concurrente sur la même séance.
                seance = Seance.objects.select_for_update().get(date_seance=date_seance, id_cours=course)
                if seance.validated:
                    # Un autre utilisateur a pu la valider entre notre vérification précédente
                    # et l'acquisition du verrou — on abandonne proprement.
                    messages.error(request, "Cette séance a été validée entre-temps.")
                    return redirect("absences:mark_absence", course_id=course_id)

                # Met à jour les horaires de séance uniquement s'ils ont réellement changé.
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
                # Pas encore de séance pour cette date — en créer une.
                seance = Seance.objects.create(
                    date_seance=date_seance,
                    heure_debut=heure_debut,
                    heure_fin=heure_fin,
                    id_cours=course,
                    id_annee=annee,
                )
                seance_created = True

            # Itère sur chaque champ status_<id> dans le corps du POST.
            for key, value in request.POST.items():
                if not key.startswith("status_"):
                    continue

                inscription_id = key.split("_", 1)[1]
                status = value
                inscription = inscriptions_by_id.get(inscription_id)
                if not inscription:
                    # Ne devrait pas arriver (déjà validé ci-dessus), mais on se protège tout de même.
                    continue

                # Recherche toute absence précédemment enregistrée pour cet étudiant + cette séance.
                existing_absence = Absence.objects.filter(
                    id_inscription=inscription, id_seance=seance
                ).first()
                is_prof = request.user.role == User.Role.PROFESSEUR

                if status == "ABSENT":
                    # Seuls ABSENT et PARTIEL sont des valeurs de type valides pour la saisie professeur.
                    _ALLOWED_TYPES = {Absence.TypeAbsence.ABSENT, Absence.TypeAbsence.PARTIEL}
                    type_absence = request.POST.get(f"type_{inscription_id}", Absence.TypeAbsence.ABSENT)
                    if type_absence not in _ALLOWED_TYPES:
                        type_absence = Absence.TypeAbsence.ABSENT

                    # Durée par défaut = séance complète ; surchargée pour PARTIEL.
                    duree = duree_seance
                    if type_absence == Absence.TypeAbsence.PARTIEL:
                        try:
                            duree = Decimal(
                                str(float(request.POST.get(f"duree_{inscription_id}", 0)))
                            ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                            if duree <= 0 or duree > duree_seance:
                                raise ValueError("plage invalide")
                        except (TypeError, ValueError):
                            # Repli sur la durée complète de séance et avertissement du professeur.
                            duree = duree_seance
                            messages.warning(
                                request,
                                f"Durée invalide pour {inscription.id_etudiant.get_full_name()} "
                                f"— absence complète ({duree_seance}h) appliquée par défaut.",
                            )

                    # CRITIQUE : ne pas écraser les absences encodées par le secrétariat.
                    if existing_absence and existing_absence.statut in (
                        Absence.Statut.JUSTIFIEE, Absence.Statut.EN_ATTENTE
                    ):
                        continue  # On ignore — absence encodée par le secrétariat protégée.

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
                        # Rare mais possible si deux requêtes se concurrencent sur le même enregistrement.
                        messages.warning(
                            request,
                            f"Absence déjà enregistrée pour {inscription.id_etudiant.get_full_name()} (doublon ignoré).",
                        )
                        continue

                    # Journalise chaque enregistrement d'absence individuel créé par le professeur.
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

                    # Envoie un email de notification uniquement pour les absences toutes neuves.
                    # La déduplication via event_key empêche les emails en doublon quand le
                    # professeur enregistre le même formulaire plusieurs fois.
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
                    # L'étudiant est marqué PRÉSENT — retire toute absence existante non protégée.
                    if existing_absence:
                        if existing_absence.statut in (Absence.Statut.JUSTIFIEE, Absence.Statut.EN_ATTENTE):
                            continue  # Protégée — ne pas supprimer une absence encodée par le secrétariat.
                        existing_absence.delete()

            # Journalise la création de séance et la soumission de présence au niveau séance.
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

            # L'action « validate » verrouille définitivement la séance ; « draft » la garde éditable.
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

            # Redirige vers la même date afin que le professeur puisse vérifier le résultat.
            return redirect(f"{reverse('absences:mark_absence', args=[course_id])}?date={date_seance}")

    # --- GET ---
    students = inscriptions_qs.order_by("id_etudiant__nom")

    # Résout la date demandée depuis la query string ; repli sur aujourd'hui.
    today = request.GET.get("date", "")
    try:
        datetime.date.fromisoformat(today)
    except (ValueError, TypeError):
        today = timezone.now().strftime("%Y-%m-%d")
    default_start = "08:30"
    default_end = "10:30"

    # Tente de charger une séance existante pour la date sélectionnée.
    try:
        existing_seance = Seance.objects.get(id_cours=course, date_seance=today)
    except Seance.DoesNotExist:
        existing_seance = None

    existing_absences: dict[int, Any] = {}
    is_edit_mode = False
    is_validated = False

    if existing_seance:
        is_edit_mode = True
        is_validated = existing_seance.validated

        # Pré-remplit les champs heure de début/fin depuis la séance stockée.
        if existing_seance.heure_debut:
            default_start = existing_seance.heure_debut.strftime("%H:%M")
        if existing_seance.heure_fin:
            default_end = existing_seance.heure_fin.strftime("%H:%M")

        # Construit un dict indexé par PK d'inscription pour un lookup O(1) côté template.
        abs_list = Absence.objects.filter(id_seance=existing_seance).select_related("encodee_par")
        for ab in abs_list:
            existing_absences[ab.id_inscription.pk] = {
                "type": ab.type_absence,
                "duree": ab.duree_absence,
                "statut": ab.statut,
                "note_professeur": ab.note_professeur,
                "encodee_par": ab.encodee_par,
            }

    # Attache les données d'absence directement à chaque inscription pour simplifier la logique du template.
    for ins in students:
        setattr(ins, "absence_data", existing_absences.get(ins.id_inscription))

    # Compteurs récapitulatifs pour la bannière en haut du formulaire.
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
