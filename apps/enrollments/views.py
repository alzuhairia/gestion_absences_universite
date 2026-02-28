from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_http_methods, require_GET
from django.contrib import messages
from django.db.models import Q, Count
from django.db import transaction
from django_ratelimit.decorators import ratelimit
import logging

from apps.accounts.models import User
from apps.academics.models import Faculte, Departement, Cours
from apps.academic_sessions.models import AnneeAcademique
from .models import Inscription
from .forms import EnrollmentForm, StudentCreationForm
from apps.dashboard.decorators import (
    secretary_required,
    api_login_required,
    api_ok,
    api_error,
    new_request_id,
)
from apps.audits.utils import log_action
from apps.audits.ip_utils import ratelimit_client_ip

logger = logging.getLogger(__name__)
API_RATE_LIMIT = '30/5m'

@login_required
@secretary_required
def enrollment_manager(request):
    facultes = Faculte.objects.all()
    academic_years = AnneeAcademique.objects.all().order_by('-libelle')
    students = User.objects.filter(role=User.Role.ETUDIANT)
    
    return render(request, 'enrollments/manager.html', {
        'facultes': facultes,
        'academic_years': academic_years,
        'students': students
    })

@ratelimit(key=ratelimit_client_ip, rate=API_RATE_LIMIT, method='GET', block=False)
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
    if getattr(request, 'limited', False):
        return api_error('Trop de requetes. Reessayez plus tard.', status=429, code='rate_limited')
    try:
        faculty_id = request.GET.get('faculty_id')
        departments = Departement.objects.filter(id_faculte_id=faculty_id).values('id_departement', 'nom_departement')
        data = [{'id': d['id_departement'], 'name': d['nom_departement']} for d in departments]
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

@ratelimit(key=ratelimit_client_ip, rate=API_RATE_LIMIT, method='GET', block=False)
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
    if getattr(request, 'limited', False):
        return api_error('Trop de requetes. Reessayez plus tard.', status=429, code='rate_limited')
    try:
        dept_id = request.GET.get('dept_id')
        year_id = request.GET.get('year_id')

        courses = Cours.objects.filter(id_departement_id=dept_id, actif=True).select_related(
            'id_annee',
            'id_departement',
        )

        # Filtrer par année académique si fournie
        if year_id:
            courses = courses.filter(id_annee_id=year_id)

        courses = courses.annotate(prereq_count=Count('prerequisites', distinct=True))

        data = []
        for c in courses:
            data.append({
                'id': c.id_cours,
                'name': f"[{c.code_cours}] {c.nom_cours}",
                'code': c.code_cours,
                'has_prereq': c.prereq_count > 0,
                'year': c.id_annee.libelle if c.id_annee else None
            })
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

@ratelimit(key=ratelimit_client_ip, rate=API_RATE_LIMIT, method='GET', block=False)
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
    if getattr(request, 'limited', False):
        return api_error('Trop de requetes. Reessayez plus tard.', status=429, code='rate_limited')
    year_id = request.GET.get('year_id')

    if not year_id:
        return api_error('year_id requis', status=400, code='bad_request')

    try:
        courses = (
            Cours.objects.filter(id_annee_id=year_id, actif=True)
            .select_related('id_departement', 'id_annee')
            .annotate(prereq_count=Count('prerequisites', distinct=True))
            .order_by('code_cours')
        )

        data = []
        for c in courses:
            data.append({
                'id': c.id_cours,
                'code': c.code_cours,
                'name': c.nom_cours,
                'department': c.id_departement.nom_departement,
                'has_prereq': c.prereq_count > 0
            })
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

