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
    """API pour rÃƒÂ©cupÃƒÂ©rer les cours d'un dÃƒÂ©partement pour une annÃƒÂ©e acadÃƒÂ©mique"""
    if getattr(request, 'limited', False):
        return api_error('Trop de requetes. Reessayez plus tard.', status=429, code='rate_limited')
    try:
        dept_id = request.GET.get('dept_id')
        year_id = request.GET.get('year_id')

        courses = Cours.objects.filter(id_departement_id=dept_id, actif=True).select_related(
            'id_annee',
            'id_departement',
        )

        # Filtrer par annÃƒÂ©e acadÃƒÂ©mique si fournie
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
    """API pour rÃƒÂ©cupÃƒÂ©rer tous les cours d'une annÃƒÂ©e acadÃƒÂ©mique"""
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

def check_prerequisites(student, course):
    """
    VÃƒÂ©rifie si l'ÃƒÂ©tudiant a validÃƒÂ© tous les prÃƒÂ©requis d'un cours.
    Les prÃƒÂ©requis doivent ÃƒÂªtre d'annÃƒÂ©es acadÃƒÂ©miques infÃƒÂ©rieures.
    Retourne (is_valid, missing_prereqs_list)
    """
    prerequisites = course.prerequisites.all()
    missing_prereqs = []
    
    # RÃƒÂ©cupÃƒÂ©rer l'annÃƒÂ©e du cours
    course_year = course.id_annee
    
    for prereq in prerequisites:
        # VÃƒÂ©rifier que le prÃƒÂ©requis est d'une annÃƒÂ©e infÃƒÂ©rieure
        if prereq.id_annee and course_year:
            # Comparer les annÃƒÂ©es (on suppose que le libellÃƒÂ© suit un format AAAA-AAAA)
            # On peut aussi comparer par ID si les annÃƒÂ©es sont triÃƒÂ©es
            prereq_year = prereq.id_annee
            if prereq_year.id_annee >= course_year.id_annee:
                # Le prÃƒÂ©requis ne devrait pas ÃƒÂªtre d'une annÃƒÂ©e supÃƒÂ©rieure ou ÃƒÂ©gale
                # Ce cas ne devrait pas arriver si la validation du formulaire est correcte
                missing_prereqs.append({
                    'code': prereq.code_cours,
                    'name': prereq.nom_cours,
                    'year': prereq_year.libelle,
                    'reason': 'Le prÃƒÂ©requis doit ÃƒÂªtre d\'une annÃƒÂ©e acadÃƒÂ©mique infÃƒÂ©rieure'
                })
                continue
        
        # VÃƒÂ©rifier si l'ÃƒÂ©tudiant a validÃƒÂ© le prÃƒÂ©requis (statut = 'VALIDE')
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
                'reason': 'PrÃƒÂ©requis non validÃƒÂ©'
            })
    
    return (len(missing_prereqs) == 0, missing_prereqs)


