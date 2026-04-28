"""
Interface de gestion des inscriptions étudiantes.

Fonctionnalités :
  - enrollment_manager : page liste (GET uniquement)
  - enroll_student     : formulaire d'inscription (GET + POST)
                         Mode NIVEAU — inscription à tous les cours d'un niveau
                         Mode COURS  — inscription à un ou plusieurs cours précis
  - get_prerequisite_info : helper — liste informative des prérequis (re-exporté depuis enrollment_handlers)

Peut créer un compte étudiant à la volée (must_change_password = True).
SÉCURITÉ : @secretary_required — seul le secrétariat peut inscrire.
"""
import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_http_methods

from apps.academic_sessions.models import AnneeAcademique
from apps.academics.models import Cours, Faculte
from apps.accounts.models import User
from apps.audits.utils import log_action
from apps.dashboard.decorators import secretary_required

from .enrollment_handlers import (  # noqa: F401
    get_prerequisite_info,
    _handle_level_enrollment,
    _handle_course_enrollment,
)
from .forms import EnrollmentForm, StudentCreationForm

logger = logging.getLogger(__name__)


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
        create_new = request.POST.get("create_new_student") == "on"

        if create_new:
            if not student_form.is_valid():
                messages.error(request, "Erreur dans les données de l'étudiant.")
                return render(
                    request,
                    "enrollments/enrollment_form.html",
                    {"enrollment_form": enrollment_form, "student_form": student_form},
                )

        if not enrollment_form.is_valid():
            messages.error(request, "Erreur dans les données d'inscription.")
            return render(
                request,
                "enrollments/enrollment_form.html",
                {"enrollment_form": enrollment_form, "student_form": student_form},
            )

        if create_new:
            enrollment_type = enrollment_form.cleaned_data["enrollment_type"]
            student_niveau = enrollment_form.cleaned_data["niveau"] if enrollment_type == "LEVEL" else None
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
                    {"enrollment_form": enrollment_form, "student_form": student_form},
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
                    {"enrollment_form": enrollment_form, "student_form": student_form},
                )

        year = enrollment_form.cleaned_data["academic_year"]
        enrollment_type = enrollment_form.cleaned_data["enrollment_type"]

        if enrollment_type == "LEVEL":
            result = _handle_level_enrollment(request, student, enrollment_form, year)
        else:
            result = _handle_course_enrollment(request, student, enrollment_form, year)

        if result is None:
            return render(
                request,
                "enrollments/enrollment_form.html",
                {"enrollment_form": enrollment_form, "student_form": student_form},
            )

        return redirect("dashboard:secretary_enrollments")

    # GET — afficher le formulaire
    academic_years = AnneeAcademique.objects.all().order_by("-libelle")
    default_year = academic_years.filter(active=True).first() or academic_years.first()

    if default_year:
        enrollment_form.fields["courses"].queryset = (
            Cours.objects.filter(actif=True, id_annee=default_year)
            .select_related("id_annee", "id_departement")
            .order_by("id_departement__nom_departement", "code_cours")
        )
        enrollment_form.fields["academic_year"].initial = default_year

    if default_year:
        messages.info(
            request,
            f"L'année académique active ({default_year.libelle}) sera utilisée pour l'inscription.",
        )

    return render(
        request,
        "enrollments/enrollment_form.html",
        {"enrollment_form": enrollment_form, "student_form": student_form},
    )
