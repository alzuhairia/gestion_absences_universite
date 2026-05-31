"""
Vue principale du tableau de bord professeur pour le système UniAbsences.

Ce module implémente la page d'accueil du tableau de bord professeur. Elle
affiche des KPI de haut niveau pour le professeur authentifié et une courte
liste d'étudiants bloqués ou actuellement protégés par un bouclier d'exemption.

KPI affichés
------------
- Nombre de cours actifs (cours avec ``actif=True`` assignés à ce professeur).
- Séances tenues dans l'année académique active (séances passées, date < today).
- Séances à venir dans l'année académique active (date >= today).
- Total des événements d'absence enregistrés sur les cours du professeur cette année.

Liste des étudiants à risque
----------------------------
La vue itère sur toutes les inscriptions EN_COURS dans les cours du professeur
et classe chacune comme :
    - ``BLOQUÉ``         — taux d'absence non justifiée >= seuil effectif.
    - ``SOUS EXEMPTION`` — taux >= seuil de base mais inférieur au seuil
                           d'exemption rehaussé (l'étudiant détient une exemption_40).

Seules les 5 premières entrées sont passées au template pour garder la carte
du tableau de bord concise.

Note de sécurité
----------------
Cette vue est strictement en lecture seule pour les données étudiantes. Aucune
action administrative (modification d'inscription, encodage d'absence, etc.)
ne peut être effectuée via cette vue.

Fait partie du système de tableau de bord UniAbsences.
"""

from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_GET

from apps.absences.models import Absence
from apps.academic_sessions.models import AnneeAcademique, Seance
from apps.academics.models import Cours
from apps.dashboard.decorators import professor_required
from apps.enrollments.models import Inscription


@login_required
@professor_required
@require_GET
def instructor_dashboard(request):
    """
    Rend le tableau de bord principal du professeur avec les KPI et la liste des étudiants à risque.

    Toutes les données sont limitées à l'année académique active. Lorsqu'aucune
    année n'est marquée active, l'année créée le plus récemment est utilisée
    comme repli (mais les KPI de séances et d'absences sont mis à 0 si aucune
    année n'existe).

    Parameters
    ----------
    request : HttpRequest
        Doit être une requête GET émise par un professeur authentifié.

    Returns
    -------
    HttpResponse
        Rend ``dashboard/instructor_index.html`` avec le contexte suivant :

        ``academic_year`` : AnneeAcademique or None
        ``active_courses_count`` : int
        ``sessions_given`` : int
            Séances passées (date_seance < today) dans l'année active.
        ``upcoming_sessions`` : int
            Séances futures (date_seance >= today) dans l'année active.
        ``total_absences`` : int
            Total des enregistrements d'absence sur tous les cours du professeur cette année.
        ``at_risk_count`` : int
            Nombre d'étudiants au niveau ou au-dessus de leur seuil effectif.
        ``at_risk_list`` : list[dict]
            Jusqu'à 5 entrées ; chaque dict possède les clés : etudiant, cours,
            total_abs, rate, inscription_id, is_exempted, status_label,
            status_color.
    """
    academic_year = AnneeAcademique.objects.filter(active=True).first()
    if not academic_year:
        academic_year = AnneeAcademique.objects.order_by("-id_annee").first()

    today = timezone.localdate()

    # KPI 1 : nombre de cours actifs (indépendant de l'année académique).
    active_courses_count = Cours.objects.filter(professeur=request.user, actif=True).count()

    if academic_year:
        # KPI 2 & 3 : séances passées vs. à venir pour l'année active.
        sessions_given = Seance.objects.filter(
            id_cours__professeur=request.user,
            id_annee=academic_year,
            date_seance__lt=today,
        ).count()
        upcoming_sessions = Seance.objects.filter(
            id_cours__professeur=request.user,
            id_annee=academic_year,
            date_seance__gte=today,
        ).count()
        # KPI 4 : total des enregistrements d'absence (tous statuts) pour cette année.
        total_absences = Absence.objects.filter(
            id_seance__id_cours__professeur=request.user,
            id_seance__id_annee=academic_year,
        ).count()
    else:
        # Aucune année académique configurée — retourner zéro pour les KPI dépendants de l'année.
        sessions_given = 0
        upcoming_sessions = 0
        total_absences = 0

    # Récupérer toutes les inscriptions EN_COURS sur les cours du professeur.
    all_inscriptions_qs = Inscription.objects.filter(
        id_cours__professeur=request.user, status=Inscription.Status.EN_COURS
    ).select_related("id_cours", "id_etudiant")
    if academic_year:
        all_inscriptions_qs = all_inscriptions_qs.filter(id_annee=academic_year)

    all_inscriptions = list(all_inscriptions_qs)
    inscription_ids = [ins.id_inscription for ins in all_inscriptions]

    # Agréger les heures d'absence non justifiées par inscription (séances passées uniquement).
    absence_sums = dict(
        Absence.objects.filter(
            id_inscription__in=inscription_ids,
            statut=Absence.Statut.NON_JUSTIFIEE,
            id_seance__date_seance__lte=today,
        )
        .values("id_inscription")
        .annotate(total=Sum("duree_absence"))
        .values_list("id_inscription", "total")
    )

    at_risk_count = 0
    at_risk_list = []

    for ins in all_inscriptions:
        cours = ins.id_cours
        if cours.nombre_total_periodes > 0:
            total_abs = float(absence_sums.get(ins.id_inscription, 0) or 0)
            rate = (total_abs / cours.nombre_total_periodes) * 100
            seuil = cours.get_seuil_absence()
            # Rehausser le seuil pour les étudiants exemptés (plafonné à 100 %).
            seuil_effectif = min(seuil + ins.exemption_margin, 100) if ins.exemption_40 else seuil

            if rate >= seuil_effectif:
                # L'étudiant a dépassé le seuil effectif (possiblement rehaussé).
                at_risk_count += 1
                at_risk_list.append(
                    {
                        "etudiant": ins.id_etudiant,
                        "cours": cours,
                        "total_abs": total_abs,
                        "rate": round(rate, 1),
                        "inscription_id": ins.id_inscription,
                        "is_exempted": ins.exemption_40,
                        "status_label": "BLOQUÉ",
                        "status_color": "danger",
                    }
                )
            elif ins.exemption_40 and rate >= seuil:
                # L'étudiant dépasse le seuil de base mais est protégé par son
                # exemption — l'afficher dans une couleur différente pour visibilité.
                at_risk_list.append(
                    {
                        "etudiant": ins.id_etudiant,
                        "cours": cours,
                        "total_abs": total_abs,
                        "rate": round(rate, 1),
                        "inscription_id": ins.id_inscription,
                        "is_exempted": True,
                        "status_label": "SOUS EXEMPTION",
                        "status_color": "info",
                    }
                )

    return render(
        request,
        "dashboard/instructor_index.html",
        {
            "academic_year": academic_year,
            "active_courses_count": active_courses_count,
            "sessions_given": sessions_given,
            "upcoming_sessions": upcoming_sessions,
            "total_absences": total_absences,
            "at_risk_count": at_risk_count,
            # Limiter à 5 entrées dans la carte du tableau de bord pour rester concis.
            "at_risk_list": at_risk_list[:5],
        },
    )
