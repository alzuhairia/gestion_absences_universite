"""
Logique métier des opérations d'inscription des étudiants.

Ce module sépare la logique de traitement des inscriptions de la couche vue
afin que chaque fonction handler puisse être testée et réutilisée
indépendamment.

Functions
---------
get_prerequisite_info     — helper : récupère la liste des prérequis d'un cours (informatif uniquement)
_handle_level_enrollment  — inscrit un étudiant à tous les cours actifs d'un niveau donné
_handle_course_enrollment — inscrit un étudiant à un ou plusieurs cours spécifiques

Return convention
-----------------
Chaque handler renvoie la chaîne ``"done"`` en cas de succès, ou ``None``
lorsque l'appelant doit ré-afficher le formulaire (par ex. après une erreur
de validation ou un conflit). Les messages Django sont utilisés pour
communiquer les détails du résultat à l'utilisateur.

Appartient à : UniAbsences — application enrollments.
"""
import logging

from django.contrib import messages
from django.db import transaction

from apps.academics.models import Cours
from apps.audits.utils import log_action

from .models import Inscription

logger = logging.getLogger(__name__)


def get_prerequisite_info(course):
    """
    Renvoie une liste de descripteurs de prérequis pour un cours.

    Les prérequis sont uniquement informatifs — ils sont affichés sous forme
    d'avertissements dans l'UI mais ne bloquent jamais l'inscription. La
    vérification des prérequis (par ex. confirmer qu'un étudiant a réussi un
    cours antérieur) sort du périmètre d'un système de gestion des absences.

    Parameters
    ----------
    course : Cours
        Le cours dont les prérequis doivent être récupérés.

    Returns
    -------
    list[dict]
        Chaque élément contient :
          - ``code``  (str) — code du cours prérequis
          - ``name``  (str) — nom du cours
          - ``year``  (str) — libellé de l'année académique, ou ``"N/A"`` si non défini
    """
    prerequisites = course.prerequisites.select_related("id_annee").all()
    return [
        {
            "code": prereq.code_cours,
            "name": prereq.nom_cours,
            "year": prereq.id_annee.libelle if prereq.id_annee else "N/A",
        }
        for prereq in prerequisites
    ]


