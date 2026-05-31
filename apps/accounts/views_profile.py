"""
Vues de profil du système de comptes UniAbsences.

Ce module contient les vues liées à la page de compte de l'utilisateur lui-même
et à l'export PDF libre-service du rapport d'absences.

Vues
----
``profile_view``
    Rend un template de profil spécifique au rôle (administrateur, secrétaire,
    professeur ou étudiant).  Les quatre variantes affichent le même bloc
    d'informations personnelles en lecture seule et les raccourcis de sécurité
    (changement de mot de passe, bascule 2FA).  Restreint aux utilisateurs
    authentifiés via ``@login_required`` ; seules les requêtes GET sont acceptées.

``download_report_pdf``
    Génère un PDF de résumé des absences par étudiant en utilisant
    ``generate_absence_report`` de ``apps.absences.utils``.  Seuls les étudiants
    peuvent accéder à ce point d'accès — chaque étudiant ne peut télécharger que
    son propre rapport.  Le nom de fichier est assaini avant d'être envoyé en
    en-tête ``Content-Disposition``.

Fait partie du système de comptes UniAbsences.
"""

import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET

from apps.absences.models import Absence
from apps.absences.utils import generate_absence_report
from apps.enrollments.models import Inscription

logger = logging.getLogger(__name__)


@login_required
@require_GET
def profile_view(request):
    """
    Rend la page de profil de l'utilisateur authentifié en utilisant le template spécifique au rôle.

    La page de profil est une vue en lecture seule des détails du compte
    personnel ainsi que des boutons d'accès rapide à la gestion du mot de
    passe et à la bascule 2FA.  Chacun des quatre rôles (ADMIN, SECRETAIRE,
    PROFESSEUR, ETUDIANT) possède son propre template qui étend la mise en
    page de base correspondante (barre latérale, navigation).

    Paramètres :
        request : La requête GET authentifiée.

    Retourne :
        HttpResponse : Le template de profil rendu avec les clés de contexte :
            - ``user`` — l'instance ``User`` courante.
            - ``two_factor_enabled`` — bool indiquant l'état de la 2FA.
    """
    user = request.user

    context = {
        "user": user,
        # Lire le drapeau 2FA en toute sécurité — vaut False par défaut pour tout
        # type d'utilisateur ne portant pas l'attribut (par ex. garde AnonymousUser).
        "two_factor_enabled": bool(getattr(user, "two_factor_enabled", False)),
    }

    # Sélectionner le template qui correspond au rôle de l'utilisateur afin que
    # la bonne mise en page de base (barre latérale, liens de navigation) soit héritée.
    if user.role == user.Role.ADMIN:
        template = "accounts/profile_admin.html"
    elif user.role == user.Role.SECRETAIRE:
        template = "accounts/profile_secretary.html"
    elif user.role == user.Role.PROFESSEUR:
        template = "accounts/profile_instructor.html"
    else:
        # ETUDIANT et tout rôle futur retombent sur le template étudiant.
        template = "accounts/profile_student.html"

    return render(request, template, context)


@login_required
@require_GET
def download_report_pdf(request):
    """
    Génère et transmet le résumé d'absences d'un étudiant en pièce jointe PDF.

    Seuls les comptes de rôle ETUDIANT peuvent appeler ce point d'accès ;
    tous les autres rôles sont redirigés vers le tableau de bord principal
    avec un message d'erreur.  Le rapport couvre l'année académique
    actuellement active (ou l'année la plus récente si aucune n'est marquée
    active) et inclut une ligne par cours inscrit avec :

    - Total des périodes de séance pour le cours.
    - Durée totale des absences non justifiées / en attente.
    - Taux d'absence calculé (pourcentage).
    - Statut d'éligibilité par rapport au seuil configuré.

    Le nom de fichier PDF est assaini pour ne contenir que des caractères
    alphanumériques, points, tirets et underscores afin d'éviter les
    injections d'en-tête ou les problèmes de système de fichiers.

    Paramètres :
        request : La requête GET authentifiée d'un étudiant.

    Retourne :
        HttpResponse : Une réponse ``application/pdf`` avec un en-tête
            ``Content-Disposition: attachment``, ou une redirection si
            l'utilisateur n'est pas un étudiant ou si une autre erreur survient.
    """
    from apps.absences.services import get_system_threshold
    from apps.accounts.models import User
    from apps.academic_sessions.models import AnneeAcademique

    user = request.user

    # Garde : seuls les étudiants sont autorisés à télécharger leur propre rapport.
    if user.role != User.Role.ETUDIANT:
        messages.error(request, "Accès réservé aux étudiants.")
        return redirect("dashboard:index")

    # Récupérer le seuil d'absence global du système utilisé par défaut lorsqu'un
    # cours ne définit pas son propre seuil.
    system_threshold = get_system_threshold()

    # Préférer l'année académique actuellement active ; retomber sur l'année la
    # plus récente si aucune n'est marquée active (par ex. pendant une transition d'année).
    active_year = AnneeAcademique.objects.filter(active=True).first()
    if not active_year:
        active_year = AnneeAcademique.objects.order_by("-id_annee").first()

    # Récupérer les inscriptions actuelles de l'étudiant, éventuellement limitées à l'année active.
    inscriptions = Inscription.objects.filter(
        id_etudiant=user, status=Inscription.Status.EN_COURS
    ).select_related("id_cours", "id_annee")
    if active_year:
        inscriptions = inscriptions.filter(id_annee=active_year)

    cours_data = []
    academic_year = active_year.libelle if active_year else "N/A"

    for ins in inscriptions:
        # Sommer uniquement les absences non justifiées et en attente pour le contrôle d'éligibilité.
        total_abs = (
            Absence.objects.filter(
                id_inscription=ins,
                statut__in=[Absence.Statut.NON_JUSTIFIEE, Absence.Statut.EN_ATTENTE],
            ).aggregate(total=Sum("duree_absence"))["total"]
            or 0
        )

        cours = ins.id_cours
        total_periodes = cours.nombre_total_periodes or 0
        # Le seuil au niveau du cours remplace la valeur système par défaut s'il est défini.
        seuil = (
            cours.seuil_absence if cours.seuil_absence is not None else system_threshold
        )
        # Taux d'absence en pourcentage ; 0 si le cours n'a aucune période enregistrée.
        absence_rate = (total_abs / total_periodes) * 100 if total_periodes > 0 else 0
        is_eligible = absence_rate < seuil

        cours_data.append(
            {
                "nom": cours.nom_cours,
                "total_periods": total_periodes,
                "duree_absence": total_abs,
                "absence_rate": absence_rate,
                "status": is_eligible,
            }
        )

    response = HttpResponse(content_type="application/pdf")
    # Assainir le nom de fichier : ne conserver que les caractères alphanumériques,
    # points, tirets et underscores pour empêcher l'injection d'en-tête et les problèmes de fichiers.
    filename_safe = "".join(
        c if c.isalnum() or c in "._-" else "_"
        for c in f"{user.prenom}_{user.nom}"
    )
    response["Content-Disposition"] = (
        f'attachment; filename="releve_absences_{filename_safe}.pdf"'
    )

    generate_absence_report(response, user, academic_year, cours_data)

    return response