def check_previous_level_validation(student, target_niveau):
    """
    VÃƒÂ©rifie si l'ÃƒÂ©tudiant a validÃƒÂ© TOUS les cours du niveau prÃƒÂ©cÃƒÂ©dent.
    
    IMPORTANT POUR LA SOUTENANCE :
    Cette fonction implÃƒÂ©mente la rÃƒÂ¨gle mÃƒÂ©tier de progression acadÃƒÂ©mique :
    - Un ÃƒÂ©tudiant ne peut s'inscrire en niveau N que s'il a validÃƒÂ© TOUS les cours du niveau N-1
    - Exception : Les nouveaux ÃƒÂ©tudiants peuvent ÃƒÂªtre inscrits directement en niveau 2 ou 3
      (ÃƒÂ©tudiants transfÃƒÂ©rÃƒÂ©s, admissions directes)
    
    Logique :
    1. Si niveau 1 : pas de vÃƒÂ©rification (retourne True)
    2. Sinon : rÃƒÂ©cupÃƒÂ©rer tous les cours du niveau prÃƒÂ©cÃƒÂ©dent
    3. VÃƒÂ©rifier que l'ÃƒÂ©tudiant a validÃƒÂ© TOUS ces cours (status='VALIDE')
    4. Retourner True si tous validÃƒÂ©s, False avec la liste des cours manquants
    
    Utilisation :
    - AppelÃƒÂ©e lors de l'inscription ÃƒÂ  un niveau complet
    - Bloque l'inscription si le niveau prÃƒÂ©cÃƒÂ©dent n'est pas validÃƒÂ©
    - Permet d'afficher un message explicite ÃƒÂ  l'utilisateur
    
    Args:
        student: Instance de User (ÃƒÂ©tudiant) ÃƒÂ  vÃƒÂ©rifier
        target_niveau: Niveau cible (1, 2 ou 3) pour lequel vÃƒÂ©rifier le niveau prÃƒÂ©cÃƒÂ©dent
        
    Returns:
        Tuple (is_valid, missing_courses_list) :
        - is_valid: True si tous les cours du niveau prÃƒÂ©cÃƒÂ©dent sont validÃƒÂ©s
        - missing_courses_list: Liste des cours non validÃƒÂ©s avec code et nom
    """
    if target_niveau == 1:
        # Pas de prÃƒÂ©requis pour l'AnnÃƒÂ©e 1 (premier niveau)
        return (True, [])
    
    previous_niveau = target_niveau - 1
    
    # RÃƒÂ©cupÃƒÂ©rer tous les cours du niveau prÃƒÂ©cÃƒÂ©dent
    previous_level_courses = Cours.objects.filter(
        niveau=previous_niveau,
        actif=True
    )
    
    if not previous_level_courses.exists():
        return (True, [])  # Pas de cours dans le niveau prÃƒÂ©cÃƒÂ©dent
    
    # VÃƒÂ©rifier que l'ÃƒÂ©tudiant a validÃƒÂ© TOUS les cours du niveau prÃƒÂ©cÃƒÂ©dent
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
    Vue pour l'inscription d'un ÃƒÂ©tudiant ÃƒÂ  un cours ou ÃƒÂ  un niveau complet.
    
    IMPORTANT POUR LA SOUTENANCE :
    Cette fonction implÃƒÂ©mente la logique mÃƒÂ©tier complexe de l'inscription :
    
    1. INSCRIPTION Ãƒâ‚¬ UN NIVEAU COMPLET :
       - SÃƒÂ©lection du niveau (1, 2 ou 3)
       - VÃƒÂ©rification que l'ÃƒÂ©tudiant a validÃƒÂ© le niveau prÃƒÂ©cÃƒÂ©dent
       - Exception : nouveaux ÃƒÂ©tudiants peuvent ÃƒÂªtre inscrits directement en niveau 2 ou 3
       - Inscription automatique ÃƒÂ  tous les cours du niveau sÃƒÂ©lectionnÃƒÂ©
       - Mise ÃƒÂ  jour du niveau de l'ÃƒÂ©tudiant
    
    2. INSCRIPTION Ãƒâ‚¬ UN COURS SPÃƒâ€°CIFIQUE :
       - SÃƒÂ©lection d'un cours prÃƒÂ©cis
       - VÃƒÂ©rification des prÃƒÂ©requis du cours
       - Blocage si prÃƒÂ©requis non validÃƒÂ©s
    
    3. CRÃƒâ€°ATION DE COMPTE Ãƒâ€°TUDIANT :
       - CrÃƒÂ©ation d'un compte avec mot de passe temporaire
       - Champ must_change_password = True (force le changement au premier login)
    
    SÃƒâ€°CURITÃƒâ€° :
    - Utilise @secretary_required : seul le secrÃƒÂ©tariat peut inscrire
    - Transaction atomique : toutes les inscriptions ou aucune (rollback en cas d'erreur)
    - Logging complet pour traÃƒÂ§abilitÃƒÂ©
    
    Args:
        request: Objet HttpRequest contenant les donnÃƒÂ©es du formulaire
        
    Returns:
        HttpResponse avec le formulaire ou redirection vers la liste des inscriptions
    """
    enrollment_form = EnrollmentForm(request.POST or None)
    student_form = StudentCreationForm(request.POST or None, prefix='student')
    
    if request.method == 'POST':
        # DÃƒÂ©terminer si on crÃƒÂ©e un nouvel ÃƒÂ©tudiant
        create_new = request.POST.get('create_new_student') == 'on'
        
        # Valider les formulaires
        if create_new:
            if not student_form.is_valid():
                messages.error(request, "Erreur dans les donnÃƒÂ©es de l'ÃƒÂ©tudiant.")
                return render(request, 'enrollments/enrollment_form.html', {
                    'enrollment_form': enrollment_form,
                    'student_form': student_form,
                })
        
        if not enrollment_form.is_valid():
            messages.error(request, "Erreur dans les donnÃƒÂ©es d'inscription.")
            return render(request, 'enrollments/enrollment_form.html', {
                'enrollment_form': enrollment_form,
                'student_form': student_form,
            })
        
        # RÃƒÂ©cupÃƒÂ©rer ou crÃƒÂ©er l'ÃƒÂ©tudiant
        if create_new:
            try:
                student = student_form.create_student()
                log_action(
                    request.user,
                    f"CRITIQUE: CrÃƒÂ©ation du compte ÃƒÂ©tudiant '{student.email}' ({student.get_full_name()}) lors de l'inscription",
                    request,
                    niveau='CRITIQUE',
                    objet_type='USER',
                    objet_id=student.id_utilisateur
                )
                messages.info(request, f"Compte ÃƒÂ©tudiant crÃƒÂ©ÃƒÂ© pour {student.get_full_name()} ({student.email}).")
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
                messages.error(request, f"Aucun ÃƒÂ©tudiant trouvÃƒÂ© avec l'e-mail {student_email}.")
                return render(request, 'enrollments/enrollment_form.html', {
                    'enrollment_form': enrollment_form,
                    'student_form': student_form,
                })
        
        # RÃƒÂ©cupÃƒÂ©rer l'annÃƒÂ©e acadÃƒÂ©mique (utiliser l'annÃƒÂ©e active si disponible)
        selected_year = enrollment_form.cleaned_data['academic_year']
        active_year = AnneeAcademique.objects.filter(active=True).first()
        
        # Utiliser l'annÃƒÂ©e active si elle existe, sinon celle sÃƒÂ©lectionnÃƒÂ©e
        year = active_year if active_year else selected_year
        
        enrollment_type = enrollment_form.cleaned_data['enrollment_type']
        
        # ============================================
        # TRAITEMENT SELON LE TYPE D'INSCRIPTION
        # ============================================
        
        if enrollment_type == 'LEVEL':
            """
            INSCRIPTION Ãƒâ‚¬ UN NIVEAU COMPLET
            
            Logique mÃƒÂ©tier :
            - L'inscription ÃƒÂ  un niveau complet = inscription ÃƒÂ  tous les cours du niveau sÃƒÂ©lectionnÃƒÂ©
            - Le niveau de l'ÃƒÂ©tudiant est mis ÃƒÂ  jour automatiquement
            - VÃƒÂ©rification que l'ÃƒÂ©tudiant a validÃƒÂ© le niveau prÃƒÂ©cÃƒÂ©dent (sauf nouveaux ÃƒÂ©tudiants)
            """
            
            niveau = int(enrollment_form.cleaned_data['niveau'])
            
            # ============================================
            # VÃƒâ€°RIFICATION DES PRÃƒâ€°REQUIS DE NIVEAU
            # ============================================
            # IMPORTANT : Un ÃƒÂ©tudiant ne peut s'inscrire en niveau N que s'il a validÃƒÂ© le niveau N-1
            # Exception : Les nouveaux ÃƒÂ©tudiants (crÃƒÂ©ÃƒÂ©s lors de cette inscription) peuvent ÃƒÂªtre
            # inscrits directement en niveau 2 ou 3 (ÃƒÂ©tudiants transfÃƒÂ©rÃƒÂ©s, admissions directes)
            
            is_new_student = create_new
            is_valid, missing_courses = check_previous_level_validation(student, niveau)
            
            if not is_valid and not is_new_student:
                # Pour un ÃƒÂ©tudiant existant, on vÃƒÂ©rifie strictement les prÃƒÂ©requis
                missing_list = ', '.join([f"{c['code']} - {c['name']}" for c in missing_courses])
                messages.error(
                    request,
                    f"L'ÃƒÂ©tudiant {student.get_full_name()} n'a pas validÃƒÂ© tous les cours de l'AnnÃƒÂ©e {niveau - 1}. "
                    f"Cours manquants : {missing_list}. "
                    f"Il ne peut pas s'inscrire ÃƒÂ  l'AnnÃƒÂ©e {niveau}."
                )
                logger.warning(f"Tentative d'inscription bloquÃƒÂ©e pour {student.email} en niveau {niveau}: prÃƒÂ©requis manquants")
                return render(request, 'enrollments/enrollment_form.html', {
                    'enrollment_form': enrollment_form,
                    'student_form': student_form,
                })
            elif not is_valid and is_new_student:
                # Pour un nouvel ÃƒÂ©tudiant, on autorise mais on avertit
                missing_list = ', '.join([f"{c['code']} - {c['name']}" for c in missing_courses])
                messages.warning(
                    request,
                    f"Attention : L'ÃƒÂ©tudiant {student.get_full_name()} est inscrit directement en AnnÃƒÂ©e {niveau} "
                    f"sans avoir validÃƒÂ© l'AnnÃƒÂ©e {niveau - 1} (cours manquants : {missing_list}). "
                    f"Cette inscription est autorisÃƒÂ©e car il s'agit d'un nouvel ÃƒÂ©tudiant (ÃƒÂ©tudiant transfÃƒÂ©rÃƒÂ© ou admission directe)."
                )
                logger.info(f"Inscription directe en niveau {niveau} autorisÃƒÂ©e pour nouvel ÃƒÂ©tudiant {student.email}")
            
            # RÃƒÂ©cupÃƒÂ©rer tous les cours du niveau pour l'annÃƒÂ©e acadÃƒÂ©mique
            level_courses = Cours.objects.filter(
                niveau=niveau,
                id_annee=year,
                actif=True
            )
            
            # Log de dÃƒÂ©bogage
            logger.info(f"Inscription niveau {niveau} pour ÃƒÂ©tudiant {student.email}")
            logger.info(f"AnnÃƒÂ©e acadÃƒÂ©mique utilisÃƒÂ©e: {year.libelle} (ID: {year.id_annee})")
            logger.info(f"Cours trouvÃƒÂ©s: {level_courses.count()}")
            for c in level_courses:
                logger.info(f"  - {c.code_cours} (niveau={c.niveau}, annÃƒÂ©e={c.id_annee.libelle if c.id_annee else 'NULL'}, actif={c.actif})")
            
            if not level_courses.exists():
                # VÃƒÂ©rifier si des cours existent avec ce niveau mais sans annÃƒÂ©e acadÃƒÂ©mique
                courses_without_year = Cours.objects.filter(
                    niveau=niveau,
                    actif=True,
                    id_annee__isnull=True
                )
                
                # VÃƒÂ©rifier si des cours existent avec ce niveau mais avec une autre annÃƒÂ©e
                courses_other_year = Cours.objects.filter(
                    niveau=niveau,
                    actif=True
                ).exclude(id_annee=year)
                
                error_msg = f"Aucun cours actif trouvÃƒÂ© pour l'AnnÃƒÂ©e {niveau} dans l'annÃƒÂ©e acadÃƒÂ©mique {year.libelle}."
                
                if courses_without_year.exists():
                    error_msg += f" {courses_without_year.count()} cours trouvÃƒÂ©(s) sans annÃƒÂ©e acadÃƒÂ©mique assignÃƒÂ©e."
                
                if courses_other_year.exists():
                    other_years = courses_other_year.values_list('id_annee__libelle', flat=True).distinct()
                    error_msg += f" {courses_other_year.count()} cours trouvÃƒÂ©(s) dans d'autres annÃƒÂ©es : {', '.join([y for y in other_years if y])}."
                
                messages.warning(request, error_msg)
                return render(request, 'enrollments/enrollment_form.html', {
                    'enrollment_form': enrollment_form,
                    'student_form': student_form,
                })
            
            # Mettre ÃƒÂ  jour le niveau de l'ÃƒÂ©tudiant
            student.niveau = niveau
            student.save()
            
            # Inscrire l'ÃƒÂ©tudiant ÃƒÂ  tous les cours du niveau
            enrolled_count = 0
            skipped_count = 0
            errors = []
            
            try:
                with transaction.atomic():
                    for course in level_courses:
                        # VÃƒÂ©rifier si dÃƒÂ©jÃƒÂ  inscrit
                        if Inscription.objects.filter(
                            id_etudiant=student,
                            id_cours=course,
                            id_annee=year
                        ).exists():
                            skipped_count += 1
                            continue
                        
                        # VÃƒÂ©rifier les prÃƒÂ©requis
                        is_valid, missing_prereqs = check_prerequisites(student, course)
                        
                        if not is_valid:
                            prereq_list = ', '.join([f"{p['code']} - {p['name']}" for p in missing_prereqs])
                            errors.append(f"{course.code_cours}: prÃƒÂ©requis manquants ({prereq_list})")
                            continue
                        
                        # CrÃƒÂ©er l'inscription
                        try:
                            inscription = Inscription.objects.create(
                                id_etudiant=student,
                                id_cours=course,
                                id_annee=year,
                                type_inscription='NORMALE',
                                eligible_examen=True,
                                status='EN_COURS'
                            )
                            logger.info(f"Inscription crÃƒÂ©ÃƒÂ©e: ID={inscription.id_inscription}, Ãƒâ€°tudiant={student.email}, Cours={course.code_cours}, AnnÃƒÂ©e={year.libelle}")
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
                            f"CRITIQUE: Inscription de l'ÃƒÂ©tudiant {student.get_full_name()} ({student.email}) au niveau {niveau} complet pour l'annÃƒÂ©e {year.libelle} ({enrolled_count} cours(s))",
                            request,
                            niveau='CRITIQUE',
                            objet_type='INSCRIPTION',
                            objet_id=None
                        )
                
                logger.info(f"RÃƒÂ©sultat final - Inscrits: {enrolled_count}, IgnorÃƒÂ©s: {skipped_count}, Erreurs: {len(errors)}")
            except Exception:
                messages.error(request, "Une erreur interne est survenue lors de l'inscription.")
                logger.exception("Erreur d'inscription")
                return render(request, 'enrollments/enrollment_form.html', {
                    'enrollment_form': enrollment_form,
                    'student_form': student_form,
                })
            
            # Messages de rÃƒÂ©sultat
            if enrolled_count > 0:
                messages.success(
                    request,
                    f"L'ÃƒÂ©tudiant {student.get_full_name()} a ÃƒÂ©tÃƒÂ© inscrit ÃƒÂ  {enrolled_count} cours(s) de l'AnnÃƒÂ©e {niveau} pour l'annÃƒÂ©e acadÃƒÂ©mique {year.libelle}. "
                    f"Son niveau acadÃƒÂ©mique a ÃƒÂ©tÃƒÂ© mis ÃƒÂ  jour ÃƒÂ  AnnÃƒÂ©e {niveau}."
                )
            else:
                # Si aucune inscription n'a ÃƒÂ©tÃƒÂ© crÃƒÂ©ÃƒÂ©e, donner plus de dÃƒÂ©tails
                if skipped_count > 0:
                    messages.warning(
                        request,
                        f"Aucune nouvelle inscription crÃƒÂ©ÃƒÂ©e. {skipped_count} cours(s) dÃƒÂ©jÃƒÂ  existant(s) pour cet ÃƒÂ©tudiant."
                    )
                if errors:
                    messages.error(
                        request,
                        f"Aucune inscription crÃƒÂ©ÃƒÂ©e. {len(errors)} erreur(s) de prÃƒÂ©requis dÃƒÂ©tectÃƒÂ©e(s)."
                    )
                    for error in errors[:5]:  # Limiter ÃƒÂ  5 erreurs
                        messages.error(request, error)
                    if len(errors) > 5:
                        messages.error(request, f"... et {len(errors) - 5} autre(s) erreur(s).")
                else:
                    # Aucune erreur, mais aucune inscription crÃƒÂ©ÃƒÂ©e non plus
                    messages.error(
                        request,
                        f"ERREUR: Aucune inscription n'a ÃƒÂ©tÃƒÂ© crÃƒÂ©ÃƒÂ©e pour l'ÃƒÂ©tudiant {student.get_full_name()}. "
                        f"VÃƒÂ©rifiez que les cours de niveau {niveau} existent pour l'annÃƒÂ©e acadÃƒÂ©mique {year.libelle} "
                        f"(trouvÃƒÂ© {level_courses.count()} cours)."
                    )
            
            if skipped_count > 0 and enrolled_count > 0:
                messages.warning(
                    request,
                    f"{skipped_count} cours(s) dÃƒÂ©jÃƒÂ  existant(s) pour cet ÃƒÂ©tudiant."
                )
            
            # Toujours rediriger vers la page des inscriptions pour voir les rÃƒÂ©sultats
            return redirect('dashboard:secretary_enrollments')
        
        else:
            # Inscription ÃƒÂ  un cours spÃƒÂ©cifique
            course = enrollment_form.cleaned_data['course']
            
            # VÃƒÂ©rifier que le cours appartient ÃƒÂ  l'annÃƒÂ©e acadÃƒÂ©mique sÃƒÂ©lectionnÃƒÂ©e
            if course.id_annee and course.id_annee.id_annee != year.id_annee:
                messages.error(
                    request,
                    f"Le cours {course.code_cours} n'appartient pas ÃƒÂ  l'annÃƒÂ©e acadÃƒÂ©mique {year.libelle}. "
                    f"Il appartient ÃƒÂ  l'annÃƒÂ©e {course.id_annee.libelle}."
                )
                return render(request, 'enrollments/enrollment_form.html', {
                    'enrollment_form': enrollment_form,
                    'student_form': student_form,
                })
            
            # VÃƒÂ©rifier si dÃƒÂ©jÃƒÂ  inscrit
            if Inscription.objects.filter(
                id_etudiant=student,
                id_cours=course,
                id_annee=year
            ).exists():
                messages.warning(
                    request,
                    f"L'ÃƒÂ©tudiant {student.get_full_name()} est dÃƒÂ©jÃƒÂ  inscrit ÃƒÂ  {course.code_cours} pour l'annÃƒÂ©e {year.libelle}."
                )
                return redirect('enrollments:enroll_student')
            
            # VÃƒÂ©rifier les prÃƒÂ©requis
            is_valid, missing_prereqs = check_prerequisites(student, course)
            
            if not is_valid:
                prereq_list = ', '.join([f"{p['code']} - {p['name']} ({p.get('reason', 'non validÃƒÂ©')})" for p in missing_prereqs])
                messages.error(
                    request,
                    f"PrÃƒÂ©requis non satisfaits pour {course.code_cours}. "
                    f"ProblÃƒÂ¨mes dÃƒÂ©tectÃƒÂ©s : {prereq_list}"
                )
                return render(request, 'enrollments/enrollment_form.html', {
                    'enrollment_form': enrollment_form,
                    'student_form': student_form,
                })
            
            # CrÃƒÂ©er l'inscription
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
                f"CRITIQUE: Inscription de l'ÃƒÂ©tudiant {student.get_full_name()} ({student.email}) au cours {course.code_cours} pour l'annÃƒÂ©e {year.libelle}",
                request,
                niveau='CRITIQUE',
                objet_type='INSCRIPTION',
                objet_id=inscription.id_inscription
            )
            
            messages.success(
                request,
                f"L'ÃƒÂ©tudiant {student.get_full_name()} a ÃƒÂ©tÃƒÂ© inscrit avec succÃƒÂ¨s au cours {course.code_cours} pour l'annÃƒÂ©e acadÃƒÂ©mique {year.libelle}."
            )
        
        return redirect('dashboard:secretary_enrollments')
    
    # GET request - afficher le formulaire
    # Filtrer les cours selon l'annÃƒÂ©e acadÃƒÂ©mique par dÃƒÂ©faut (annÃƒÂ©e active)
    academic_years = AnneeAcademique.objects.all().order_by('-libelle')
    default_year = academic_years.filter(active=True).first() or academic_years.first()
    
    if default_year:
        enrollment_form.fields['course'].queryset = Cours.objects.filter(
            actif=True,
            id_annee=default_year
        ).select_related('id_annee', 'id_departement').order_by('code_cours')
        enrollment_form.fields['academic_year'].initial = default_year
    
    # Afficher un message d'information sur l'annÃƒÂ©e acadÃƒÂ©mique utilisÃƒÂ©e
    if default_year:
        messages.info(
            request,
            f"L'annÃƒÂ©e acadÃƒÂ©mique active ({default_year.libelle}) sera utilisÃƒÂ©e pour l'inscription."
        )
    
    return render(request, 'enrollments/enrollment_form.html', {
        'enrollment_form': enrollment_form,
        'student_form': student_form,
    })


