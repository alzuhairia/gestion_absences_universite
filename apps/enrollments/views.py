"""
FICHIER : apps/enrollments/views.py
RESPONSABILITE : Gestion des inscriptions etudiants (UI + API AJAX)
FONCTIONNALITES PRINCIPALES :
  - Interface gestionnaire d'inscriptions
  - API AJAX : departements, cours par departement/annee/etudiant
  - Inscription par niveau complet ou cours individuels
  - Creation de compte etudiant a l'inscription
  - Verification des prerequis (non bloquant)
DEPENDANCES CLES : enrollments.models, enrollments.forms, academics.models
"""

import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Count
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_http_methods
from django_ratelimit.decorators import ratelimit

from apps.academic_sessions.models import AnneeAcademique
from apps.academics.models import Cours, Departement, Faculte
from apps.accounts.models import User
from apps.audits.ip_utils import ratelimit_client_ip
from apps.audits.utils import log_action
from apps.dashboard.decorators import (
    api_error,
    api_login_required,
    api_ok,
    new_request_id,
    secretary_required,
)

from .forms import EnrollmentForm, StudentCreationForm
from .models import Inscription

logger = logging.getLogger(__name__)
API_RATE_LIMIT = "30/5m"


# ──────────────────────────────────────────────────────────────
#  INTERFACE GESTIONNAIRE
# ──────────────────────────────────────────────────────────────


@login_required
@secretary_required
@require_GET
def enrollment_manager(request):
    facultes = Faculte.objects.all()
    academic_years = AnneeAcademique.objects.all().order_by("-libelle")
    students = User.objects.filter(role=User.Role.ETUDIANT, actif=True)

    return render(
        request,
        "enrollments/manager.html",
        {"facultes": facultes, "academic_years": academic_years, "students": students},
    )


# ──────────────────────────────────────────────────────────────
#  API AJAX POUR L'INTERFACE DYNAMIQUE
# ──────────────────────────────────────────────────────────────


@ratelimit(key=ratelimit_client_ip, rate=API_RATE_LIMIT, method="GET", block=False)
@api_login_required(roles=[User.Role.ADMIN, User.Role.SECRETAIRE])
@require_GET
def get_departments(request):
    """
    API — Liste les départements d'une faculté.

    Query params:
        faculty_id (int, requis) : ID de la faculté

    Réponses:
        200 [{"id": int, "name": str}, ...]
        400 {"error": {"code": "bad_request", "message": "..."}}
        401 {"error": {"code": "auth_required", ...}}
        403 {"error": {"code": "forbidden", ...}}
        429 Rate limit dépassé (30/5m par IP)
        500 {"error": {"code": "server_error", ...}}
    """
    if getattr(request, "limited", False):
        return api_error(
            "Trop de requetes. Reessayez plus tard.", status=429, code="rate_limited"
        )
    try:
        faculty_id = request.GET.get("faculty_id")
        if not faculty_id:
            return api_error("faculty_id requis", status=400, code="bad_request")
        try:
            faculty_id = int(faculty_id)
        except (TypeError, ValueError):
            return api_error(
                "faculty_id doit être un entier", status=400, code="bad_request"
            )
        departments = Departement.objects.filter(id_faculte_id=faculty_id).values(
            "id_departement", "nom_departement"
        )
        data = [
            {"id": d["id_departement"], "name": d["nom_departement"]}
            for d in departments
        ]
        return api_ok(data)
    except Exception:
        request_id = new_request_id()
        logger.exception("Erreur API get_departments [request_id=%s]", request_id)
        return api_error(
            "Une erreur interne est survenue.",
            status=500,
            code="server_error",
            request_id=request_id,
        )


