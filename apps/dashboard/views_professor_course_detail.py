"""
Vue de détail d'un cours côté professeur pour le système UniAbsences.

Ce module implémente la page de détail d'un cours, organisée en onglets,
affichée au professeur lorsqu'il clique sur l'un de ses cours assignés. Elle
est en lecture seule pour toutes les données étudiantes — aucune opération
administrative n'est permise ici.

Onglets
-------
Étudiants
    Étudiants inscrits pour l'année académique active, chacun annoté avec :
    - Total des heures d'absence non justifiées et taux d'absence calculé.
    - Seuil effectif (``seuil_effectif``), tenant compte des marges
      d'exemption par étudiant.
    - Indicateurs de blocage / exemption / à-risque.
    - Niveau de risque prédictif (HIGH / MEDIUM / LOW / NONE), taux projeté,
      taux récent et jours restants dans l'année académique (issus de
      ``predict_absence_risk``).

Séances
    Séances historiques du cours, classées de la plus récente à la plus
    ancienne. Chaque séance est annotée avec son jeton QR de présence actif
    (le cas échéant). La vue identifie également le premier jeton QR actif
    et la première séance non validée à saisie manuelle pour aujourd'hui.

Statistiques
    Chiffres agrégés : total des étudiants inscrits, nombre à risque, total
    d'événements d'absence, et taux moyen d'absence pour l'ensemble de la classe.

Sécurité
--------
L'accès est restreint au rôle professeur via ``@professor_required``.
La vue applique le contrôle de propriété : un professeur ne peut consulter
les pages de détail que pour les cours qui lui sont assignés
(``course.professeur_id == request.user.pk``).

Fait partie du système de tableau de bord UniAbsences.
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET

from apps.absences.models import Absence, QRAttendanceToken
from apps.absences.services import get_system_threshold, predict_absence_risk
from apps.academic_sessions.models import AnneeAcademique, Seance
from apps.academics.models import Cours
from apps.dashboard.decorators import professor_required
from apps.enrollments.models import Inscription


@login_required
@professor_required
@require_GET
def instructor_course_detail(request, course_id):
    """
    Rend la page de détail à onglets pour un cours unique assigné au professeur.

    L'onglet actif est sélectionné par le paramètre de requête ``?tab=`` et vaut
    ``students`` par défaut. Les données des trois onglets sont calculées en une
    seule requête pour éviter des allers-retours supplémentaires lorsque
    l'utilisateur change d'onglet.

    Vérification de propriété : redirige vers le tableau de bord professeur avec
    un message d'erreur si le professeur authentifié n'a pas créé / n'est pas
    assigné au cours demandé.

    Parameters
    ----------
    request : HttpRequest
        Doit être une requête GET émise par un professeur authentifié.
    course_id : int
        Clé primaire de l'instance ``Cours`` à afficher.

    Returns
    -------
    HttpResponse
        Rend ``dashboard/instructor_course_detail.html`` avec le contexte
        décrit ci-dessous.

    Context keys
    ------------
    course : Cours
        L'objet cours.
    academic_year : AnneeAcademique or None
        L'année académique active (ou la plus récente si aucune n'est active).
    active_tab : str
        L'une de ``"students"``, ``"sessions"`` ou ``"statistics"``.
    students_data : list[dict]
        Dictionnaires par étudiant avec les clés : inscription, etudiant,
        total_abs, rate, is_at_risk, is_blocked, is_exempted,
        is_under_exemption, seuil_effectif, risk_level, projected_rate,
        recent_rate, course_avg_rate, days_remaining, trend.
    sessions : list[Seance]
        Séances du cours ; chaque séance possède un attribut ``active_qr_token``
        injecté à l'exécution.
    total_students, at_risk_students, total_absences_all, overall_rate : int/float
        Statistiques agrégées pour l'onglet Statistiques.
    early_warnings_count : int
        Étudiants dont le risque prédictif est HIGH ou MEDIUM mais qui ne sont
        pas encore au-delà du seuil — utile pour la surveillance proactive.
    course_threshold : float
        Le seuil d'absence applicable à ce cours.
    course_active_qr : QRAttendanceToken or None
        Le premier jeton QR actif trouvé parmi les séances du cours aujourd'hui.
    course_active_manual : Seance or None
        La première séance non validée et sans QR programmée pour aujourd'hui,
        indiquant qu'une saisie manuelle de présence peut être nécessaire.
    """
    course = get_object_or_404(Cours, id_cours=course_id)

    # Garde de propriété : les professeurs ne peuvent voir que leurs propres cours.
    if course.professeur_id != request.user.pk:
        messages.error(request, "Accès non autorisé à ce cours.")
        return redirect("dashboard:instructor_dashboard")

    academic_year = AnneeAcademique.objects.filter(active=True).first()
    if not academic_year:
        academic_year = AnneeAcademique.objects.order_by("-id_annee").first()

    # Déterminer l'onglet à rendre ; par défaut la liste des étudiants.
    active_tab = request.GET.get("tab", "students")

    # ── Onglet : Étudiants ────────────────────────────────────────────────────

    if academic_year:
        inscriptions = Inscription.objects.filter(
            id_cours=course, id_annee=academic_year, status=Inscription.Status.EN_COURS
        ).select_related("id_etudiant", "id_cours")
    else:
        # Repli quand aucune année académique n'est configurée : afficher toutes les inscriptions actives.
        inscriptions = Inscription.objects.filter(
            id_cours=course, status=Inscription.Status.EN_COURS
        ).select_related("id_etudiant", "id_cours")

    inscriptions = list(inscriptions)
    inscription_ids = [ins.id_inscription for ins in inscriptions]
    today = timezone.localdate()

    # Agréger les heures d'absence non justifiées par inscription en une seule requête BD.
    # Seules les séances passées (date <= today) sont comptées.
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

    system_threshold = get_system_threshold()
    # Utiliser l'override par cours s'il est défini ; sinon, retomber sur la valeur système par défaut.
    course_threshold = (
        course.seuil_absence if course.seuil_absence is not None else system_threshold
    )

    students_data = []
    for ins in inscriptions:
        total_abs = float(absence_sums.get(ins.id_inscription, 0) or 0)
        rate = (
            (total_abs / course.nombre_total_periodes) * 100
            if course.nombre_total_periodes > 0
            else 0.0
        )
        # Le seuil effectif est rehaussé de la exemption_margin pour les étudiants
        # qui détiennent une exemption (exemption_40), plafonné à 100 %.
        seuil_effectif = min(course_threshold + ins.exemption_margin, 100) if ins.exemption_40 else course_threshold
        is_at_risk = rate >= course_threshold
        is_blocked = rate >= seuil_effectif
        # Un étudiant est « sous exemption » lorsqu'il dépasse le seuil de base
        # mais que le bouclier d'exemption le maintient sous le seuil effectif de blocage.
        is_under_exemption = ins.exemption_40 and is_at_risk and not is_blocked

        students_data.append(
            {
                "inscription": ins,
                "etudiant": ins.id_etudiant,
                "total_abs": total_abs,
                "rate": round(rate, 1),
                "is_at_risk": is_at_risk,
                "is_blocked": is_blocked,
                "is_exempted": ins.exemption_40,
                "is_under_exemption": is_under_exemption,
                "seuil_effectif": seuil_effectif,
            }
        )

    # Exécuter le modèle de risque prédictif pour tous les étudiants inscrits en un seul appel.
    predictions = predict_absence_risk(
        inscriptions, academic_year=academic_year, system_threshold=system_threshold
    )
    # Indexer les prédictions par PK d'inscription pour une recherche O(1) dans la boucle ci-dessous.
    predictions_by_id = {p["inscription"].id_inscription: p for p in predictions}
    early_warnings_count = 0
    for sd in students_data:
        pred = predictions_by_id.get(sd["inscription"].id_inscription)
        if pred:
            sd["risk_level"] = pred["risk_level"]
            sd["projected_rate"] = pred["projected_rate"]
            sd["recent_rate"] = pred["recent_rate"]
            sd["course_avg_rate"] = pred["course_avg_rate"]
            sd["days_remaining"] = pred["days_remaining"]
            sd["trend"] = pred["trend"]
            # Compter les étudiants à risque HIGH ou MEDIUM qui n'ont pas encore
            # franchi le seuil — ce sont des candidats à une intervention précoce.
            if pred["risk_level"] in ("HIGH", "MEDIUM") and not sd["is_at_risk"]:
                early_warnings_count += 1
        else:
            # Aucune prédiction disponible (p. ex., pas encore de séances) : utiliser des valeurs par défaut sûres.
            sd["risk_level"] = "NONE"
            sd["projected_rate"] = sd["rate"]
            sd["recent_rate"] = 0
            sd["course_avg_rate"] = 0
            sd["days_remaining"] = 0
            sd["trend"] = "stable"

    # ── Onglet : Séances ──────────────────────────────────────────────────────

    if academic_year:
        sessions = Seance.objects.filter(
            id_cours=course, id_annee=academic_year
        ).order_by("-date_seance", "-heure_debut")
    else:
        sessions = Seance.objects.filter(id_cours=course).order_by(
            "-date_seance", "-heure_debut"
        )

    sessions = list(sessions)
    seance_ids = [s.id_seance for s in sessions]

    # Récupérer tous les jetons QR actifs et non expirés pour ces séances en une seule requête.
    active_tokens_by_seance = {}
    if seance_ids:
        active_tokens_by_seance = {
            t.seance_id: t
            for t in QRAttendanceToken.objects.filter(
                seance_id__in=seance_ids,
                is_active=True,
                expires_at__gt=timezone.now(),
            ).order_by("seance_id", "-created_at")
            # order_by garantit que le jeton créé le plus récemment l'emporte
            # lorsque plusieurs jetons existent pour la même séance (le dict conserve la dernière valeur).
        }

    # Annoter chaque séance avec son jeton QR actif et identifier le premier
    # jeton QR actif ainsi que le premier candidat à la saisie manuelle pour aujourd'hui.
    course_active_qr = None
    course_active_manual = None
    today_local = timezone.localdate()
    for s in sessions:
        s.active_qr_token = active_tokens_by_seance.get(s.id_seance)
        # Suivre le premier jeton QR actif parmi toutes les séances.
        if s.active_qr_token and not course_active_qr:
            course_active_qr = s.active_qr_token
        # Une séance est éligible à la saisie manuelle lorsqu'elle n'a pas de jeton QR,
        # est non validée et est programmée pour aujourd'hui.
        if (
            course_active_manual is None
            and s.active_qr_token is None
            and not s.validated
            and s.date_seance == today_local
        ):
            course_active_manual = s

    # ── Onglet : Statistiques ─────────────────────────────────────────────────

    total_students = len(students_data)
    at_risk_students = sum(1 for s in students_data if s["is_at_risk"])

    # Compter tous les événements d'absence du cours (tous statuts, pas seulement NON_JUSTIFIEE).
    total_absences_all = Absence.objects.filter(id_seance__id_cours=course)
    if academic_year:
        total_absences_all = total_absences_all.filter(id_seance__id_annee=academic_year)
    total_absences_all = total_absences_all.count()

    # Taux d'absence moyen pour l'ensemble de la classe (moyenne sur tous les étudiants inscrits).
    overall_rate = (
        sum(s["rate"] for s in students_data) / total_students
        if total_students > 0
        else 0
    )

    return render(
        request,
        "dashboard/instructor_course_detail.html",
        {
            "course": course,
            "academic_year": academic_year,
            "active_tab": active_tab,
            "students_data": students_data,
            "sessions": sessions,
            "total_students": total_students,
            "at_risk_students": at_risk_students,
            "total_absences_all": total_absences_all,
            "overall_rate": round(overall_rate, 1),
            "early_warnings_count": early_warnings_count,
            "course_threshold": course_threshold,
            "course_active_qr": course_active_qr,
            "course_active_manual": course_active_manual,
        },
    )
