"""
Vues pour la gestion des inscriptions étudiantes.

Ce module contient les deux vues d'inscription principales utilisées par le secrétariat :

- ``enrollment_manager`` — page de liste en lecture seule affichant les facultés,
  les années académiques et les étudiants actifs, utilisée comme tableau de bord
  d'accueil pour le secrétaire.

- ``enroll_student`` — le formulaire d'inscription principal. Supporte deux modes :
    1. Inscription LEVEL — inscrit l'étudiant à tous les cours actifs pour une
       combinaison niveau/département/année donnée en une seule transaction atomique.
    2. Inscription COURSE — inscrit l'étudiant à un ou plusieurs cours
       sélectionnés individuellement.

  La vue peut également créer un nouveau compte étudiant à la volée (l'étudiant
  devra changer son mot de passe temporaire à la première connexion).

Security: les deux vues sont protégées par ``@secretary_required``.

Gestion des prérequis : les prérequis sont affichés uniquement comme
avertissements informatifs et ne bloquent jamais l'inscription. La vérification
des prérequis académiques (par ex. confirmer qu'un étudiant a réussi un cours
antérieur) relève du système d'administration académique, pas du suivi des absences.

Appartient à : UniAbsences — application enrollments.
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
    """
    Affiche la page d'accueil du gestionnaire d'inscriptions (lecture seule).

    Fournit au secrétaire une vue d'ensemble de toutes les facultés, années
    académiques et étudiants actifs. Aucune logique d'inscription n'est exécutée
    ici ; elle sert de hub de navigation et de point de départ du workflow
    d'inscription.

    Parameters
    ----------
    request : HttpRequest
        Doit être authentifié en tant que secrétaire.

    Returns
    -------
    HttpResponse
        Rend ``enrollments/manager.html`` avec le contexte :
          - ``facultes``        — toutes les facultés
          - ``academic_years``  — toutes les années académiques, plus récentes d'abord
          - ``students``        — tous les étudiants actifs
    """
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
    Gère l'inscription d'un étudiant via un formulaire à double mode (GET + POST).

    Enrollment modes
    ----------------
    LEVEL  — inscrit l'étudiant à chaque cours actif correspondant au niveau,
             département et année académique sélectionnés. Le champ ``niveau``
             de l'étudiant est mis à jour en conséquence.
    COURSE — inscrit l'étudiant à un ou plusieurs cours sélectionnés individuellement.

    Student account creation
    ------------------------
    Lorsque la case ``create_new_student`` est cochée, un nouvel enregistrement
    ``User`` est créé avec ``must_change_password=True`` afin que l'étudiant
    soit forcé de définir son propre mot de passe à la première connexion. La
    création du compte est journalisée dans la piste d'audit.

    En GET, le formulaire est pré-rempli avec l'année académique active et le
    queryset de cours correspondant trié par département puis code de cours.

    Parameters
    ----------
    request : HttpRequest
        Doit être authentifié en tant que secrétaire.

    Returns
    -------
    HttpResponse
        - GET  — rend ``enrollments/enrollment_form.html`` avec le formulaire pré-rempli.
        - POST (succès) — redirige vers ``dashboard:secretary_enrollments``.
        - POST (erreur) — ré-affiche le formulaire avec les messages de validation/conflit.
    """
    enrollment_form = EnrollmentForm(request.POST or None)
    student_form = StudentCreationForm(request.POST or None, prefix="student")

    if request.method == "POST":
        create_new = request.POST.get("create_new_student") == "on"

        # Valider d'abord le sous-formulaire de création d'étudiant lorsque la case est cochée.
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
            # Déduire le niveau de l'étudiant à partir du type d'inscription afin que le nouveau
            # compte reflète immédiatement le niveau académique correct.
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
            # Rechercher un étudiant existant par adresse e-mail.
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

        # Déléguer au handler approprié selon le mode sélectionné.
        if enrollment_type == "LEVEL":
            result = _handle_level_enrollment(request, student, enrollment_form, year)
        else:
            result = _handle_course_enrollment(request, student, enrollment_form, year)

        # None signifie que le handler a rencontré une erreur et a déjà ajouté des messages.
        if result is None:
            return render(
                request,
                "enrollments/enrollment_form.html",
                {"enrollment_form": enrollment_form, "student_form": student_form},
            )

        return redirect("dashboard:secretary_enrollments")

    # GET — pré-remplir le formulaire avec l'année académique active.
    academic_years = AnneeAcademique.objects.all().order_by("-libelle")
    default_year = academic_years.filter(active=True).first() or academic_years.first()

    if default_year:
        # Restreindre le queryset de cours à l'année active, trié pour la lisibilité.
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
