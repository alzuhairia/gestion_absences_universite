"""
Détail d'un cours pour le professeur.

Fonctionnalités :
  - Onglet Étudiants : liste avec taux d'absence et alertes prédictives
  - Onglet Séances   : historique + token QR actif par séance
  - Onglet Statistiques : taux moyen, nombre à risque

STRICT : lecture seule pour les données étudiants.
SÉCURITÉ : vérification course.professeur == request.user
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Sum
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
    Page de détails du cours pour le professeur.
    STRICT : Aucune action administrative permise.
    """
    course = get_object_or_404(Cours, id_cours=course_id)
    if course.professeur_id != request.user.pk:
        messages.error(request, "Accès non autorisé à ce cours.")
        return redirect("dashboard:instructor_dashboard")

    academic_year = AnneeAcademique.objects.filter(active=True).first()
    if not academic_year:
        academic_year = AnneeAcademique.objects.order_by("-id_annee").first()

    active_tab = request.GET.get("tab", "students")

    # ── Onglet Étudiants ──────────────────────────────────────────────────────

    if academic_year:
        inscriptions = Inscription.objects.filter(
            id_cours=course, id_annee=academic_year, status=Inscription.Status.EN_COURS
        ).select_related("id_etudiant", "id_cours")
    else:
        inscriptions = Inscription.objects.filter(
            id_cours=course, status=Inscription.Status.EN_COURS
        ).select_related("id_etudiant", "id_cours")

    inscriptions = list(inscriptions)
    inscription_ids = [ins.id_inscription for ins in inscriptions]
    today = timezone.localdate()
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
        seuil_effectif = min(course_threshold + ins.exemption_margin, 100) if ins.exemption_40 else course_threshold
        is_at_risk = rate >= course_threshold
        is_blocked = rate >= seuil_effectif
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

    # Prédictions de risque d'absence
    predictions = predict_absence_risk(
        inscriptions, academic_year=academic_year, system_threshold=system_threshold
    )
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
            if pred["risk_level"] in ("HIGH", "MEDIUM") and not sd["is_at_risk"]:
                early_warnings_count += 1
        else:
            sd["risk_level"] = "NONE"
            sd["projected_rate"] = sd["rate"]
            sd["recent_rate"] = 0
            sd["course_avg_rate"] = 0
            sd["days_remaining"] = 0
            sd["trend"] = "stable"

    # ── Onglet Séances ────────────────────────────────────────────────────────

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
    active_tokens_by_seance = {}
    if seance_ids:
        active_tokens_by_seance = {
            t.seance_id: t
            for t in QRAttendanceToken.objects.filter(
                seance_id__in=seance_ids,
                is_active=True,
                expires_at__gt=timezone.now(),
            ).order_by("seance_id", "-created_at")
        }

    course_active_qr = None
    course_active_manual = None
    today_local = timezone.localdate()
    for s in sessions:
        s.active_qr_token = active_tokens_by_seance.get(s.id_seance)
        if s.active_qr_token and not course_active_qr:
            course_active_qr = s.active_qr_token
        if (
            course_active_manual is None
            and s.active_qr_token is None
            and not s.validated
            and s.date_seance == today_local
        ):
            course_active_manual = s

    # ── Onglet Statistiques ───────────────────────────────────────────────────

    total_students = len(students_data)
    at_risk_students = sum(1 for s in students_data if s["is_at_risk"])
    total_absences_all = Absence.objects.filter(id_seance__id_cours=course)
    if academic_year:
        total_absences_all = total_absences_all.filter(id_seance__id_annee=academic_year)
    total_absences_all = total_absences_all.count()

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
