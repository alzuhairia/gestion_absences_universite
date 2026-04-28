"""
API AJAX pour l'interface dynamique d'inscription.

Endpoints :
  - get_departments        : départements d'une faculté
  - get_courses            : cours actifs d'un département (+ filtre année)
  - get_courses_by_year    : tous les cours actifs d'une année académique
  - get_courses_by_student : cours auxquels un étudiant est déjà inscrit

Toutes les routes sont protégées par @api_login_required (ADMIN ou SECRETAIRE)
et limitées à 30 requêtes / 5 minutes par IP.
"""
import logging

from django.db.models import Count
from django.views.decorators.http import require_GET
from django_ratelimit.decorators import ratelimit

from apps.academic_sessions.models import AnneeAcademique
from apps.academics.models import Cours, Departement
from apps.accounts.models import User
from apps.audits.ip_utils import ratelimit_client_ip
from apps.dashboard.decorators import (
    api_error,
    api_login_required,
    api_ok,
    new_request_id,
)

from .models import Inscription

logger = logging.getLogger(__name__)
API_RATE_LIMIT = "30/5m"


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
        return api_error("Trop de requetes. Reessayez plus tard.", status=429, code="rate_limited")
    try:
        faculty_id = request.GET.get("faculty_id")
        if not faculty_id:
            return api_error("faculty_id requis", status=400, code="bad_request")
        try:
            faculty_id = int(faculty_id)
        except (TypeError, ValueError):
            return api_error("faculty_id doit être un entier", status=400, code="bad_request")
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
        return api_error("Une erreur interne est survenue.", status=500,
                         code="server_error", request_id=request_id)


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
    """
    if getattr(request, "limited", False):
        return api_error("Trop de requetes. Reessayez plus tard.", status=429, code="rate_limited")
    try:
        dept_id = request.GET.get("dept_id")
        if not dept_id:
            return api_error("dept_id requis", status=400, code="bad_request")
        try:
            dept_id = int(dept_id)
        except (TypeError, ValueError):
            return api_error("dept_id doit être un entier", status=400, code="bad_request")

        year_id = request.GET.get("year_id")
        if year_id:
            try:
                year_id = int(year_id)
            except (TypeError, ValueError):
                return api_error("year_id doit être un entier", status=400, code="bad_request")

        courses = Cours.objects.filter(
            id_departement_id=dept_id, actif=True
        ).select_related("id_annee", "id_departement")

        if year_id:
            courses = courses.filter(id_annee_id=year_id)

        courses = courses.annotate(prereq_count=Count("prerequisites", distinct=True))

        data = []
        for c in courses:
            data.append({
                "id": c.id_cours,
                "name": f"[{c.code_cours}] {c.nom_cours}",
                "code": c.code_cours,
                "has_prereq": c.prereq_count > 0,
                "year": c.id_annee.libelle if c.id_annee else None,
            })
        return api_ok(data)
    except Exception:
        request_id = new_request_id()
        logger.exception("Erreur API get_courses [request_id=%s]", request_id)
        return api_error("Une erreur interne est survenue.", status=500,
                         code="server_error", request_id=request_id)


@ratelimit(key=ratelimit_client_ip, rate=API_RATE_LIMIT, method="GET", block=False)
@api_login_required(roles=[User.Role.ADMIN, User.Role.SECRETAIRE])
@require_GET
def get_courses_by_year(request):
    """
    API — Liste tous les cours actifs d'une année académique.

    Query params:
        year_id  (int, requis)    : ID de l'année académique
        dept_id  (int, optionnel) : filtre par département
        niveau   (int, optionnel) : filtre par niveau
        student_id (int, optionnel) : marque les cours déjà inscrits

    Réponses:
        200 [{"id": int, "code": str, "name": str, "department": str,
              "has_prereq": bool, "already_enrolled": bool}, ...]
        400 {"error": {"code": "bad_request", "message": "year_id requis"}}
    """
    if getattr(request, "limited", False):
        return api_error("Trop de requetes. Reessayez plus tard.", status=429, code="rate_limited")
    year_id = request.GET.get("year_id")

    if not year_id:
        return api_error("year_id requis", status=400, code="bad_request")
    try:
        year_id = int(year_id)
    except (TypeError, ValueError):
        return api_error("year_id doit être un entier", status=400, code="bad_request")

    try:
        qs = Cours.objects.filter(id_annee_id=year_id, actif=True)

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
            data.append({
                "id": c.id_cours,
                "code": c.code_cours,
                "name": c.nom_cours,
                "hours": c.nombre_total_periodes,
                "department": c.id_departement.nom_departement,
                "has_prereq": c.prereq_count > 0,
                "already_enrolled": c.id_cours in enrolled_course_ids,
            })
        return api_ok(data)
    except Exception:
        request_id = new_request_id()
        logger.exception("Erreur API get_courses_by_year [request_id=%s]", request_id)
        return api_error("Une erreur interne est survenue.", status=500,
                         code="server_error", request_id=request_id)


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
    """
    if getattr(request, "limited", False):
        return api_error("Trop de requetes. Reessayez plus tard.", status=429, code="rate_limited")

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
            .select_related("id_cours", "id_cours__id_departement", "id_cours__id_annee")
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
        logger.exception("Erreur API get_courses_by_student [request_id=%s]", request_id)
        return api_error("Une erreur interne est survenue.", status=500,
                         code="server_error", request_id=request_id)
