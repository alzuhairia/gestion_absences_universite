"""
Endpoints API AJAX pour l'interface d'inscription dynamique.

Tous les endpoints renvoient du JSON et sont protégés par ``@api_login_required``
(rôle ADMIN ou SECRETAIRE requis). Une limite de débit partagée de 30 requêtes
par 5 minutes par IP est appliquée via ``django-ratelimit``.

Endpoints
---------
get_departments        — départements appartenant à une faculté donnée
get_courses            — cours actifs pour un département (avec filtre année optionnel)
get_courses_by_year    — tous les cours actifs pour une année académique (avec filtres optionnels)
get_courses_by_student — cours dans lesquels un étudiant est actuellement inscrit

Appartient à : UniAbsences — application enrollments.
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

# Limite de débit partagée appliquée à chaque endpoint de ce module.
API_RATE_LIMIT = "30/5m"


@ratelimit(key=ratelimit_client_ip, rate=API_RATE_LIMIT, method="GET", block=False)
@api_login_required(roles=[User.Role.ADMIN, User.Role.SECRETAIRE])
@require_GET
def get_departments(request):
    """
    Renvoie la liste des départements appartenant à une faculté.

    Parameters
    ----------
    request : HttpRequest
        Doit inclure ``faculty_id`` (entier) comme paramètre de requête GET.

    Returns
    -------
    JsonResponse
        200 — ``[{"id": int, "name": str}, ...]``
        400 — ``{"error": {"code": "bad_request", "message": "..."}}``
        401 — authentification requise
        403 — rôle non autorisé
        429 — limite de débit dépassée (30 requêtes / 5 min par IP)
        500 — erreur serveur inattendue (inclut ``request_id`` pour le traçage des logs)
    """
    # Respecter le flag de rate-limit défini par django-ratelimit avant d'exécuter la logique.
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

        # Ne récupérer que les deux champs nécessaires au frontend pour garder une payload réduite.
        departments = Departement.objects.filter(id_faculte_id=faculty_id).values(
            "id_departement", "nom_departement"
        )
        data = [
            {"id": d["id_departement"], "name": d["nom_departement"]}
            for d in departments
        ]
        return api_ok(data)
    except Exception:
        # Logger avec un ID de requête unique afin que l'incident puisse être corrélé dans les logs.
        request_id = new_request_id()
        logger.exception("Erreur API get_departments [request_id=%s]", request_id)
        return api_error("Une erreur interne est survenue.", status=500,
                         code="server_error", request_id=request_id)


@ratelimit(key=ratelimit_client_ip, rate=API_RATE_LIMIT, method="GET", block=False)
@api_login_required(roles=[User.Role.ADMIN, User.Role.SECRETAIRE])
@require_GET
def get_courses(request):
    """
    Renvoie les cours actifs pour un département, avec un filtre optionnel par année académique.

    La réponse inclut un flag ``has_prereq`` afin que le frontend puisse avertir
    le secrétaire avant d'inscrire un étudiant à qui il manquerait des prérequis.

    Parameters
    ----------
    request : HttpRequest
        Paramètres GET :
          - ``dept_id`` (int, requis)    — clé primaire du département
          - ``year_id`` (int, optionnel) — filtre par année académique

    Returns
    -------
    JsonResponse
        200 — ``[{"id": int, "name": str, "code": str,
                  "has_prereq": bool, "year": str|null}, ...]``
        400 — paramètre manquant ou invalide
        429 — limite de débit dépassée
        500 — erreur serveur inattendue
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

        # Queryset de base : cours actifs pour le département donné.
        courses = Cours.objects.filter(
            id_departement_id=dept_id, actif=True
        ).select_related("id_annee", "id_departement")

        # Restriction optionnelle par année académique.
        if year_id:
            courses = courses.filter(id_annee_id=year_id)

        # Annoter avec le nombre de prérequis pour piloter le badge d'avertissement du frontend.
        courses = courses.annotate(prereq_count=Count("prerequisites", distinct=True))

        data = []
        for c in courses:
            data.append({
                "id": c.id_cours,
                # Afficher le code à côté du nom pour que le secrétaire puisse identifier le cours.
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
    Renvoie tous les cours actifs pour une année académique, avec filtres optionnels.

    Lorsque ``student_id`` est fourni, la réponse marque également les cours
    auxquels l'étudiant est déjà inscrit (``already_enrolled: true``), ce qui
    permet au frontend de griser ces cases à cocher.

    Parameters
    ----------
    request : HttpRequest
        Paramètres GET :
          - ``year_id``    (int, requis)    — clé primaire de l'année académique
          - ``dept_id``    (int, optionnel) — filtre par département
          - ``niveau``     (int, optionnel) — filtre par niveau d'étude (1, 2, ou 3)
          - ``student_id`` (int, optionnel) — marque les cours déjà inscrits

    Returns
    -------
    JsonResponse
        200 — ``[{"id": int, "code": str, "name": str, "department": str,
                  "has_prereq": bool, "already_enrolled": bool}, ...]``
        400 — paramètre manquant ou invalide
        429 — limite de débit dépassée
        500 — erreur serveur inattendue
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
        # Commencer avec tous les cours actifs pour l'année demandée.
        qs = Cours.objects.filter(id_annee_id=year_id, actif=True)

        # Appliquer le filtre département optionnel.
        dept_id = request.GET.get("dept_id")
        niveau = request.GET.get("niveau")
        if dept_id:
            try:
                dept_id = int(dept_id)
            except (TypeError, ValueError):
                return api_error("dept_id doit être un entier", status=400, code="bad_request")
            qs = qs.filter(id_departement_id=dept_id)

        # Appliquer le filtre niveau d'étude optionnel.
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

        # Récupérer les inscriptions actuelles de l'étudiant en une seule requête, puis utiliser un set
        # pour des vérifications d'appartenance en O(1) au lieu d'accès BD par cours.
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
                # True lorsque l'étudiant est déjà inscrit (EN_COURS) à ce cours.
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
    Renvoie les cours auxquels un étudiant est actuellement inscrit pour l'année académique active.

    Seules les inscriptions de statut ``EN_COURS`` sont renvoyées. Si aucune
    année académique n'est marquée active, une liste vide est retournée plutôt
    qu'une erreur.

    Parameters
    ----------
    request : HttpRequest
        Paramètres GET :
          - ``student_id`` (int, requis) — clé primaire de l'utilisateur étudiant

    Returns
    -------
    JsonResponse
        200 — ``[{"id": int, "code": str, "name": str,
                  "department": str, "level": int, "year": str}, ...]``
        400 — ``student_id`` manquant ou invalide
        429 — limite de débit dépassée
        500 — erreur serveur inattendue
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
        # Résoudre l'année académique actuellement active ; renvoyer une liste vide si aucune.
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
                # Protection contre les cours pas encore assignés à une année académique.
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