@ratelimit(key=ratelimit_client_ip, rate=API_RATE_LIMIT, method="GET", block=False)
@api_login_required(roles=[User.Role.ADMIN, User.Role.SECRETAIRE])
@require_GET
def get_courses(request):
    """
    API — Liste les cours actifs d'un département.

    Query params:
        dept_id  (int, requis)    : ID du département
        year_id  (int, optionnel) : filtre par année académique

    Réponses:
        200 [{"id": int, "name": str, "code": str, "has_prereq": bool, "year": str|null}, ...]
        401 {"error": {"code": "auth_required", ...}}
        403 {"error": {"code": "forbidden", ...}}
        429 Rate limit dépassé (30/5m par IP)
        500 {"error": {"code": "server_error", ...}}
    """
    if getattr(request, "limited", False):
        return api_error(
            "Trop de requetes. Reessayez plus tard.", status=429, code="rate_limited"
        )
    try:
        dept_id = request.GET.get("dept_id")
        if not dept_id:
            return api_error("dept_id requis", status=400, code="bad_request")
        try:
            dept_id = int(dept_id)
        except (TypeError, ValueError):
            return api_error(
                "dept_id doit être un entier", status=400, code="bad_request"
            )

        year_id = request.GET.get("year_id")
        if year_id:
            try:
                year_id = int(year_id)
            except (TypeError, ValueError):
                return api_error(
                    "year_id doit être un entier", status=400, code="bad_request"
                )

        courses = Cours.objects.filter(
            id_departement_id=dept_id, actif=True
        ).select_related(
            "id_annee",
            "id_departement",
        )

        # Filtrer par année académique si fournie
        if year_id:
            courses = courses.filter(id_annee_id=year_id)

        courses = courses.annotate(prereq_count=Count("prerequisites", distinct=True))

        data = []
        for c in courses:
            data.append(
                {
                    "id": c.id_cours,
                    "name": f"[{c.code_cours}] {c.nom_cours}",
                    "code": c.code_cours,
                    "has_prereq": c.prereq_count > 0,
                    "year": c.id_annee.libelle if c.id_annee else None,
                }
            )
        return api_ok(data)
    except Exception:
        request_id = new_request_id()
        logger.exception("Erreur API get_courses [request_id=%s]", request_id)
        return api_error(
            "Une erreur interne est survenue.",
            status=500,
            code="server_error",
            request_id=request_id,
        )


@ratelimit(key=ratelimit_client_ip, rate=API_RATE_LIMIT, method="GET", block=False)
@api_login_required(roles=[User.Role.ADMIN, User.Role.SECRETAIRE])
@require_GET
def get_courses_by_year(request):
    """
    API — Liste tous les cours actifs d'une année académique.

    Query params:
        year_id (int, requis) : ID de l'année académique

    Réponses:
        200 [{"id": int, "code": str, "name": str, "department": str, "has_prereq": bool}, ...]
        400 {"error": {"code": "bad_request", "message": "year_id requis"}}
        401 {"error": {"code": "auth_required", ...}}
        403 {"error": {"code": "forbidden", ...}}
        429 Rate limit dépassé (30/5m par IP)
        500 {"error": {"code": "server_error", ...}}
    """
    if getattr(request, "limited", False):
        return api_error(
            "Trop de requetes. Reessayez plus tard.", status=429, code="rate_limited"
        )
    year_id = request.GET.get("year_id")

    if not year_id:
        return api_error("year_id requis", status=400, code="bad_request")
    try:
        year_id = int(year_id)
    except (TypeError, ValueError):
        return api_error("year_id doit être un entier", status=400, code="bad_request")

    try:
        qs = Cours.objects.filter(id_annee_id=year_id, actif=True)

        # Filtres optionnels pour l'aperçu inscription niveau complet
        dept_id = request.GET.get("dept_id")
        niveau = request.GET.get("niveau")
        if dept_id:
            try:
                dept_id = int(dept_id)
            except (TypeError, ValueError):
                return api_error("dept_id doit être un entier", status=400, code="bad_request")
            qs = qs.filter(id_departement_id=dept_id)
        if niveau:
            try:
                niveau = int(niveau)
            except (TypeError, ValueError):
                return api_error("niveau doit être un entier", status=400, code="bad_request")
            qs = qs.filter(niveau=niveau)

        courses = (
            qs.select_related("id_departement", "id_annee")
            .annotate(prereq_count=Count("prerequisites", distinct=True))
            .order_by("id_departement__nom_departement", "code_cours")
        )

        # Optionally check which courses the student is already enrolled in
        enrolled_course_ids = set()
        student_id = request.GET.get("student_id")
        if student_id:
            try:
                student_id = int(student_id)
            except (TypeError, ValueError):
                return api_error("student_id doit être un entier", status=400, code="bad_request")
            enrolled_course_ids = set(
                Inscription.objects.filter(
                    id_etudiant_id=student_id,
                    id_annee_id=year_id,
                    status=Inscription.Status.EN_COURS,
                ).values_list("id_cours_id", flat=True)
            )

        data = []
        for c in courses:
            data.append(
                {
                    "id": c.id_cours,
                    "code": c.code_cours,
                    "name": c.nom_cours,
                    "hours": c.nombre_total_periodes,
                    "department": c.id_departement.nom_departement,
                    "has_prereq": c.prereq_count > 0,
                    "already_enrolled": c.id_cours in enrolled_course_ids,
                }
            )
        return api_ok(data)
    except Exception:
        request_id = new_request_id()
        logger.exception("Erreur API get_courses_by_year [request_id=%s]", request_id)
        return api_error(
            "Une erreur interne est survenue.",
            status=500,
            code="server_error",
            request_id=request_id,
        )


