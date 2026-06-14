"""
Pointage manuel de présence — endpoint partiel HTMX.

``mark_absence_htmx``
    Traite la mise à jour de présence d'un seul étudiant en temps réel et
    renvoie uniquement le fragment HTML ``<tr>`` rafraîchi, évitant un
    rechargement complet de la page. Conçu pour être déclenché par les
    attributs HTMX ``hx-post`` du template du formulaire de présence.

Règle métier critique
----------------------
Les absences encodées par le secrétariat (statut ``JUSTIFIEE`` ou
``EN_ATTENTE``) sont **protégées** : le professeur peut les voir mais ne peut
pas les modifier ou les supprimer. Toute requête ciblant une absence
protégée est silencieusement ignorée et la ligne originale est rendue à
l'identique.

Cycle de vie des séances
-----------------
Si aucun enregistrement ``Seance`` n'existe pour la date et le cours soumis,
un est créé automatiquement afin que le professeur n'ait pas à enregistrer
les horaires de séance séparément avant de pointer les étudiants. Si une
séance existe déjà, ses horaires ne sont mis à jour que lorsqu'ils ont
effectivement changé, pour éviter des ``UPDATE`` inutiles.

Fait partie du système de pointage UniAbsences.
"""
import datetime
import logging
from decimal import ROUND_HALF_UP, Decimal

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from django.db import transaction
from django.views.decorators.http import require_POST

from ..models import Absence
from apps.academic_sessions.models import AnneeAcademique, Seance
from apps.academics.models import Cours
from apps.dashboard.decorators import professor_required
from apps.enrollments.models import Inscription

logger = logging.getLogger(__name__)


