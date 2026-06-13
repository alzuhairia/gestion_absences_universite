"""
Vues d'édition directe admin / secrétariat — apps/absences/views/admin_views.py

Fournit au secrétariat la possibilité de modifier directement un
enregistrement d'absence existant (type, statut, durée) en imposant un
motif d'audit obligatoire. Chaque changement est écrit dans le journal
d'audit via ``log_action``.

Décisions de conception clés
----------------------------
- ``_VALID_TYPES`` et ``_VALID_STATUTS`` sont des constantes au niveau du
  module afin que la logique de validation ne construise pas de nouveaux
  ensembles à chaque requête.
- ``select_for_update()`` à l'intérieur de la transaction empêche une
  condition de course TOCTOU où deux secrétaires pourraient éditer le même
  enregistrement simultanément.
- La machine à états de la ``Justification`` est tenue synchrone à chaque
  changement de statut de l'absence, afin que les deux modèles ne
  divergent jamais.
- Les emails ne sont volontairement *pas* envoyés ici ; le secrétariat
  effectue une correction administrative, il ne répond pas à une
  soumission étudiante.

Contrôles de sécurité
---------------------
- ``@secretary_required`` — seul le rôle secrétariat peut accéder à cette vue.
- ``select_for_update()`` — verrou au niveau ligne empêche les éditions concurrentes.
- Validation complète du modèle et contrôles par liste blanche avant toute
  écriture en base.

Fait partie du système d'absences UniAbsences.
"""
import logging
from decimal import Decimal, ROUND_HALF_UP

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from apps.audits.utils import log_action
from apps.dashboard.decorators import secretary_required

from ..models import Absence, Justification

logger = logging.getLogger(__name__)

# Liste blanche des types d'absence que le secrétariat est autorisé à définir directement.
_VALID_TYPES = {Absence.TypeAbsence.ABSENT, Absence.TypeAbsence.PARTIEL}

# Liste blanche de toutes les valeurs de statut d'absence valides, dérivée de l'enum du modèle.
_VALID_STATUTS = set(Absence.Statut.values)


def _get_seance_duration(seance):
    """
    Calcule la durée d'une séance en heures décimales pour l'affichage et la validation.

    Combine ``heure_debut`` et ``heure_fin`` avec une date arbitraire afin
    que l'arithmétique ``timedelta`` de Python puisse être appliquée à des
    objets ``time``.

    Paramètres
    ----------
    seance : Seance
        La séance dont les horaires début/fin sont inspectés.

    Retour
    ------
    tuple[float | None, str | None]
        Une paire ``(heures_decimales, "HH:MM")``, ou ``(None, None)`` quand
        la séance n'a pas de plage horaire valide.
    """
    if seance.heure_debut and seance.heure_fin:
        from datetime import datetime, date
        # Utilise une date arbitraire pour pouvoir soustraire deux objets time via datetime.
        dt_debut = datetime.combine(date.today(), seance.heure_debut)
        dt_fin = datetime.combine(date.today(), seance.heure_fin)
        total_seconds = (dt_fin - dt_debut).seconds
        hours = round(total_seconds / 3600.0, 2)
        if hours > 0:
            h = total_seconds // 3600
            m = (total_seconds % 3600) // 60
            return hours, f"{h:02d}:{m:02d}"
    return None, None