def _handle_level_enrollment(request, student, enrollment_form, year):
    """
    Inscrit un étudiant à tous les cours actifs d'un niveau d'étude donné.

    Récupère chaque ``Cours`` actif correspondant au niveau, au département et
    à l'année académique sélectionnés, puis crée un enregistrement
    ``Inscription`` pour chacun qui n'existe pas encore. Le champ ``niveau``
    de l'étudiant est également mis à jour pour refléter le nouveau niveau.

    Business rules enforced
    -----------------------
    - Un étudiant ne peut pas être inscrit à deux niveaux différents au sein
      de la même année académique (vérification de conflit inter-niveaux).
    - Si aucun cours actif n'est trouvé pour la combinaison niveau/département/année
      demandée, un avertissement descriptif est affiché et l'inscription est annulée.
    - Des avertissements de prérequis sont affichés pour chaque cours ayant
      des prérequis, mais ils ne bloquent jamais l'inscription.
    - Toute l'opération s'exécute au sein d'une seule transaction base de données
      afin qu'un échec en milieu de boucle ne laisse pas l'étudiant partiellement inscrit.

    Parameters
    ----------
    request : HttpRequest
        La requête HTTP courante (utilisée pour attacher les messages Django).
    student : User
        L'étudiant à inscrire.
    enrollment_form : EnrollmentForm
        Une instance de formulaire validée fournissant ``niveau`` et ``departement``.
    year : AnneeAcademique
        L'année académique cible.

    Returns
    -------
    str or None
        ``"done"`` en cas de succès (l'appelant redirige), ``None`` en cas
        d'erreur ou de conflit (l'appelant ré-affiche le formulaire).
    """
    niveau = int(enrollment_form.cleaned_data["niveau"])
    departement = enrollment_form.cleaned_data["departement"]

    level_courses = Cours.objects.filter(
        niveau=niveau,
        id_annee=year,
        id_departement=departement,
        actif=True,
    )

    # Logs de niveau debug pour aider au diagnostic des problèmes d'inscription en production.
    logger.info(
        f"Inscription niveau {niveau}, département '{departement.nom_departement}' "
        f"pour étudiant {student.email}"
    )
    logger.info(f"Année académique utilisée: {year.libelle} (ID: {year.id_annee})")
    logger.info(f"Cours trouvés: {level_courses.count()}")
    for c in level_courses:
        logger.info(
            f"  - {c.code_cours} (niveau={c.niveau}, "
            f"année={c.id_annee.libelle if c.id_annee else 'NULL'}, actif={c.actif})"
        )

    # Vérification de conflit inter-niveaux : un étudiant ne peut pas suivre deux niveaux différents
    # la même année académique. Détecter toute inscription EN_COURS à un niveau différent
    # et signaler clairement les niveaux en conflit au secrétaire.
    existing_other_level = (
        Inscription.objects.filter(
            id_etudiant=student,
            id_annee=year,
            status=Inscription.Status.EN_COURS,
        )
        .exclude(id_cours__niveau=niveau)
        .select_related("id_cours")
    )
    if existing_other_level.exists():
        other_niveaux = sorted(
            existing_other_level.values_list("id_cours__niveau", flat=True).distinct()
        )
        niveaux_str = ", ".join(f"Année {n}" for n in other_niveaux)
        messages.error(
            request,
            f"{student.get_full_name()} est déjà inscrit(e) en {niveaux_str} "
            f"pour l'année académique {year.libelle}. "
            f"Un étudiant ne peut pas suivre deux niveaux différents la même année. "
            f"Veuillez créer une nouvelle année académique pour inscrire cet étudiant en Année {niveau}.",
        )
        return None

    # Aucun cours trouvé : fournir un message de diagnostic expliquant les causes possibles
    # (les cours existent mais sans année assignée, ou existent dans une autre année).
    if not level_courses.exists():
        courses_without_year = Cours.objects.filter(
            niveau=niveau, id_departement=departement, actif=True, id_annee__isnull=True
        )
        courses_other_year = Cours.objects.filter(
            niveau=niveau, id_departement=departement, actif=True
        ).exclude(id_annee=year)

        error_msg = (
            f"Aucun cours actif trouvé pour l'Année {niveau} "
            f"du département {departement.nom_departement} "
            f"dans l'année académique {year.libelle}."
        )
        if courses_without_year.exists():
            error_msg += f" {courses_without_year.count()} cours trouvé(s) sans année académique assignée."
        if courses_other_year.exists():
            other_years = courses_other_year.values_list("id_annee__libelle", flat=True).distinct()
            error_msg += f" {courses_other_year.count()} cours trouvé(s) dans d'autres années : {', '.join([y for y in other_years if y])}."

        messages.warning(request, error_msg)
        return None

    enrolled_count = 0
    skipped_count = 0
    errors = []

    try:
        with transaction.atomic():
            # Mettre à jour le niveau de l'étudiant pour qu'il corresponde au niveau nouvellement inscrit.
            student.niveau = niveau
            student.save(update_fields=["niveau"])

            for course in level_courses:
                # Avertir au sujet des prérequis (non bloquant).
                prereqs = get_prerequisite_info(course)
                if prereqs:
                    prereq_list = ", ".join([f"{p['code']} - {p['name']}" for p in prereqs])
                    messages.warning(
                        request,
                        f"{course.code_cours} a des prerequis : {prereq_list}. "
                        f"Veuillez verifier que l'etudiant les a completes.",
                    )

                try:
                    # Utiliser get_or_create pour éviter gracieusement les inscriptions dupliquées.
                    inscription, created = Inscription.objects.get_or_create(
                        id_etudiant=student,
                        id_cours=course,
                        id_annee=year,
                        defaults={
                            "type_inscription": Inscription.TypeInscription.NORMALE,
                            "eligible_examen": True,
                            "status": Inscription.Status.EN_COURS,
                        },
                    )
                    if not created:
                        # Déjà inscrit — compter comme ignoré, ne pas générer d'erreur.
                        skipped_count += 1
                        continue
                    logger.info(
                        f"Inscription créée: ID={inscription.id_inscription}, Étudiant={student.email}, Cours={course.code_cours}, Année={year.libelle}"
                    )
                    enrolled_count += 1
                except Exception:
                    errors.append(f"{course.code_cours}: erreur lors de la creation de l'inscription")
                    logger.exception("Erreur lors de la creation de l'inscription pour %s", course.code_cours)
                    continue

            # Journaliser dans l'audit l'inscription par lot si au moins une inscription a été créée.
            if enrolled_count > 0:
                log_action(
                    request.user,
                    f"CRITIQUE: Inscription de l'étudiant {student.get_full_name()} ({student.email}) au niveau {niveau} — {departement.nom_departement} pour l'année {year.libelle} ({enrolled_count} cours(s))",
                    request,
                    niveau="CRITIQUE",
                    objet_type="INSCRIPTION",
                    objet_id=None,
                )

        logger.info(f"Résultat final - Inscrits: {enrolled_count}, Ignorés: {skipped_count}, Erreurs: {len(errors)}")
    except Exception:
        messages.error(request, "Une erreur interne est survenue lors de l'inscription.")
        logger.exception("Erreur d'inscription")
        return None

    # Construire les messages de synthèse destinés à l'utilisateur en fonction des compteurs de résultats.
    if enrolled_count > 0:
        messages.success(
            request,
            f"L'étudiant {student.get_full_name()} a été inscrit à {enrolled_count} cours "
            f"de l'Année {niveau} — {departement.nom_departement} "
            f"pour l'année académique {year.libelle}.",
        )
        if skipped_count > 0:
            existing_codes = ", ".join(
                c.code_cours
                for c in level_courses
                if Inscription.objects.filter(id_etudiant=student, id_cours=c, id_annee=year).exists()
            )
            messages.warning(
                request,
                f"{skipped_count} cours ignoré(s) (déjà inscrit) : {existing_codes}.",
            )
    elif skipped_count > 0:
        # Tous les cours étaient déjà inscrits — informer plutôt que de générer une erreur.
        existing_codes = ", ".join(
            c.code_cours
            for c in level_courses
            if Inscription.objects.filter(id_etudiant=student, id_cours=c, id_annee=year).exists()
        )
        messages.info(
            request,
            f"{student.get_full_name()} est déjà inscrit(e) à tous les {skipped_count} cours "
            f"de l'Année {niveau} — {departement.nom_departement} "
            f"pour {year.libelle} : {existing_codes}.",
        )
    elif errors:
        # Afficher jusqu'à 5 messages d'erreur individuels pour éviter de surcharger la page.
        for error in errors[:5]:
            messages.error(request, error)
        if len(errors) > 5:
            messages.error(request, f"... et {len(errors) - 5} autre(s) erreur(s).")
    else:
        messages.error(
            request,
            f"Aucune inscription n'a été créée pour {student.get_full_name()}. "
            f"Vérifiez que les cours de niveau {niveau} existent pour l'année académique {year.libelle}.",
        )

    return "done"