@login_required
@professor_required
@require_POST
def mark_absence_htmx(request, course_id):
    """
    Endpoint HTMX — met à jour la présence d'un seul étudiant sans rechargement complet.

    Accepte une soumission POST contenant l'ID d'inscription, le statut
    souhaité (``ABSENT`` ou ``PRESENT``) et la date/horaires de la séance.
    Renvoie le partiel HTML ``<tr>`` mis à jour pour la ligne étudiant ciblée.

    Logique de type / durée d'absence
    ------------------------------
    - ``ABSENT`` — la durée complète de la séance est enregistrée.
    - ``PARTIEL`` — une durée personnalisée (``duree_<inscription_id>``) est
      utilisée ; replie sur la durée complète si la valeur est invalide.
    - Les absences protégées (``JUSTIFIEE`` / ``EN_ATTENTE``) restent intactes.

    Paramètres
    ----------
    request : HttpRequest
        La requête POST entrante (déclenchée par HTMX).
    course_id : int
        Clé primaire du ``Cours`` dont la présence est mise à jour.

    Retour
    ------
    HttpResponse
        - ``403`` si le professeur ne possède pas ce cours ou si la séance est
          déjà validée.
        - ``400`` si des champs requis sont manquants ou si les horaires sont mal formés.
        - ``404`` si l'inscription n'existe pas dans ce cours.
        - Le partiel ``absences/_student_row.html`` rendu en cas de succès.
    """
    course = get_object_or_404(Cours, id_cours=course_id)

    # Vérification de propriété — le décorateur vérifie le rôle, pas le cours.
    if course.professeur != request.user:
        return HttpResponse("Accès non autorisé.", status=403)

    inscription_id = request.POST.get("inscription_id", "")
    status = request.POST.get("status", "")

    active_year = AnneeAcademique.objects.filter(active=True).first()

    # Récupère l'inscription, restreinte à ce cours et à l'année académique active.
    ins_qs = Inscription.objects.filter(
        id_inscription=inscription_id,
        id_cours=course,
        status=Inscription.Status.EN_COURS,
    ).select_related("id_etudiant", "id_cours")
    if active_year:
        ins_qs = ins_qs.filter(id_annee=active_year)
    inscription = ins_qs.first()

    if not inscription:
        return HttpResponse("Inscription introuvable.", status=404)

    date_seance = request.POST.get("date_seance", "").strip()
    heure_debut = request.POST.get("heure_debut", "").strip()
    heure_fin = request.POST.get("heure_fin", "").strip()

    if not date_seance or not heure_debut or not heure_fin:
        return HttpResponse("Date et horaires requis.", status=400)

    # Parse les horaires de séance au format HH:MM.
    try:
        fmt = "%H:%M"
        t_debut = datetime.datetime.strptime(heure_debut, fmt)
        t_fin = datetime.datetime.strptime(heure_fin, fmt)
    except (TypeError, ValueError):
        return HttpResponse("Format d'heure invalide.", status=400)

    if t_fin <= t_debut:
        return HttpResponse("L'heure de fin doit être après l'heure de début.", status=400)

    # Calcule la durée de la séance en heures décimales pour les valeurs par défaut d'absence.
    duree_seance = Decimal((t_fin - t_debut).seconds) / Decimal(3600)
    duree_seance = duree_seance.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    if not active_year:
        return HttpResponse("Aucune année académique active.", status=400)

    with transaction.atomic():
        try:
            # Réutilise un enregistrement de séance existant et met à jour ses horaires si besoin.
            seance = Seance.objects.select_for_update().get(date_seance=date_seance, id_cours=course)
            updated_fields = []
            # Compare uniquement la portion HH:MM pour éviter des mises à jour inutiles dues aux secondes.
            if str(seance.heure_debut or "")[:5] != heure_debut:
                seance.heure_debut = heure_debut
                updated_fields.append("heure_debut")
            if str(seance.heure_fin or "")[:5] != heure_fin:
                seance.heure_fin = heure_fin
                updated_fields.append("heure_fin")
            if updated_fields:
                seance.save(update_fields=updated_fields)
        except Seance.DoesNotExist:
            # Première mise à jour HTMX pour cette date — crée la séance automatiquement.
            seance = Seance.objects.create(
                date_seance=date_seance,
                heure_debut=heure_debut,
                heure_fin=heure_fin,
                id_cours=course,
                id_annee=active_year,
            )

        # Rejette les mises à jour sur les séances verrouillées.
        if seance.validated:
            return HttpResponse("Séance déjà validée.", status=403)

        # Récupère toute absence existante pour cet étudiant et cette séance.
        existing_absence = Absence.objects.filter(
            id_inscription=inscription, id_seance=seance
        ).first()

        if status == "ABSENT":
            if existing_absence and existing_absence.statut in (
                Absence.Statut.JUSTIFIEE, Absence.Statut.EN_ATTENTE
            ):
                # Absence protégée — saut silencieux ; la ligne est rendue à l'identique.
                pass
            else:
                # Seuls ABSENT et PARTIEL sont des types valides côté professeur.
                _ALLOWED_TYPES_HTMX = {Absence.TypeAbsence.ABSENT, Absence.TypeAbsence.PARTIEL}
                type_absence = request.POST.get(f"type_{inscription_id}", Absence.TypeAbsence.ABSENT)
                if type_absence not in _ALLOWED_TYPES_HTMX:
                    type_absence = Absence.TypeAbsence.ABSENT

                # Durée par défaut = durée complète de la séance ; durée personnalisée pour PARTIEL.
                duree = duree_seance
                if type_absence == Absence.TypeAbsence.PARTIEL:
                    try:
                        duree = Decimal(
                            str(float(request.POST.get(f"duree_{inscription_id}", 0)))
                        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                        if duree <= 0 or duree > duree_seance:
                            raise ValueError
                    except (TypeError, ValueError):
                        # Durée personnalisée invalide — repli silencieux.
                        duree = duree_seance

                note = request.POST.get(f"note_{inscription_id}", "").strip()[:500]

                Absence.objects.update_or_create(
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

        elif status == "PRESENT":
            # Supprime l'enregistrement d'absence ; ignore si elle est protégée par le secrétariat.
            if existing_absence:
                if existing_absence.statut not in (Absence.Statut.JUSTIFIEE, Absence.Statut.EN_ATTENTE):
                    existing_absence.delete()

    # Recharge l'état final de l'absence (après tous les changements) pour le rendu partiel.
    absence = Absence.objects.select_related(
        "id_inscription__id_etudiant", "id_seance"
    ).filter(id_inscription=inscription, id_seance=seance).first()

    # Attache les données d'absence à l'objet inscription afin que le template puisse les lire
    # sans requête supplémentaire — reflète la structure utilisée dans la vue page complète.
    if absence:
        setattr(inscription, "absence_data", {
            "type": absence.type_absence,
            "duree": absence.duree_absence,
            "statut": absence.statut,
            "note_professeur": absence.note_professeur,
            "encodee_par": absence.encodee_par,
        })
    else:
        setattr(inscription, "absence_data", None)

    # Renvoie uniquement le fragment HTML de la ligne étudiant mise à jour (HTMX la remplace en place).
    return render(request, "absences/_student_row.html", {
        "ins": inscription,
        "is_validated": False,
        "course": course,
        "seance_id": seance.id_seance,
    })