@login_required
@secretary_required
@require_http_methods(["GET", "POST"])
def edit_absence(request, pk):
    """
    Permet au secrétariat de modifier directement un enregistrement d'absence existant.

    Un motif (``reason``) non vide est obligatoire pour chaque changement ;
    la motivation est écrite dans le journal d'audit afin que toute
    modification soit entièrement traçable.

    GET
        Affiche le formulaire d'édition pré-rempli avec les valeurs courantes
        de l'absence et la durée calculée de la séance pour référence.

    POST
        Valide tous les champs soumis, acquiert un verrou au niveau ligne,
        applique les changements atomiquement, tient à jour la machine à
        états de la ``Justification``, écrit une entrée d'audit, et
        redirige vers la liste de validation.

    Règles métier appliquées
    ------------------------
    - Une absence au statut ``JUSTIFIEE`` ne peut pas être éditée directement ;
      le secrétariat doit d'abord changer son statut via le workflow de
      justification.
    - La nouvelle durée doit être positive et ne doit pas dépasser la durée
      de la séance.
    - Les valeurs de type et de statut sont validées contre des listes
      blanches côté serveur.

    Paramètres
    ----------
    request : HttpRequest
        La requête HTTP entrante.
    pk : int
        Clé primaire de l'enregistrement ``Absence`` à éditer.

    Retour
    ------
    HttpResponse
        Formulaire rendu sur GET ou erreur de validation, redirection sur succès.

    Lève
    ----
    Http404
        Quand aucune ``Absence`` n'existe avec la ``pk`` donnée.
    """
    absence = get_object_or_404(Absence.objects.select_related("id_seance"), pk=pk)

    # Empêche les éditions directes sur les absences déjà justifiées ; celles-ci doivent passer
    # par le workflow de justification pour préserver la piste d'audit.
    if absence.statut == Absence.Statut.JUSTIFIEE:
        messages.error(
            request,
            "Cette absence est déjà justifiée et ne peut plus être modifiée. "
            "Veuillez d'abord changer son statut via le traitement des justificatifs.",
        )
        return redirect("absences:validation_list")

    # Pré-calcule la durée de la séance pour que le formulaire puisse l'afficher comme valeur plafond.
    seance_duration, seance_duration_display = _get_seance_duration(absence.id_seance)

    if request.method == "POST":
        # Constitue le contexte tôt pour que chaque chemin de sortie anticipée puisse ré-afficher le formulaire.
        ctx = {
            "absence": absence,
            "seance_duration": seance_duration,
            "seance_duration_display": seance_duration_display,
        }

        reason = request.POST.get("reason", "").strip()
        new_type = request.POST.get("type_absence", "")
        new_statut = request.POST.get("statut", "")

        # Le motif est obligatoire — rejette une soumission silencieuse sans justification.
        if not reason:
            messages.error(request, "Un motif est obligatoire pour modifier une absence.")
            return render(request, "absences/edit_absence.html", ctx)

        # Valide le type contre la liste blanche côté serveur (pas seulement le widget de formulaire).
        if new_type not in _VALID_TYPES:
            messages.error(request, "Type d'absence invalide.")
            return render(request, "absences/edit_absence.html", ctx)

        # Valide le statut contre toutes les valeurs d'enum connues.
        if new_statut not in _VALID_STATUTS:
            messages.error(request, "Statut invalide.")
            return render(request, "absences/edit_absence.html", ctx)

        # Analyse et quantifie la durée à exactement 2 décimales.
        try:
            raw_duree = request.POST.get("duree_absence") or "0"
            new_duree = Decimal(str(raw_duree)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        except (ValueError, TypeError, ArithmeticError):
            messages.error(request, "Durée invalide (ex : 1.5).")
            return render(request, "absences/edit_absence.html", ctx)

        if new_duree <= 0:
            messages.error(request, "La durée doit être supérieure à zéro.")
            return render(request, "absences/edit_absence.html", ctx)

        # Garantit que la durée déclarée ne dépasse pas la durée réelle de la séance.
        if seance_duration and new_duree > seance_duration:
            messages.error(
                request,
                f"La durée ({new_duree}h) ne peut pas dépasser la durée de la séance ({seance_duration}h).",
            )
            return render(request, "absences/edit_absence.html", ctx)

        with transaction.atomic():
            # Recharge avec select_for_update pour tenir un verrou au niveau ligne pendant
            # la durée de la transaction et empêcher les doubles éditions concurrentes.
            absence = (
                Absence.objects
                .select_related("id_seance__id_cours", "id_inscription__id_etudiant")
                .select_for_update()
                .get(pk=pk)
            )

            # Un autre secrétaire peut avoir justifié cette absence entre notre GET
            # et ce POST — vérifie à nouveau à l'intérieur de la transaction.
            if absence.statut == Absence.Statut.JUSTIFIEE:
                messages.error(request, "Cette absence a été justifiée entre-temps et ne peut plus être modifiée.")
                return redirect("absences:validation_list")

            # Capture les anciennes valeurs pour construire un diff pour le log d'audit.
            old_statut = absence.statut
            old_duree = float(absence.duree_absence or 0)
            old_type = absence.type_absence

            change_desc = f"Absence {pk} MODIFIÉE. "
            changed = False

            # Construit une description de diff lisible par humain pour chaque champ modifié.
            if old_statut != new_statut:
                change_desc += f"Statut: {old_statut} -> {new_statut}. "
                changed = True
            if old_duree != new_duree:
                change_desc += f"Durée: {old_duree} -> {new_duree}. "
                changed = True
            if old_type != new_type:
                change_desc += f"Type: {old_type} -> {new_type}. "
                changed = True

            if changed:
                change_desc += f"Motif: {reason}"

                absence.duree_absence = new_duree
                absence.type_absence = new_type
                absence.statut = new_statut
                absence.save()

                # Tient la machine à états de la Justification synchrone à chaque changement de statut
                # de l'absence parente, afin que les deux modèles restent cohérents.
                if old_statut != new_statut:
                    justification = Justification.objects.filter(id_absence=absence).first()
                    if justification:
                        if new_statut == Absence.Statut.JUSTIFIEE:
                            # Le secrétariat marque manuellement comme justifiée.
                            justification.state = Justification.State.ACCEPTEE
                            justification.validee_par = request.user
                            justification.date_validation = timezone.now()
                        elif new_statut == Absence.Statut.NON_JUSTIFIEE:
                            # Le secrétariat rejette explicitement la justification.
                            justification.state = Justification.State.REFUSEE
                            justification.validee_par = request.user
                            justification.date_validation = timezone.now()
                        elif new_statut == Absence.Statut.EN_ATTENTE:
                            # Réinitialise en attente pour que l'étudiant puisse re-soumettre.
                            justification.state = Justification.State.EN_ATTENTE
                            justification.validee_par = None
                            justification.date_validation = None
                        justification.save()

                log_action(
                    request.user,
                    f"Secrétaire a modifié l'absence {pk} pour "
                    f"{absence.id_inscription.id_etudiant.get_full_name()} - "
                    f"{absence.id_seance.id_cours.code_cours}. {change_desc}",
                    request,
                    niveau="WARNING",
                    objet_type="ABSENCE",
                    objet_id=pk,
                )

        if changed:
            messages.success(request, "L'absence a été modifiée. La modification est enregistrée dans l'audit.")
        else:
            messages.info(request, "Aucune modification détectée.")

        return redirect("absences:validation_list")

    # GET — affiche le formulaire avec les valeurs courantes.
    return render(request, "absences/edit_absence.html", {
        "absence": absence,
        "seance_duration": seance_duration,
        "seance_duration_display": seance_duration_display,
    })