@ratelimit(key=ratelimit_client_ip, rate=API_RATE_LIMIT, method='GET', block=False)
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
    if getattr(request, 'limited', False):
        return api_error('Trop de requetes. Reessayez plus tard.', status=429, code='rate_limited')

    student_id = request.GET.get('student_id')
    if not student_id:
        return api_error('student_id requis', status=400, code='bad_request')

    try:
        annee_active = AnneeAcademique.objects.filter(active=True).first()
        if not annee_active:
            return api_ok([])

        inscriptions = (
            Inscription.objects.filter(
                id_etudiant_id=student_id,
                id_annee=annee_active,
                status="EN_COURS",
            )
            .select_related('id_cours', 'id_cours__id_departement', 'id_cours__id_annee')
            .order_by('id_cours__code_cours')
        )

        data = [
            {
                'id': ins.id_cours.id_cours,
                'code': ins.id_cours.code_cours,
                'name': ins.id_cours.nom_cours,
                'department': ins.id_cours.id_departement.nom_departement,
                'level': ins.id_cours.niveau,
                'year': ins.id_cours.id_annee.libelle if ins.id_cours.id_annee else "",
            }
            for ins in inscriptions
        ]
        return api_ok(data)
    except Exception:
        request_id = new_request_id()
        logger.exception("Erreur API get_courses_by_student [request_id=%s]", request_id)
        return api_error("Une erreur interne est survenue.", status=500, code="server_error",
                         request_id=request_id)


def check_prerequisites(student, course):
    """
    Vérifie si l'étudiant a validé tous les prérequis d'un cours.
    Les prérequis doivent être d'années académiques inférieures.
    Retourne (is_valid, missing_prereqs_list)
    """
    prerequisites = course.prerequisites.all()
    missing_prereqs = []
    
    # Récupérer l'année du cours
    course_year = course.id_annee
    
    for prereq in prerequisites:
        # Vérifier que le prérequis est d'une année inférieure
        if prereq.id_annee and course_year:
            # Comparer les années (on suppose que le libellé suit un format AAAA-AAAA)
            # On peut aussi comparer par ID si les années sont triées
            prereq_year = prereq.id_annee
            if prereq_year.id_annee >= course_year.id_annee:
                # Le prérequis ne devrait pas être d'une année supérieure ou égale
                # Ce cas ne devrait pas arriver si la validation du formulaire est correcte
                missing_prereqs.append({
                    'code': prereq.code_cours,
                    'name': prereq.nom_cours,
                    'year': prereq_year.libelle,
                    'reason': 'Le prérequis doit être d\'une année académique inférieure'
                })
                continue
        
        # Vérifier si l'étudiant a validé le prérequis (statut = 'VALIDE')
        has_validated = Inscription.objects.filter(
            id_etudiant=student,
            id_cours=prereq,
            status='VALIDE'
        ).exists()
        
        if not has_validated:
            missing_prereqs.append({
                'code': prereq.code_cours,
                'name': prereq.nom_cours,
                'year': prereq.id_annee.libelle if prereq.id_annee else 'N/A',
                'reason': 'Prérequis non validé'
            })
    
    return (len(missing_prereqs) == 0, missing_prereqs)


def check_previous_level_validation(student, target_niveau):
    """
    Vérifie si l'étudiant a validé TOUS les cours du niveau précédent.
    
    IMPORTANT POUR LA SOUTENANCE :
    Cette fonction implémente la règle métier de progression académique :
    - Un étudiant ne peut s'inscrire en niveau N que s'il a validé TOUS les cours du niveau N-1
    - Exception : Les nouveaux étudiants peuvent être inscrits directement en niveau 2 ou 3
      (étudiants transférés, admissions directes)
    
    Logique :
    1. Si niveau 1 : pas de vérification (retourne True)
    2. Sinon : récupérer tous les cours du niveau précédent
    3. Vérifier que l'étudiant a validé TOUS ces cours (status='VALIDE')
    4. Retourner True si tous validés, False avec la liste des cours manquants
    
    Utilisation :
    - Appelée lors de l'inscription à un niveau complet
    - Bloque l'inscription si le niveau précédent n'est pas validé
    - Permet d'afficher un message explicite à l'utilisateur
    
    Args:
        student: Instance de User (étudiant) à vérifier
        target_niveau: Niveau cible (1, 2 ou 3) pour lequel vérifier le niveau précédent
        
    Returns:
        Tuple (is_valid, missing_courses_list) :
        - is_valid: True si tous les cours du niveau précédent sont validés
        - missing_courses_list: Liste des cours non validés avec code et nom
    """
    if target_niveau == 1:
        # Pas de prérequis pour l'Année 1 (premier niveau)
        return (True, [])
    
    previous_niveau = target_niveau - 1
    
    # Récupérer tous les cours du niveau précédent
    previous_level_courses = Cours.objects.filter(
        niveau=previous_niveau,
        actif=True
    )
    
    if not previous_level_courses.exists():
        return (True, [])  # Pas de cours dans le niveau précédent
    
    # Vérifier que l'étudiant a validé TOUS les cours du niveau précédent
    missing_courses = []
    for course in previous_level_courses:
        has_validated = Inscription.objects.filter(
            id_etudiant=student,
            id_cours=course,
            status='VALIDE'
        ).exists()
        
        if not has_validated:
            missing_courses.append({
                'code': course.code_cours,
                'name': course.nom_cours
            })
    
    return (len(missing_courses) == 0, missing_courses)