@ratelimit(key=ratelimit_client_ip, rate=API_RATE_LIMIT, method="GET", block=False)
@api_login_required(roles=[User.Role.ADMIN, User.Role.SECRETAIRE])
@require_GET
def get_courses_by_student(request):
    """
    API — Liste les cours auxquels un étudiant est inscrit (année active).

    Query params:
        student_id (int, requis) : ID de l'étudiant

    Réponses:
        200 [{"id": int, "code": str, "name": str, "department": str, "level": int, "year": str}, ...]
        400 {"error": {"code": "bad_request", "message": "student_id requis"}}
        401/403/429/500 — formats habituels
    """
    if getattr(request, "limited", False):
        return api_error(
            "Trop de requetes. Reessayez plus tard.", status=429, code="rate_limited"
        )

    student_id = request.GET.get("student_id")
    if not student_id:
        return api_error("student_id requis", status=400, code="bad_request")
    try:
        student_id = int(student_id)
    except (TypeError, ValueError):
        return api_error("student_id doit être un entier", status=400, code="bad_request")

    try:
        annee_active = AnneeAcademique.objects.filter(active=True).first()
        if not annee_active:
            return api_ok([])

        inscriptions = (
            Inscription.objects.filter(
                id_etudiant_id=student_id,
                id_annee=annee_active,
                status=Inscription.Status.EN_COURS,
            )
            .select_related(
                "id_cours", "id_cours__id_departement", "id_cours__id_annee"
            )
            .order_by("id_cours__code_cours")
        )

        data = [
            {
                "id": ins.id_cours.id_cours,
                "code": ins.id_cours.code_cours,
                "name": ins.id_cours.nom_cours,
                "department": ins.id_cours.id_departement.nom_departement,
                "level": ins.id_cours.niveau,
                "year": ins.id_cours.id_annee.libelle if ins.id_cours.id_annee else "",
            }
            for ins in inscriptions
        ]
        return api_ok(data)
    except Exception:
        request_id = new_request_id()
        logger.exception(
            "Erreur API get_courses_by_student [request_id=%s]", request_id
        )
        return api_error(
            "Une erreur interne est survenue.",
            status=500,
            code="server_error",
            request_id=request_id,
        )