def _handle_course_enrollment(request, student, enrollment_form, year):
    """
    Inscrit un étudiant à un ou plusieurs cours sélectionnés individuellement.

    Chaque cours sélectionné est validé par rapport à l'année académique
    cible avant que l'inscription ne soit tentée. Les cours dont
    ``id_annee`` ne correspond pas à l'année sélectionnée sont rejetés avec
    un avertissement mais n'interrompent pas toute l'opération — les cours
    restants sont quand même traités.

    Des avertissements de prérequis sont affichés pour chaque cours ayant
    des prérequis, mais les prérequis ne bloquent jamais l'inscription.

    Parameters
    ----------
    request : HttpRequest
        La requête HTTP courante (utilisée pour attacher les messages Django).
    student : User
        L'étudiant à inscrire.
    enrollment_form : EnrollmentForm
        Une instance de formulaire validée fournissant le queryset ``courses``.
    year : AnneeAcademique
        L'année académique cible utilisée comme clé d'inscription.

    Returns
    -------
    str or None
        ``"done"`` en cas de succès (l'appelant redirige), ``None`` en cas
        d'erreur interne inattendue (l'appelant ré-affiche le formulaire).
    """
    selected_courses = enrollment_form.cleaned_data["courses"]

    enrolled_count = 0
    skipped_count = 0
    year_mismatch = []  # Codes des cours rejetés parce que leur année != l'année sélectionnée.

    try:
        with transaction.atomic():
            for course in selected_courses:
                # Rejeter les cours qui appartiennent à une année académique différente.
                # Cela peut se produire si le queryset du formulaire n'a pas été correctement filtré
                # ou si le secrétaire a changé l'année après avoir chargé la page.
                if course.id_annee and course.id_annee.id_annee != year.id_annee:
                    year_mismatch.append(course.code_cours)
                    continue

                # Avertir au sujet des prérequis (informatif, non bloquant).
                prereqs = get_prerequisite_info(course)
                if prereqs:
                    prereq_list = ", ".join([f"{p['code']} - {p['name']}" for p in prereqs])
                    messages.warning(
                        request,
                        f"{course.code_cours} a des prérequis : {prereq_list}. "
                        f"Veuillez vérifier que l'étudiant les a complétés.",
                    )

                # get_or_create empêche les erreurs d'inscriptions dupliquées.
                inscription, created = Inscription.objects.get_or_create(
                    id_etudiant=student,
                    id_cours=course,
                    id_annee=year,
                    defaults={
                        "type_inscription": Inscription.TypeInscription.NORMALE,
                        "eligible_examen": True,
                        "status": Inscription.Status.EN_COURS,
                    },
                )

                if created:
                    enrolled_count += 1
                    logger.info(
                        "Inscription créée: Étudiant=%s, Cours=%s, Année=%s",
                        student.email, course.code_cours, year.libelle,
                    )
                else:
                    skipped_count += 1

            # Journaliser dans l'audit l'inscription multi-cours si quelque chose a été créé.
            if enrolled_count > 0:
                course_codes = ", ".join(
                    c.code_cours
                    for c in selected_courses
                    if not (c.id_annee and c.id_annee.id_annee != year.id_annee)
                )
                log_action(
                    request.user,
                    f"CRITIQUE: Inscription de l'étudiant {student.get_full_name()} ({student.email}) à {enrolled_count} cours ({course_codes}) pour l'année {year.libelle}",
                    request,
                    niveau="CRITIQUE",
                    objet_type="INSCRIPTION",
                    objet_id=None,
                )
    except Exception:
        messages.error(request, "Une erreur interne est survenue lors de l'inscription.")
        logger.exception("Erreur d'inscription multi-cours")
        return None

    # Construire une chaîne de synthèse unique couvrant les trois catégories de résultats.
    result_parts = []
    if enrolled_count > 0:
        result_parts.append(f"{enrolled_count} cours inscrit(s)")
    if skipped_count > 0:
        result_parts.append(f"{skipped_count} cours ignoré(s) (déjà inscrit)")
    if year_mismatch:
        result_parts.append(
            f"{len(year_mismatch)} cours rejeté(s) (année incorrecte : {', '.join(year_mismatch)})"
        )

    summary = f"Résultat pour {student.get_full_name()} — {' | '.join(result_parts)}"

    # Utiliser le niveau success uniquement quand tout s'est inscrit proprement ; sinon avertir.
    if enrolled_count > 0 and not year_mismatch:
        messages.success(request, summary)
    else:
        messages.warning(request, summary)

    return "done"
