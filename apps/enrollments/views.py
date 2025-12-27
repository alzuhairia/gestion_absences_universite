from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.contrib import messages
from django.db.models import Q

from apps.accounts.models import User
from apps.academics.models import Faculte, Departement, Cours
from apps.academic_sessions.models import AnneeAcademique
from .models import Inscription
from apps.dashboard.decorators import secretary_required

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

@login_required
def get_departments(request):
    faculty_id = request.GET.get('faculty_id')
    departments = Departement.objects.filter(id_faculte_id=faculty_id).values('id_departement', 'nom_departement')
    data = [{'id': d['id_departement'], 'name': d['nom_departement']} for d in departments]
    return JsonResponse(data, safe=False)

@login_required
def get_courses(request):
    dept_id = request.GET.get('dept_id')
    courses = Cours.objects.filter(id_departement_id=dept_id)
    data = []
    for c in courses:
        data.append({
            'id': c.id_cours,
            'name': c.nom_cours,
            'has_prereq': c.prerequisites.exists()
        })
    return JsonResponse(data, safe=False)

@login_required
@secretary_required
@require_POST
def enroll_student(request):
    student_email = request.POST.get('student_email')
    course_id = request.POST.get('course')
    year_id = request.POST.get('academic_year')
    
    # 1. Validate Inputs
    try:
        student = User.objects.get(email=student_email, role=User.Role.ETUDIANT)
        course = Cours.objects.get(pk=course_id)
        year = AnneeAcademique.objects.get(pk=year_id)
    except (User.DoesNotExist, Cours.DoesNotExist, AnneeAcademique.DoesNotExist):
        messages.error(request, "Données invalides (Étudiant, Cours ou Année introuvable).")
        return redirect('dashboard:secretary_enrollments')

    # 2. Check Existing Enrollment
    if Inscription.objects.filter(id_etudiant=student, id_cours=course, id_annee=year).exists():
        messages.warning(request, f"L'étudiant {student.get_full_name()} est déjà inscrit à {course.code_cours} pour cette année.")
        return redirect('dashboard:secretary_enrollments')

    # 3. Prerequisite Check
    prerequisites = course.prerequisites.all()
    missing_prereqs = []
    
    for prereq in prerequisites:
        # Vérifier si l'étudiant a validé le prérequis (statut = 'VALIDE')
        has_validated = Inscription.objects.filter(
            id_etudiant=student,
            id_cours=prereq,
            status='VALIDE'
        ).exists()
        
        if not has_validated:
            missing_prereqs.append(f"{prereq.code_cours} - {prereq.nom_cours}")
    
    if missing_prereqs:
        msg = f"Prérequis non satisfaits pour {course.code_cours}. L'étudiant doit avoir validé : {', '.join(missing_prereqs)}"
        messages.error(request, msg)
        return redirect('dashboard:secretary_enrollments')

    # 4. Create Inscription
    Inscription.objects.create(
        id_etudiant=student,
        id_cours=course,
        id_annee=year,
        type_inscription='NORMALE',
        eligible_examen=True,
        status='EN_COURS'
    )
    
    from apps.audits.utils import log_action
    log_action(
        request.user,
        f"Secrétaire a inscrit l'étudiant {student.get_full_name()} ({student.email}) au cours {course.code_cours} pour l'année {year.libelle}",
        request,
        niveau='INFO',
        objet_type='INSCRIPTION',
        objet_id=None
    )
    messages.success(
        request, 
        f"L'étudiant {student.get_full_name()} a été inscrit avec succès au cours {course.code_cours} pour l'année académique {year.libelle}."
    )
    return redirect('dashboard:secretary_enrollments')
