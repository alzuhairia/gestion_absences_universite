"""
Constructeurs d'emails de notification UniAbsences.

Chaque fonction retourne un tuple (subject, body, html_body) prêt
à être passé à send_notification_email() ou send_with_dedup().

Types d'emails :
  - Seuil d'absence dépassé (étudiant + professeur)
  - Éligibilité restaurée (étudiant)
  - Justificatif soumis (professeur)
  - Décision de justificatif (étudiant + professeur)
  - Absence enregistrée (étudiant)
  - Résumé hebdomadaire (secrétariat)
"""

from .email_core import _render_html


def build_threshold_exceeded_email(student, course_name, taux, seuil):
    """Email sent to student when absence threshold is exceeded."""
    subject = f"[UniAbsences] ALERTE — Seuil d'absence dépassé pour {course_name}"
    context = {
        "student_name": student.get_full_name(),
        "course_name": course_name,
        "taux": f"{taux:.1f}",
        "seuil": seuil,
    }
    body = (
        f"Bonjour {context['student_name']},\n\n"
        f"Votre taux d'absence pour le cours « {course_name} » "
        f"a atteint {context['taux']}%, dépassant le seuil autorisé de {seuil}%.\n\n"
        f"Votre accès à l'examen pour ce cours est désormais bloqué.\n\n"
        f"Si vous pensez qu'il s'agit d'une erreur, veuillez contacter le secrétariat.\n\n"
        f"— UniAbsences Notification System"
    )
    html_body = _render_html("emails/threshold_exceeded.html", context)
    return subject, body, html_body


def build_threshold_exceeded_professor_email(professor, student, course_name, taux, seuil):
    """Email sent to professor when a student in their course exceeds the threshold."""
    subject = f"[UniAbsences] Étudiant bloqué — {student.get_full_name()} ({course_name})"
    context = {
        "professor_name": professor.get_full_name(),
        "student_name": student.get_full_name(),
        "student_email": student.email,
        "course_name": course_name,
        "taux": f"{taux:.1f}",
        "seuil": seuil,
    }
    body = (
        f"Bonjour {context['professor_name']},\n\n"
        f"L'étudiant {context['student_name']} ({student.email}) a dépassé le seuil "
        f"d'absence pour votre cours « {course_name} ».\n\n"
        f"Taux actuel : {context['taux']}% (seuil : {seuil}%)\n"
        f"L'accès à l'examen a été automatiquement bloqué.\n\n"
        f"— UniAbsences Notification System"
    )
    html_body = _render_html("emails/threshold_exceeded_professor.html", context)
    return subject, body, html_body


def build_eligibility_restored_email(student, course_name):
    """Email sent to student when eligibility is restored."""
    subject = f"[UniAbsences] Éligibilité restaurée — {course_name}"
    context = {
        "student_name": student.get_full_name(),
        "course_name": course_name,
    }
    body = (
        f"Bonjour {context['student_name']},\n\n"
        f"Vous êtes à nouveau éligible à l'examen pour le cours « {course_name} ».\n\n"
        f"— UniAbsences Notification System"
    )
    html_body = _render_html("emails/eligibility_restored.html", context)
    return subject, body, html_body


def build_justification_submitted_professor_email(professor, student, course_code, absence_date):
    """Email sent to professor when a student submits a justification."""
    subject = f"[UniAbsences] Justificatif soumis — {student.get_full_name()} ({course_code})"
    context = {
        "professor_name": professor.get_full_name(),
        "student_name": student.get_full_name(),
        "student_email": student.email,
        "course_code": course_code,
        "absence_date": absence_date,
    }
    body = (
        f"Bonjour {context['professor_name']},\n\n"
        f"L'étudiant {context['student_name']} ({student.email}) a soumis un justificatif "
        f"pour son absence du {absence_date} dans votre cours {course_code}.\n\n"
        f"Le secrétariat procédera à la validation.\n\n"
        f"— UniAbsences Notification System"
    )
    html_body = _render_html("emails/justification_submitted.html", context)
    return subject, body, html_body


