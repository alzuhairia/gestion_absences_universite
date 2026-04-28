"""
FICHIER : apps/enrollments/enrollment_handlers.py
RESPONSABILITE : Logique d'inscription par niveau et par cours

Fonctions :
  get_prerequisite_info     — helper : liste des prérequis d'un cours (non bloquant)
  _handle_level_enrollment  — inscription à tous les cours d'un niveau
  _handle_course_enrollment — inscription à un ou plusieurs cours précis

Retourne "done" en cas de succès, None si l'appelant doit afficher le formulaire.
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
    Retourne la liste des prérequis d'un cours (information uniquement).
    Les prérequis sont affichés comme avertissement, jamais bloquants.
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
    """Inscription mode NIVEAU — tous les cours actifs du niveau sélectionné."""
    niveau = int(enrollment_form.cleaned_data["niveau"])
    departement = enrollment_form.cleaned_data["departement"]

    level_courses = Cours.objects.filter(
        niveau=niveau,
        id_annee=year,
        id_departement=departement,
        actif=True,
    )

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
            student.niveau = niveau
            student.save(update_fields=["niveau"])

            for course in level_courses:
                prereqs = get_prerequisite_info(course)
                if prereqs:
                    prereq_list = ", ".join([f"{p['code']} - {p['name']}" for p in prereqs])
                    messages.warning(
                        request,
                        f"{course.code_cours} a des prerequis : {prereq_list}. "
                        f"Veuillez verifier que l'etudiant les a completes.",
                    )

                try:
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
    """Inscription mode COURS — un ou plusieurs cours précis."""
    selected_courses = enrollment_form.cleaned_data["courses"]

    enrolled_count = 0
    skipped_count = 0
    year_mismatch = []

    try:
        with transaction.atomic():
            for course in selected_courses:
                if course.id_annee and course.id_annee.id_annee != year.id_annee:
                    year_mismatch.append(course.code_cours)
                    continue

                prereqs = get_prerequisite_info(course)
                if prereqs:
                    prereq_list = ", ".join([f"{p['code']} - {p['name']}" for p in prereqs])
                    messages.warning(
                        request,
                        f"{course.code_cours} a des prérequis : {prereq_list}. "
                        f"Veuillez vérifier que l'étudiant les a complétés.",
                    )

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

    if enrolled_count > 0 and not year_mismatch:
        messages.success(request, summary)
    else:
        messages.warning(request, summary)

    return "done"