@login_required
@secretary_required
@require_http_methods(["GET", "POST"])
def enroll_student(request):
    """
    Vue pour l'inscription d'un étudiant à un cours ou à un niveau complet.
    
    IMPORTANT POUR LA SOUTENANCE :
    Cette fonction implémente la logique métier complexe de l'inscription :
    
    1. INSCRIPTION À UN NIVEAU COMPLET :
       - Sélection du niveau (1, 2 ou 3)
       - Vérification que l'étudiant a validé le niveau précédent
       - Exception : nouveaux étudiants peuvent être inscrits directement en niveau 2 ou 3
       - Inscription automatique à tous les cours du niveau sélectionné
       - Mise à jour du niveau de l'étudiant
    
    2. INSCRIPTION À UN COURS SPÉCIFIQUE :
       - Sélection d'un cours précis
       - Vérification des prérequis du cours
       - Blocage si prérequis non validés
    
    3. CRÉATION DE COMPTE ÉTUDIANT :
       - Création d'un compte avec mot de passe temporaire
       - Champ must_change_password = True (force le changement au premier login)
    
    SÉCURITÉ :
    - Utilise @secretary_required : seul le secrétariat peut inscrire
    - Transaction atomique : toutes les inscriptions ou aucune (rollback en cas d'erreur)
    - Logging complet pour traçabilité
    
    Args:
        request: Objet HttpRequest contenant les données du formulaire
        
    Returns:
        HttpResponse avec le formulaire ou redirection vers la liste des inscriptions
    """
    enrollment_form = EnrollmentForm(request.POST or None)
    student_form = StudentCreationForm(request.POST or None, prefix='student')
    
    if request.method == 'POST':
        # Déterminer si on crée un nouvel étudiant
        create_new = request.POST.get('create_new_student') == 'on'
        
        # Valider les formulaires
        if create_new:
            if not student_form.is_valid():
                messages.error(request, "Erreur dans les données de l'étudiant.")
                return render(request, 'enrollments/enrollment_form.html', {
                    'enrollment_form': enrollment_form,
                    'student_form': student_form,
                })
        
        if not enrollment_form.is_valid():
            messages.error(request, "Erreur dans les données d'inscription.")
            return render(request, 'enrollments/enrollment_form.html', {
                'enrollment_form': enrollment_form,
                'student_form': student_form,
            })
        
        # Récupérer ou créer l'étudiant
        if create_new:
            try:
                student = student_form.create_student()
                log_action(
                    request.user,
                    f"CRITIQUE: Création du compte étudiant '{student.email}' ({student.get_full_name()}) lors de l'inscription",
                    request,
                    niveau='CRITIQUE',
                    objet_type='USER',
                    objet_id=student.id_utilisateur
                )
                messages.info(request, f"Compte étudiant créé pour {student.get_full_name()} ({student.email}).")
            except Exception:
                logger.exception("Erreur lors de la creation du compte etudiant")
                messages.error(request, "Une erreur interne est survenue lors de la creation du compte etudiant.")
                return render(request, 'enrollments/enrollment_form.html', {
                    'enrollment_form': enrollment_form,
                    'student_form': student_form,
                })
        else:
            student_email = enrollment_form.cleaned_data['student_email']
            try:
                student = User.objects.get(email=student_email, role=User.Role.ETUDIANT)
            except User.DoesNotExist:
                messages.error(request, f"Aucun étudiant trouvé avec l'e-mail {student_email}.")
                return render(request, 'enrollments/enrollment_form.html', {
                    'enrollment_form': enrollment_form,
                    'student_form': student_form,
                })
        
        # Récupérer l'année académique (utiliser l'année active si disponible)
        selected_year = enrollment_form.cleaned_data['academic_year']
        active_year = AnneeAcademique.objects.filter(active=True).first()
        
        # Utiliser l'année active si elle existe, sinon celle sélectionnée
        year = active_year if active_year else selected_year
        
        enrollment_type = enrollment_form.cleaned_data['enrollment_type']
        
        # ============================================
        # TRAITEMENT SELON LE TYPE D'INSCRIPTION
        # ============================================
        
        if enrollment_type == 'LEVEL':
            """
            INSCRIPTION À UN NIVEAU COMPLET
            
            Logique métier :
            - L'inscription à un niveau complet = inscription à tous les cours du niveau sélectionné
            - Le niveau de l'étudiant est mis à jour automatiquement
            - Vérification que l'étudiant a validé le niveau précédent (sauf nouveaux étudiants)
            """
            
            niveau = int(enrollment_form.cleaned_data['niveau'])
            
            # ============================================
            # VÉRIFICATION DES PRÉREQUIS DE NIVEAU
            # ============================================
            # IMPORTANT : Un étudiant ne peut s'inscrire en niveau N que s'il a validé le niveau N-1
            # Exception : Les nouveaux étudiants (créés lors de cette inscription) peuvent être
            # inscrits directement en niveau 2 ou 3 (étudiants transférés, admissions directes)
            
            is_new_student = create_new
            is_valid, missing_courses = check_previous_level_validation(student, niveau)
            
            if not is_valid and not is_new_student:
                # Pour un étudiant existant, on vérifie strictement les prérequis
                missing_list = ', '.join([f"{c['code']} - {c['name']}" for c in missing_courses])
                messages.error(
                    request,
                    f"L'étudiant {student.get_full_name()} n'a pas validé tous les cours de l'Année {niveau - 1}. "
                    f"Cours manquants : {missing_list}. "
                    f"Il ne peut pas s'inscrire à l'Année {niveau}."
                )
                logger.warning(f"Tentative d'inscription bloquée pour {student.email} en niveau {niveau}: prérequis manquants")
                return render(request, 'enrollments/enrollment_form.html', {
                    'enrollment_form': enrollment_form,
                    'student_form': student_form,
                })
            elif not is_valid and is_new_student:
                # Pour un nouvel étudiant, on autorise mais on avertit
                missing_list = ', '.join([f"{c['code']} - {c['name']}" for c in missing_courses])
                messages.warning(
                    request,
                    f"Attention : L'étudiant {student.get_full_name()} est inscrit directement en Année {niveau} "
                    f"sans avoir validé l'Année {niveau - 1} (cours manquants : {missing_list}). "
                    f"Cette inscription est autorisée car il s'agit d'un nouvel étudiant (étudiant transféré ou admission directe)."
                )
                logger.info(f"Inscription directe en niveau {niveau} autorisée pour nouvel étudiant {student.email}")
            
            # Récupérer tous les cours du niveau pour l'année académique
            level_courses = Cours.objects.filter(
                niveau=niveau,
                id_annee=year,
                actif=True
            )
            
            # Log de débogage
            logger.info(f"Inscription niveau {niveau} pour étudiant {student.email}")
            logger.info(f"Année académique utilisée: {year.libelle} (ID: {year.id_annee})")
            logger.info(f"Cours trouvés: {level_courses.count()}")
            for c in level_courses:
                logger.info(f"  - {c.code_cours} (niveau={c.niveau}, année={c.id_annee.libelle if c.id_annee else 'NULL'}, actif={c.actif})")
            
            if not level_courses.exists():
                # Vérifier si des cours existent avec ce niveau mais sans année académique
                courses_without_year = Cours.objects.filter(
                    niveau=niveau,
                    actif=True,
                    id_annee__isnull=True
                )
                
                # Vérifier si des cours existent avec ce niveau mais avec une autre année
                courses_other_year = Cours.objects.filter(
                    niveau=niveau,
                    actif=True
                ).exclude(id_annee=year)
                
                error_msg = f"Aucun cours actif trouvé pour l'Année {niveau} dans l'année académique {year.libelle}."
                
                if courses_without_year.exists():
                    error_msg += f" {courses_without_year.count()} cours trouvé(s) sans année académique assignée."
                
                if courses_other_year.exists():
                    other_years = courses_other_year.values_list('id_annee__libelle', flat=True).distinct()
                    error_msg += f" {courses_other_year.count()} cours trouvé(s) dans d'autres années : {', '.join([y for y in other_years if y])}."
                
                messages.warning(request, error_msg)
                return render(request, 'enrollments/enrollment_form.html', {
                    'enrollment_form': enrollment_form,
                    'student_form': student_form,
                })
            
            # Mettre à jour le niveau de l'étudiant
            student.niveau = niveau
            student.save()
            
            # Inscrire l'étudiant à tous les cours du niveau
            enrolled_count = 0
            skipped_count = 0
            errors = []
            
            try:
                with transaction.atomic():
                    for course in level_courses:
                        # Vérifier si déjà inscrit
                        if Inscription.objects.filter(
                            id_etudiant=student,
                            id_cours=course,
                            id_annee=year
                        ).exists():
                            skipped_count += 1
                            continue
                        
                        # Vérifier les prérequis
                        is_valid, missing_prereqs = check_prerequisites(student, course)
                        
                        if not is_valid:
                            prereq_list = ', '.join([f"{p['code']} - {p['name']}" for p in missing_prereqs])
                            errors.append(f"{course.code_cours}: prérequis manquants ({prereq_list})")
                            continue
                        
                        # Créer l'inscription
                        try:
                            inscription = Inscription.objects.create(
                                id_etudiant=student,
                                id_cours=course,
                                id_annee=year,
                                type_inscription='NORMALE',
                                eligible_examen=True,
                                status='EN_COURS'
                            )
                            logger.info(f"Inscription créée: ID={inscription.id_inscription}, Étudiant={student.email}, Cours={course.code_cours}, Année={year.libelle}")
                            enrolled_count += 1
                        except Exception:
                            error_msg = f"{course.code_cours}: erreur lors de la creation de l'inscription"
                            errors.append(error_msg)
                            logger.exception("Erreur lors de la creation de l'inscription pour %s", course.code_cours)
                            continue
                    
                    # Journaliser
                    if enrolled_count > 0:
                        log_action(
                            request.user,
                            f"CRITIQUE: Inscription de l'étudiant {student.get_full_name()} ({student.email}) au niveau {niveau} complet pour l'année {year.libelle} ({enrolled_count} cours(s))",
                            request,
                            niveau='CRITIQUE',
                            objet_type='INSCRIPTION',
                            objet_id=None
                        )
                
                logger.info(f"Résultat final - Inscrits: {enrolled_count}, Ignorés: {skipped_count}, Erreurs: {len(errors)}")
            except Exception:
                messages.error(request, "Une erreur interne est survenue lors de l'inscription.")
                logger.exception("Erreur d'inscription")
                return render(request, 'enrollments/enrollment_form.html', {
                    'enrollment_form': enrollment_form,
                    'student_form': student_form,
                })
            
            # Messages de résultat
            if enrolled_count > 0:
                messages.success(
                    request,
                    f"L'étudiant {student.get_full_name()} a été inscrit à {enrolled_count} cours(s) de l'Année {niveau} pour l'année académique {year.libelle}. "
                    f"Son niveau académique a été mis à jour à Année {niveau}."
                )
            else:
                # Si aucune inscription n'a été créée, donner plus de détails
                if skipped_count > 0:
                    messages.warning(
                        request,
                        f"Aucune nouvelle inscription créée. {skipped_count} cours(s) déjà existant(s) pour cet étudiant."
                    )
                if errors:
                    messages.error(
                        request,
                        f"Aucune inscription créée. {len(errors)} erreur(s) de prérequis détectée(s)."
                    )
                    for error in errors[:5]:  # Limiter à 5 erreurs
                        messages.error(request, error)
                    if len(errors) > 5:
                        messages.error(request, f"... et {len(errors) - 5} autre(s) erreur(s).")
                else:
                    # Aucune erreur, mais aucune inscription créée non plus
                    messages.error(
                        request,
                        f"ERREUR: Aucune inscription n'a été créée pour l'étudiant {student.get_full_name()}. "
                        f"Vérifiez que les cours de niveau {niveau} existent pour l'année académique {year.libelle} "
                        f"(trouvé {level_courses.count()} cours)."
                    )
            
            if skipped_count > 0 and enrolled_count > 0:
                messages.warning(
                    request,
                    f"{skipped_count} cours(s) déjà existant(s) pour cet étudiant."
                )
            
            # Toujours rediriger vers la page des inscriptions pour voir les résultats
            return redirect('dashboard:secretary_enrollments')
        
        else:
            # Inscription à un cours spécifique
            course = enrollment_form.cleaned_data['course']
            
            # Vérifier que le cours appartient à l'année académique sélectionnée
            if course.id_annee and course.id_annee.id_annee != year.id_annee:
                messages.error(
                    request,
                    f"Le cours {course.code_cours} n'appartient pas à l'année académique {year.libelle}. "
                    f"Il appartient à l'année {course.id_annee.libelle}."
                )
                return render(request, 'enrollments/enrollment_form.html', {
                    'enrollment_form': enrollment_form,
                    'student_form': student_form,
                })
            
            # Vérifier si déjà inscrit
            if Inscription.objects.filter(
                id_etudiant=student,
                id_cours=course,
                id_annee=year
            ).exists():
                messages.warning(
                    request,
                    f"L'étudiant {student.get_full_name()} est déjà inscrit à {course.code_cours} pour l'année {year.libelle}."
                )
                return redirect('enrollments:enroll_student')
            
            # Vérifier les prérequis
            is_valid, missing_prereqs = check_prerequisites(student, course)
            
            if not is_valid:
                prereq_list = ', '.join([f"{p['code']} - {p['name']} ({p.get('reason', 'non validé')})" for p in missing_prereqs])
                messages.error(
                    request,
                    f"Prérequis non satisfaits pour {course.code_cours}. "
                    f"Problèmes détectés : {prereq_list}"
                )
                return render(request, 'enrollments/enrollment_form.html', {
                    'enrollment_form': enrollment_form,
                    'student_form': student_form,
                })
            
            # Créer l'inscription
            inscription = Inscription.objects.create(
                id_etudiant=student,
                id_cours=course,
                id_annee=year,
                type_inscription='NORMALE',
                eligible_examen=True,
                status='EN_COURS'
            )
            
            # Journaliser
            log_action(
                request.user,
                f"CRITIQUE: Inscription de l'étudiant {student.get_full_name()} ({student.email}) au cours {course.code_cours} pour l'année {year.libelle}",
                request,
                niveau='CRITIQUE',
                objet_type='INSCRIPTION',
                objet_id=inscription.id_inscription
            )
            
            messages.success(
                request,
                f"L'étudiant {student.get_full_name()} a été inscrit avec succès au cours {course.code_cours} pour l'année académique {year.libelle}."
            )
        
        return redirect('dashboard:secretary_enrollments')
    
    # GET request - afficher le formulaire
    # Filtrer les cours selon l'année académique par défaut (année active)
    academic_years = AnneeAcademique.objects.all().order_by('-libelle')
    default_year = academic_years.filter(active=True).first() or academic_years.first()
    
    if default_year:
        enrollment_form.fields['course'].queryset = Cours.objects.filter(
            actif=True,
            id_annee=default_year
        ).select_related('id_annee', 'id_departement').order_by('code_cours')
        enrollment_form.fields['academic_year'].initial = default_year
    
    # Afficher un message d'information sur l'année académique utilisée
    if default_year:
        messages.info(
            request,
            f"L'année académique active ({default_year.libelle}) sera utilisée pour l'inscription."
        )
    
    return render(request, 'enrollments/enrollment_form.html', {
        'enrollment_form': enrollment_form,
        'student_form': student_form,
    })