def build_justification_decision_email(student, course_code, absence_date, approved, motif=""):
    """Email sent to student when justification is approved or rejected."""
    decision = "ACCEPTÉE" if approved else "REFUSÉE"
    subject = f"[UniAbsences] Justification {decision} — {course_code} ({absence_date})"
    context = {
        "student_name": student.get_full_name(),
        "course_code": course_code,
        "absence_date": absence_date,
        "approved": approved,
        "decision": decision,
        "motif": motif,
    }
    body = (
        f"Bonjour {context['student_name']},\n\n"
        f"Votre justification pour l'absence du {absence_date} "
        f"dans le cours {course_code} a été {decision}.\n"
    )
    if not approved and motif:
        body += f"\nMotif : {motif}\n"
    body += f"\n— UniAbsences Notification System"
    html_body = _render_html("emails/justification_decision.html", context)
    return subject, body, html_body


def build_justification_decision_professor_email(professor, student, course_code, absence_date, approved):
    """Email sent to professor when a justification in their course is decided."""
    decision = "acceptée" if approved else "refusée"
    subject = f"[UniAbsences] Justification {decision} — {student.get_full_name()} ({course_code})"
    context = {
        "professor_name": professor.get_full_name(),
        "student_name": student.get_full_name(),
        "course_code": course_code,
        "absence_date": absence_date,
        "approved": approved,
        "decision": decision,
    }
    body = (
        f"Bonjour {context['professor_name']},\n\n"
        f"La justification de {context['student_name']} pour l'absence du {absence_date} "
        f"dans votre cours {course_code} a été {decision} par le secrétariat.\n\n"
        f"— UniAbsences Notification System"
    )
    html_body = _render_html("emails/justification_decision_professor.html", context)
    return subject, body, html_body


def build_absence_recorded_email(student, course_name, absence_date, taux):
    """Email sent to student when a professor records an absence."""
    subject = f"[UniAbsences] Absence enregistrée — {course_name} ({absence_date})"
    context = {
        "student_name": student.get_full_name(),
        "course_name": course_name,
        "absence_date": absence_date,
        "taux": f"{taux:.1f}",
    }
    body = (
        f"Bonjour {context['student_name']},\n\n"
        f"Une absence a été enregistrée pour le cours « {course_name} » "
        f"le {absence_date}.\n\n"
        f"Votre taux d'absence actuel est de {context['taux']}%.\n\n"
        f"Si vous pensez qu'il s'agit d'une erreur, veuillez contacter votre professeur "
        f"ou soumettre un justificatif.\n\n"
        f"— UniAbsences Notification System"
    )
    html_body = _render_html("emails/absence_recorded.html", context)
    return subject, body, html_body


def build_weekly_summary_email(secretary, summary_data):
    """
    Email sent to secretaries with weekly absence statistics.

    Args:
        secretary: User instance (secretary)
        summary_data: dict with keys:
            - week_start, week_end: date strings
            - total_absences: int
            - new_blocked: int
            - pending_justifications: int
            - courses_at_risk: list of {course_name, at_risk_count}
    """
    subject = (
        f"[UniAbsences] Résumé hebdomadaire des absences "
        f"({summary_data['week_start']} — {summary_data['week_end']})"
    )
    context = {
        "secretary_name": secretary.get_full_name(),
        **summary_data,
    }
    body = (
        f"Bonjour {context['secretary_name']},\n\n"
        f"Voici le résumé hebdomadaire des absences "
        f"({summary_data['week_start']} — {summary_data['week_end']}) :\n\n"
        f"  • Absences enregistrées : {summary_data['total_absences']}\n"
        f"  • Nouveaux blocages : {summary_data['new_blocked']}\n"
        f"  • Justificatifs en attente : {summary_data['pending_justifications']}\n\n"
    )
    if summary_data.get("courses_at_risk"):
        body += "Cours avec étudiants à risque :\n"
        for c in summary_data["courses_at_risk"]:
            body += f"  • {c['course_name']} : {c['at_risk_count']} étudiant(s)\n"
    body += f"\n— UniAbsences Notification System"
    html_body = _render_html("emails/weekly_summary.html", context)
    return subject, body, html_body