def get_prerequisite_info(course):
    """
    Retourne la liste des prérequis d'un cours (information uniquement).
    Cette application gère les absences, pas les résultats académiques :
    les prérequis sont donc affichés comme avertissement, jamais bloquants.
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


# ──────────────────────────────────────────────────────────────
#  INSCRIPTION ETUDIANT
# ──────────────────────────────────────────────────────────────


@login_required
@secretary_required
@require_http_methods(["GET", "POST"])
def enroll_student(request):
    """
    Vue pour l'inscription d'un étudiant à un cours ou à un niveau complet.

    Modes d'inscription :
    1. NIVEAU COMPLET — inscription à tous les cours actifs du niveau sélectionné
    2. COURS SPÉCIFIQUE — inscription à un cours précis

    Les prérequis sont affichés comme avertissement informatif mais ne bloquent
    jamais l'inscription. La vérification académique (notes, validation) relève
    d'un système de scolarité, pas d'un système de gestion des absences.

    Peut créer un compte étudiant à la volée (must_change_password = True).

    SÉCURITÉ :
    - @secretary_required : seul le secrétariat peut inscrire
    - Transaction atomique pour les inscriptions niveau complet
    - Logging complet pour traçabilité
    """
    enrollment_form = EnrollmentForm(request.POST or None)
    student_form = StudentCreationForm(request.POST or None, prefix="student")

    if request.method == "POST":
        # Déterminer si on crée un nouvel étudiant
        create_new = request.POST.get("create_new_student") == "on"

        # Valider les formulaires
        if create_new:
            if not student_form.is_valid():
                messages.error(request, "Erreur dans les données de l'étudiant.")
                return render(
                    request,
                    "enrollments/enrollment_form.html",
                    {
                        "enrollment_form": enrollment_form,
                        "student_form": student_form,
                    },
                )

        if not enrollment_form.is_valid():
            messages.error(request, "Erreur dans les données d'inscription.")
            return render(
                request,
                "enrollments/enrollment_form.html",
                {
                    "enrollment_form": enrollment_form,
                    "student_form": student_form,
                },
            )

        # Récupérer ou créer l'étudiant
        if create_new:
            # Déduire le niveau du contexte d'inscription
            enrollment_type = enrollment_form.cleaned_data["enrollment_type"]
            if enrollment_type == "LEVEL":
                student_niveau = enrollment_form.cleaned_data["niveau"]
            else:
                student_niveau = None
            try:
                student = student_form.create_student(niveau=student_niveau)
                log_action(
                    request.user,
                    f"CRITIQUE: Création du compte étudiant '{student.email}' ({student.get_full_name()}) lors de l'inscription",
                    request,
                    niveau="CRITIQUE",
                    objet_type="USER",
                    objet_id=student.id_utilisateur,
                )
                messages.info(
                    request,
                    f"Compte étudiant créé pour {student.get_full_name()} ({student.email}).",
                )
            except Exception:
                logger.exception("Erreur lors de la creation du compte etudiant")
                messages.error(
                    request,
                    "Une erreur interne est survenue lors de la creation du compte etudiant.",
                )
                return render(
                    request,
                    "enrollments/enrollment_form.html",
                    {
                        "enrollment_form": enrollment_form,
                        "student_form": student_form,
                    },
                )
        else:
            student_email = enrollment_form.cleaned_data["student_email"]
            try:
                student = User.objects.get(email=student_email, role=User.Role.ETUDIANT)
            except User.DoesNotExist:
                messages.error(
                    request, f"Aucun étudiant trouvé avec l'e-mail {student_email}."
                )
                return render(
                    request,
                    "enrollments/enrollment_form.html",
                    {
                        "enrollment_form": enrollment_form,
                        "student_form": student_form,
                    },
                )

        # Utiliser l'année sélectionnée par l'utilisateur dans le formulaire
        year = enrollment_form.cleaned_data["academic_year"]

        enrollment_type = enrollment_form.cleaned_data["enrollment_type"]

        # ============================================
        # TRAITEMENT SELON LE TYPE D'INSCRIPTION
        # ============================================

        if enrollment_type == "LEVEL":
            # Inscription à un niveau complet = tous les cours actifs du niveau + département

            niveau = int(enrollment_form.cleaned_data["niveau"])
            departement = enrollment_form.cleaned_data["departement"]

            # Récupérer les cours filtrés par département + niveau + année
            level_courses = Cours.objects.filter(
                niveau=niveau,
                id_annee=year,
                id_departement=departement,
                actif=True,
            )

            # Log de débogage
            logger.info(
                f"Inscription niveau {niveau}, département '{departement.nom_departement}' "
                f"pour étudiant {student.email}"
            )
            logger.info(
                f"Année académique utilisée: {year.libelle} (ID: {year.id_annee})"
            )
            logger.info(f"Cours trouvés: {level_courses.count()}")
            for c in level_courses:
                logger.info(
                    f"  - {c.code_cours} (niveau={c.niveau}, "
                    f"année={c.id_annee.libelle if c.id_annee else 'NULL'}, actif={c.actif})"
                )

            if not level_courses.exists():
                # Diagnostic détaillé
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
                    other_years = courses_other_year.values_list(
                        "id_annee__libelle", flat=True
                    ).distinct()
                    error_msg += f" {courses_other_year.count()} cours trouvé(s) dans d'autres années : {', '.join([y for y in other_years if y])}."

                messages.warning(request, error_msg)
                return render(
                    request,
                    "enrollments/enrollment_form.html",
                    {
                        "enrollment_form": enrollment_form,
                        "student_form": student_form,
                    },
                )

            # Inscrire l'étudiant à tous les cours du niveau
            enrolled_count = 0
            skipped_count = 0
            errors = []

            try:
                with transaction.atomic():
                    # Mettre à jour le niveau DANS la transaction
                    # pour garantir la cohérence si les inscriptions échouent
                    student.niveau = niveau
                    student.save(update_fields=["niveau"])

                    for course in level_courses:
                        # Avertissement informatif sur les prérequis (non bloquant)
                        prereqs = get_prerequisite_info(course)
                        if prereqs:
                            prereq_list = ", ".join(
                                [f"{p['code']} - {p['name']}" for p in prereqs]
                            )
                            messages.warning(
                                request,
                                f"{course.code_cours} a des prerequis : {prereq_list}. "
                                f"Veuillez verifier que l'etudiant les a completes.",
                            )

                        # get_or_create : atomique — élimine la race condition
                        # entre exists() et create() de l'ancien code.
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
                            error_msg = f"{course.code_cours}: erreur lors de la creation de l'inscription"
                            errors.append(error_msg)
                            logger.exception(
                                "Erreur lors de la creation de l'inscription pour %s",
                                course.code_cours,
                            )
                            continue

                    # Journaliser
                    if enrolled_count > 0:
                        log_action(
                            request.user,
                            f"CRITIQUE: Inscription de l'étudiant {student.get_full_name()} ({student.email}) au niveau {niveau} — {departement.nom_departement} pour l'année {year.libelle} ({enrolled_count} cours(s))",
                            request,
                            niveau="CRITIQUE",
                            objet_type="INSCRIPTION",
                            objet_id=None,
                        )

                logger.info(
                    f"Résultat final - Inscrits: {enrolled_count}, Ignorés: {skipped_count}, Erreurs: {len(errors)}"
                )
            except Exception:
                messages.error(
                    request, "Une erreur interne est survenue lors de l'inscription."
                )
                logger.exception("Erreur d'inscription")
                return render(
                    request,
                    "enrollments/enrollment_form.html",
                    {
                        "enrollment_form": enrollment_form,
                        "student_form": student_form,
                    },
                )

            # Messages de résultat
            if enrolled_count > 0:
                messages.success(
                    request,
                    f"L'étudiant {student.get_full_name()} a été inscrit à {enrolled_count} cours(s) "
                    f"de l'Année {niveau} — {departement.nom_departement} "
                    f"pour l'année académique {year.libelle}.",
                )
            else:
                # Si aucune inscription n'a été créée, donner plus de détails
                if skipped_count > 0:
                    messages.warning(
                        request,
                        f"Aucune nouvelle inscription créée. {skipped_count} cours(s) déjà existant(s) pour cet étudiant.",
                    )
                if errors:
                    for error in errors[:5]:
                        messages.error(request, error)
                    if len(errors) > 5:
                        messages.error(
                            request, f"... et {len(errors) - 5} autre(s) erreur(s)."
                        )
                else:
                    messages.error(
                        request,
                        f"ERREUR: Aucune inscription n'a été créée pour l'étudiant {student.get_full_name()}. "
                        f"Vérifiez que les cours de niveau {niveau} existent pour l'année académique {year.libelle} "
                        f"(trouvé {level_courses.count()} cours).",
                    )

            if skipped_count > 0 and enrolled_count > 0:
                messages.warning(
                    request,
                    f"{skipped_count} cours(s) déjà existant(s) pour cet étudiant.",
                )

            # Toujours rediriger vers la page des inscriptions pour voir les résultats
            return redirect("dashboard:secretary_enrollments")

        else:
            # Inscription à un ou plusieurs cours spécifiques
            selected_courses = enrollment_form.cleaned_data["courses"]

            enrolled_count = 0
            skipped_count = 0
            year_mismatch = []

            try:
                with transaction.atomic():
                    for course in selected_courses:
                        # Vérifier que le cours appartient à l'année académique
                        if course.id_annee and course.id_annee.id_annee != year.id_annee:
                            year_mismatch.append(course.code_cours)
                            continue

                        # Avertissement informatif sur les prérequis (non bloquant)
                        prereqs = get_prerequisite_info(course)
                        if prereqs:
                            prereq_list = ", ".join(
                                [f"{p['code']} - {p['name']}" for p in prereqs]
                            )
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
                                student.email,
                                course.code_cours,
                                year.libelle,
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
                messages.error(
                    request, "Une erreur interne est survenue lors de l'inscription."
                )
                logger.exception("Erreur d'inscription multi-cours")
                return render(
                    request,
                    "enrollments/enrollment_form.html",
                    {
                        "enrollment_form": enrollment_form,
                        "student_form": student_form,
                    },
                )

            # Résultat partiel explicite — un message structuré
            total_selected = len(selected_courses)
            result_parts = []
            if enrolled_count > 0:
                result_parts.append(
                    f"{enrolled_count} cours inscrit(s)"
                )
            if skipped_count > 0:
                result_parts.append(
                    f"{skipped_count} cours ignoré(s) (déjà inscrit)"
                )
            if year_mismatch:
                result_parts.append(
                    f"{len(year_mismatch)} cours rejeté(s) (année incorrecte : {', '.join(year_mismatch)})"
                )

            summary = f"Résultat pour {student.get_full_name()} — {' | '.join(result_parts)}"

            if enrolled_count > 0 and not year_mismatch:
                messages.success(request, summary)
            elif enrolled_count > 0:
                messages.warning(request, summary)
            else:
                messages.warning(request, summary)

        return redirect("dashboard:secretary_enrollments")

    # GET request - afficher le formulaire
    # Filtrer les cours selon l'année académique par défaut (année active)
    academic_years = AnneeAcademique.objects.all().order_by("-libelle")
    default_year = academic_years.filter(active=True).first() or academic_years.first()

    if default_year:
        enrollment_form.fields["courses"].queryset = (
            Cours.objects.filter(actif=True, id_annee=default_year)
            .select_related("id_annee", "id_departement")
            .order_by("id_departement__nom_departement", "code_cours")
        )
        enrollment_form.fields["academic_year"].initial = default_year

    # Afficher un message d'information sur l'année académique utilisée
    if default_year:
        messages.info(
            request,
            f"L'année académique active ({default_year.libelle}) sera utilisée pour l'inscription.",
        )

    return render(
        request,
        "enrollments/enrollment_form.html",
        {
            "enrollment_form": enrollment_form,
            "student_form": student_form,
        },
    )
