import datetime
import io

from django.db import transaction
from django.db.models import Count, F, Q, Sum
from django.db.models.functions import TruncMonth
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema, extend_schema_view
from openpyxl import Workbook
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.absences.models import Absence, Justification
from apps.absences.services import get_system_threshold
from apps.notifications.email import (
    build_justification_decision_email,
    build_justification_decision_professor_email,
    build_justification_submitted_professor_email,
    send_notification_email,
)
from apps.academic_sessions.models import AnneeAcademique
from apps.academics.models import Cours
from apps.accounts.models import User
from apps.audits.models import LogAudit
from apps.enrollments.models import Inscription
from apps.notifications.models import Notification

from .filters import (
    AbsenceFilter,
    CoursFilter,
    InscriptionFilter,
    JustificationFilter,
    StudentFilter,
)
from .pagination import StandardPagination
from .permissions import (
    IsAdmin,
    IsAdminOrSecretary,
    IsAdminOrSecretaryOrProfessor,
    IsStudent,
)
from .serializers import (
    AbsenceListSerializer,
    AbsenceWriteSerializer,
    CoursDetailSerializer,
    CoursListSerializer,
    CoursWriteSerializer,
    DashboardAnalyticsSerializer,
    InscriptionListSerializer,
    InscriptionWriteSerializer,
    JustificationCreateSerializer,
    JustificationListSerializer,
    JustificationProcessSerializer,
    NotificationSerializer,
    StatisticsAnalyticsSerializer,
    StudentSerializer,
    UserListSerializer,
)


# ── Students ──────────────────────────────────────────────────────────────────


@extend_schema_view(
    list=extend_schema(summary="List students", tags=["Students"]),
    retrieve=extend_schema(summary="Get student detail", tags=["Students"]),
    create=extend_schema(summary="Create student", tags=["Students"]),
    update=extend_schema(summary="Update student", tags=["Students"]),
    partial_update=extend_schema(summary="Partial update student", tags=["Students"]),
    destroy=extend_schema(summary="Deactivate student (soft delete)", tags=["Students"]),
)
class StudentViewSet(viewsets.ModelViewSet):
    """
    CRUD for student users.

    - Admin/Secretary: full access
    - Professor: list/retrieve only (students in their courses)
    - Student: retrieve own profile only
    """

    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_class = StudentFilter
    search_fields = ["nom", "prenom", "email"]
    ordering_fields = ["nom", "prenom", "email", "niveau", "date_creation"]
    ordering = ["nom", "prenom"]

    def get_permissions(self):
        if self.action in ("create", "update", "partial_update", "destroy"):
            return [IsAdminOrSecretary()]
        return [IsAuthenticated()]

    def get_serializer_class(self):
        if self.action == "list":
            return UserListSerializer
        return StudentSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return User.objects.none()
        qs = User.objects.filter(role=User.Role.ETUDIANT)
        user = self.request.user

        if user.role == User.Role.ETUDIANT:
            return qs.filter(pk=user.pk)
        if user.role == User.Role.PROFESSEUR:
            student_ids = Inscription.objects.filter(
                id_cours__professeur=user
            ).values_list("id_etudiant", flat=True)
            return qs.filter(pk__in=student_ids)
        return qs

    def perform_create(self, serializer):
        user = serializer.save(role=User.Role.ETUDIANT)
        user.set_password(User.objects.make_random_password())
        user.must_change_password = True
        user.save(update_fields=["password", "must_change_password"])

    def perform_destroy(self, instance):
        instance.actif = False
        instance.save(update_fields=["actif"])


# ── Courses ───────────────────────────────────────────────────────────────────


@extend_schema_view(
    list=extend_schema(summary="List courses", tags=["Courses"]),
    retrieve=extend_schema(summary="Get course detail (with sessions & prerequisites)", tags=["Courses"]),
    create=extend_schema(summary="Create course", tags=["Courses"]),
    update=extend_schema(summary="Update course", tags=["Courses"]),
    partial_update=extend_schema(summary="Partial update course", tags=["Courses"]),
    destroy=extend_schema(summary="Delete course", tags=["Courses"]),
)
class CoursViewSet(viewsets.ModelViewSet):
    """
    CRUD for courses.

    - Admin/Secretary: full access
    - Professor: list/detail on own courses
    - Student: list/retrieve enrolled courses only
    """

    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_class = CoursFilter
    search_fields = ["code_cours", "nom_cours"]
    ordering_fields = ["code_cours", "nom_cours", "niveau"]
    ordering = ["code_cours"]

    def get_permissions(self):
        if self.action in ("create", "update", "partial_update", "destroy"):
            return [IsAdminOrSecretary()]
        return [IsAuthenticated()]

    def get_serializer_class(self):
        if self.action == "retrieve":
            return CoursDetailSerializer
        if self.action in ("create", "update", "partial_update"):
            return CoursWriteSerializer
        return CoursListSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Cours.objects.none()
        qs = Cours.objects.select_related(
            "id_departement", "professeur", "id_annee"
        )
        if self.action == "retrieve":
            qs = qs.prefetch_related("seances", "prerequisites")
        user = self.request.user

        if user.role == User.Role.ETUDIANT:
            enrolled_course_ids = Inscription.objects.filter(
                id_etudiant=user
            ).values_list("id_cours", flat=True)
            return qs.filter(pk__in=enrolled_course_ids)
        if user.role == User.Role.PROFESSEUR:
            return qs.filter(professeur=user)
        return qs


# ── Enrollments ───────────────────────────────────────────────────────────────


@extend_schema_view(
    list=extend_schema(summary="List enrollments", tags=["Enrollments"]),
    retrieve=extend_schema(summary="Get enrollment detail", tags=["Enrollments"]),
    create=extend_schema(summary="Create enrollment", tags=["Enrollments"]),
    update=extend_schema(summary="Update enrollment", tags=["Enrollments"]),
    partial_update=extend_schema(summary="Partial update enrollment", tags=["Enrollments"]),
    destroy=extend_schema(summary="Delete enrollment", tags=["Enrollments"]),
)
class InscriptionViewSet(viewsets.ModelViewSet):
    """
    CRUD for enrollments.

    - Admin/Secretary: full access
    - Professor: read-only for their courses
    - Student: read-only for own enrollments
    """

    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_class = InscriptionFilter
    search_fields = [
        "id_etudiant__nom",
        "id_etudiant__prenom",
        "id_cours__code_cours",
    ]
    ordering_fields = ["id_inscription", "status", "type_inscription"]
    ordering = ["-id_inscription"]

    def get_permissions(self):
        if self.action in ("create", "update", "partial_update", "destroy"):
            return [IsAdminOrSecretary()]
        return [IsAuthenticated()]

    def get_serializer_class(self):
        if self.action in ("create", "update", "partial_update"):
            return InscriptionWriteSerializer
        return InscriptionListSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Inscription.objects.none()
        qs = Inscription.objects.select_related(
            "id_etudiant", "id_cours", "id_annee"
        )
        user = self.request.user

        if user.role == User.Role.ETUDIANT:
            return qs.filter(id_etudiant=user)
        if user.role == User.Role.PROFESSEUR:
            return qs.filter(id_cours__professeur=user)
        return qs


# ── Absences ──────────────────────────────────────────────────────────────────


@extend_schema_view(
    list=extend_schema(summary="List absences", tags=["Absences"]),
    retrieve=extend_schema(summary="Get absence detail", tags=["Absences"]),
    create=extend_schema(summary="Record an absence", tags=["Absences"]),
    update=extend_schema(summary="Update absence", tags=["Absences"]),
    partial_update=extend_schema(summary="Partial update absence", tags=["Absences"]),
    destroy=extend_schema(summary="Delete absence", tags=["Absences"]),
)
class AbsenceViewSet(viewsets.ModelViewSet):
    """
    CRUD for absences.

    - Admin/Secretary: full access
    - Professor: create/update/list for their courses
    - Student: read-only for own absences
    """

    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_class = AbsenceFilter
    search_fields = [
        "id_inscription__id_etudiant__nom",
        "id_inscription__id_etudiant__prenom",
    ]
    ordering_fields = ["id_absence", "duree_absence", "statut"]
    ordering = ["-id_absence"]

    def get_permissions(self):
        if self.action in ("create", "update", "partial_update"):
            return [IsAdminOrSecretaryOrProfessor()]
        if self.action == "destroy":
            return [IsAdminOrSecretary()]
        return [IsAuthenticated()]

    def get_serializer_class(self):
        if self.action in ("create", "update", "partial_update"):
            return AbsenceWriteSerializer
        return AbsenceListSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Absence.objects.none()
        qs = Absence.objects.select_related(
            "id_inscription__id_etudiant",
            "id_inscription__id_cours",
            "id_seance",
        )
        user = self.request.user

        if user.role == User.Role.ETUDIANT:
            return qs.filter(id_inscription__id_etudiant=user)
        if user.role == User.Role.PROFESSEUR:
            return qs.filter(id_inscription__id_cours__professeur=user)
        return qs

    def perform_create(self, serializer):
        serializer.save(
            encodee_par=self.request.user,
            statut=Absence.Statut.NON_JUSTIFIEE,
        )


# ── Justifications ────────────────────────────────────────────────────────────


@extend_schema_view(
    list=extend_schema(summary="List justifications", tags=["Justifications"]),
    retrieve=extend_schema(summary="Get justification detail", tags=["Justifications"]),
    create=extend_schema(summary="Submit a justification (student only)", tags=["Justifications"]),
)
class JustificationViewSet(
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.ListModelMixin,
    viewsets.GenericViewSet,
):
    """
    Justification management.

    - Student: create justifications for own absences, list own
    - Admin/Secretary: list all, approve/reject via process action
    - Professor: read-only for their courses
    """

    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_class = JustificationFilter
    ordering_fields = ["date_soumission", "state"]
    ordering = ["-date_soumission"]

    def get_permissions(self):
        if self.action == "create":
            return [IsStudent()]
        if self.action == "process":
            return [IsAdminOrSecretary()]
        return [IsAuthenticated()]

    def get_serializer_class(self):
        if self.action == "create":
            return JustificationCreateSerializer
        if self.action == "process":
            return JustificationProcessSerializer
        return JustificationListSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Justification.objects.none()
        qs = Justification.objects.select_related(
            "id_absence__id_inscription__id_etudiant",
            "id_absence__id_inscription__id_cours",
            "validee_par",
        )
        user = self.request.user

        if user.role == User.Role.ETUDIANT:
            return qs.filter(
                id_absence__id_inscription__id_etudiant=user
            )
        if user.role == User.Role.PROFESSEUR:
            return qs.filter(
                id_absence__id_inscription__id_cours__professeur=user
            )
        return qs

    def perform_create(self, serializer):
        with transaction.atomic():
            justification = serializer.save()
            absence = justification.id_absence
            absence.statut = Absence.Statut.EN_ATTENTE
            absence.save(update_fields=["statut"])

        # Email to professor (outside transaction)
        professor = absence.id_seance.id_cours.professeur
        if professor:
            subj, body, html_body = build_justification_submitted_professor_email(
                professor,
                self.request.user,
                absence.id_seance.id_cours.code_cours,
                str(absence.id_seance.date_seance),
            )
            send_notification_email(professor, subj, body, html_body=html_body)

    @extend_schema(
        summary="Approve or reject a justification",
        tags=["Justifications"],
        request=JustificationProcessSerializer,
        responses=JustificationListSerializer,
    )
    @action(detail=True, methods=["post"], url_path="process")
    def process(self, request, pk=None):
        """Approve or reject a justification."""
        serializer = JustificationProcessSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        action_value = serializer.validated_data["action"]
        comment = serializer.validated_data.get("commentaire_gestion", "")

        with transaction.atomic():
            justification = Justification.objects.select_for_update().get(
                pk=self.get_object().pk
            )

            if justification.state != Justification.State.EN_ATTENTE:
                return Response(
                    {"detail": "This justification has already been processed."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            if action_value == "approve":
                justification.state = Justification.State.ACCEPTEE
                justification.id_absence.statut = Absence.Statut.JUSTIFIEE
            else:
                justification.state = Justification.State.REFUSEE
                justification.id_absence.statut = Absence.Statut.NON_JUSTIFIEE

            justification.validee_par = request.user
            justification.date_validation = timezone.now()
            justification.commentaire_gestion = comment
            justification.save()
            justification.id_absence.save(update_fields=["statut"])

        # Emails to student + professor (outside transaction)
        absence = justification.id_absence
        student = absence.id_inscription.id_etudiant
        course_code = absence.id_seance.id_cours.code_cours
        date_str = str(absence.id_seance.date_seance)
        approved = action_value == "approve"

        subj, body, html_body = build_justification_decision_email(
            student, course_code, date_str, approved, comment
        )
        send_notification_email(student, subj, body, html_body=html_body)

        professor = absence.id_seance.id_cours.professeur
        if professor:
            subj, body, html_body = build_justification_decision_professor_email(
                professor, student, course_code, date_str, approved
            )
            send_notification_email(professor, subj, body, html_body=html_body)

        return Response(
            JustificationListSerializer(justification).data,
            status=status.HTTP_200_OK,
        )


# ══════════════════════════════════════════════════════════════════════════════
# Feature 1: Notifications API
# ══════════════════════════════════════════════════════════════════════════════


@extend_schema_view(
    list=extend_schema(summary="List my notifications", tags=["Notifications"]),
    mark_read=extend_schema(summary="Mark notification as read", tags=["Notifications"]),
    mark_all_read=extend_schema(summary="Mark all notifications as read", tags=["Notifications"]),
)
class NotificationViewSet(viewsets.GenericViewSet, mixins.ListModelMixin):
    """User notifications (auto-generated by the system)."""

    serializer_class = NotificationSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = StandardPagination

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Notification.objects.none()
        return Notification.objects.filter(
            id_utilisateur=self.request.user
        ).order_by("-date_envoi")

    @action(detail=True, methods=["post"])
    def mark_read(self, request, pk=None):
        notif = get_object_or_404(
            Notification, pk=pk, id_utilisateur=request.user
        )
        notif.lue = True
        notif.save(update_fields=["lue"])
        return Response({"status": "read"})

    @action(detail=False, methods=["post"])
    def mark_all_read(self, request):
        count = Notification.objects.filter(
            id_utilisateur=request.user, lue=False
        ).update(lue=True)
        return Response({"marked_read": count})


# ══════════════════════════════════════════════════════════════════════════════
# Feature 2: Dashboard Analytics API
# ══════════════════════════════════════════════════════════════════════════════


@extend_schema(
    summary="Dashboard KPIs (admin only)",
    tags=["Analytics"],
    responses=DashboardAnalyticsSerializer,
)
@api_view(["GET"])
@permission_classes([IsAdmin])
def dashboard_analytics(request):
    """Admin dashboard KPIs as JSON."""
    academic_year = AnneeAcademique.objects.filter(active=True).first()

    total_students = User.objects.filter(
        role=User.Role.ETUDIANT, actif=True
    ).count()
    total_professors = User.objects.filter(
        role=User.Role.PROFESSEUR, actif=True
    ).count()
    total_secretaries = User.objects.filter(
        role=User.Role.SECRETAIRE, actif=True
    ).count()
    active_courses = Cours.objects.filter(actif=True).count()

    year_filter = Q(id_annee=academic_year) if academic_year else Q()

    total_inscriptions = Inscription.objects.filter(year_filter).count()
    total_absences = Absence.objects.filter(
        Q(id_inscription__id_annee=academic_year) if academic_year else Q()
    ).count()

    # Students at risk
    system_threshold = get_system_threshold()
    all_inscriptions = Inscription.objects.select_related("id_cours")
    if academic_year:
        all_inscriptions = all_inscriptions.filter(id_annee=academic_year)
    inscription_ids = list(
        all_inscriptions.values_list("id_inscription", flat=True)
    )
    absence_sums = dict(
        Absence.objects.filter(
            id_inscription__in=inscription_ids,
            statut__in=[
                Absence.Statut.NON_JUSTIFIEE,
                Absence.Statut.EN_ATTENTE,
            ],
        )
        .values("id_inscription")
        .annotate(total=Sum("duree_absence"))
        .values_list("id_inscription", "total")
    )
    at_risk_count = 0
    for ins in all_inscriptions:
        cours = ins.id_cours
        if cours.nombre_total_periodes > 0:
            total_abs = float(absence_sums.get(ins.id_inscription, 0) or 0)
            rate = (total_abs / cours.nombre_total_periodes) * 100
            seuil = (
                cours.seuil_absence
                if cours.seuil_absence is not None
                else system_threshold
            )
            seuil_effectif = min(seuil + ins.exemption_margin, 100) if ins.exemption_40 else seuil
            if rate >= seuil_effectif:
                at_risk_count += 1

    seven_days_ago = timezone.now() - datetime.timedelta(days=7)
    critical_actions = LogAudit.objects.filter(
        date_action__gte=seven_days_ago, niveau="CRITIQUE"
    ).count()

    data = {
        "academic_year": academic_year.libelle if academic_year else None,
        "total_students": total_students,
        "total_professors": total_professors,
        "total_secretaries": total_secretaries,
        "active_courses": active_courses,
        "total_inscriptions": total_inscriptions,
        "total_absences": total_absences,
        "students_at_risk": at_risk_count,
        "critical_actions_7d": critical_actions,
    }
    return Response(DashboardAnalyticsSerializer(data).data)


@extend_schema(
    summary="Absence statistics & charts data (admin only)",
    tags=["Analytics"],
    responses=StatisticsAnalyticsSerializer,
)
@api_view(["GET"])
@permission_classes([IsAdmin])
def statistics_analytics(request):
    """Advanced absence statistics as JSON (for charts)."""
    academic_year = AnneeAcademique.objects.filter(active=True).first()
    year_filter = (
        Q(id_inscription__id_annee=academic_year) if academic_year else Q()
    )

    # Top 5 professors by absence count
    top_professors = list(
        Absence.objects.filter(year_filter)
        .values(
            nom=F("id_inscription__id_cours__professeur__nom"),
            prenom=F("id_inscription__id_cours__professeur__prenom"),
        )
        .annotate(total=Count("id_absence"))
        .order_by("-total")[:5]
    )
    top_professors = [
        {"name": f"{p['prenom']} {p['nom']}", "count": p["total"]}
        for p in top_professors
        if p["nom"]
    ]

    # Top 5 courses by absence count
    top_courses = list(
        Absence.objects.filter(year_filter)
        .values(name=F("id_inscription__id_cours__nom_cours"))
        .annotate(count=Count("id_absence"))
        .order_by("-count")[:5]
    )

    # Monthly evolution
    monthly_absences = list(
        Absence.objects.filter(year_filter)
        .annotate(month=TruncMonth("id_seance__date_seance"))
        .values("month")
        .annotate(count=Count("id_absence"))
        .order_by("month")
    )
    monthly_absences = [
        {"month": m["month"].strftime("%Y-%m"), "count": m["count"]}
        for m in monthly_absences
        if m["month"]
    ]

    # By department
    dept_absences = list(
        Absence.objects.filter(year_filter)
        .values(
            name=F(
                "id_inscription__id_cours__id_departement__nom_departement"
            )
        )
        .annotate(count=Count("id_absence"))
        .order_by("-count")
    )
    dept_absences = [d for d in dept_absences if d["name"]]

    # By status
    status_map = {
        Absence.Statut.NON_JUSTIFIEE: "Non justifiée",
        Absence.Statut.EN_ATTENTE: "En attente",
        Absence.Statut.JUSTIFIEE: "Justifiée",
    }
    status_absences = list(
        Absence.objects.filter(year_filter)
        .values("statut")
        .annotate(count=Count("id_absence"))
        .order_by("statut")
    )
    status_absences = [
        {"status": status_map.get(s["statut"], s["statut"]), "count": s["count"]}
        for s in status_absences
    ]

    # By level
    level_absences = list(
        Absence.objects.filter(year_filter)
        .values(niveau=F("id_inscription__id_cours__niveau"))
        .annotate(count=Count("id_absence"))
        .order_by("niveau")
    )
    level_absences = [
        {"level": f"Année {lv['niveau']}", "count": lv["count"]}
        for lv in level_absences
        if lv["niveau"]
    ]

    data = {
        "academic_year": academic_year.libelle if academic_year else None,
        "top_professors": top_professors,
        "top_courses": top_courses,
        "monthly_absences": monthly_absences,
        "absences_by_department": dept_absences,
        "absences_by_status": status_absences,
        "absences_by_level": level_absences,
    }
    return Response(StatisticsAnalyticsSerializer(data).data)


# ══════════════════════════════════════════════════════════════════════════════
# Feature 3: Export PDF / Excel API
# ══════════════════════════════════════════════════════════════════════════════


@extend_schema(
    summary="Export student absence report as PDF",
    tags=["Exports"],
    responses={(200, "application/pdf"): bytes},
)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def export_student_pdf_api(request, student_id):
    """Generate PDF absence report for a student."""
    user = request.user

    # Permission check: students can only export their own report
    if user.role == User.Role.ETUDIANT:
        if user.pk != student_id:
            return Response(
                {"detail": "You can only export your own report."},
                status=status.HTTP_403_FORBIDDEN,
            )
        student = user
    elif user.role in (User.Role.ADMIN, User.Role.SECRETAIRE):
        student = get_object_or_404(
            User, pk=student_id, role=User.Role.ETUDIANT
        )
    else:
        return Response(
            {"detail": "Not authorized."},
            status=status.HTTP_403_FORBIDDEN,
        )

    academic_year = AnneeAcademique.objects.filter(active=True).first()

    insc_filter = {
        "id_etudiant": student,
        "status": Inscription.Status.EN_COURS,
    }
    if academic_year:
        insc_filter["id_annee"] = academic_year

    inscriptions = Inscription.objects.filter(**insc_filter).select_related(
        "id_cours"
    )
    inscription_ids = list(
        inscriptions.values_list("id_inscription", flat=True)
    )

    absence_sums = dict(
        Absence.objects.filter(
            id_inscription__in=inscription_ids,
            statut__in=[
                Absence.Statut.NON_JUSTIFIEE,
                Absence.Statut.EN_ATTENTE,
            ],
        )
        .values("id_inscription")
        .annotate(total=Sum("duree_absence"))
        .values_list("id_inscription", "total")
    )

    absences = (
        Absence.objects.filter(
            id_inscription__in=inscription_ids,
            statut__in=[
                Absence.Statut.NON_JUSTIFIEE,
                Absence.Statut.EN_ATTENTE,
            ],
        )
        .select_related("id_seance", "id_seance__id_cours")
        .order_by("id_seance__date_seance")
    )

    # Build PDF
    buf = io.BytesIO()
    p = canvas.Canvas(buf, pagesize=A4)
    width, height = A4

    def check_page_break(y, margin=80):
        if y < margin:
            p.showPage()
            return height - 50
        return y

    p.setFont("Helvetica-Bold", 16)
    p.drawString(50, height - 50, "Universite - Rapport d'Absences")

    p.setFont("Helvetica", 12)
    p.drawString(50, height - 80, f"Etudiant: {student.get_full_name()}")
    p.drawString(50, height - 100, f"Email: {student.email}")
    if academic_year:
        p.drawString(
            50, height - 120, f"Annee academique: {academic_year.libelle}"
        )
    p.drawString(
        50, height - 140, f"Date du rapport: {datetime.date.today()}"
    )

    p.line(50, height - 160, width - 50, height - 160)
    y = height - 180

    p.setFont("Helvetica-Bold", 14)
    p.drawString(50, y, "Resume par Cours")
    y -= 20

    p.setFont("Helvetica", 10)
    for ins in inscriptions:
        cours = ins.id_cours
        total_abs = float(absence_sums.get(ins.id_inscription, 0) or 0)
        p.drawString(
            60,
            y,
            f"- {cours.nom_cours} ({cours.code_cours}): {total_abs}h non justifiees",
        )
        y -= 15
        y = check_page_break(y)

    y = check_page_break(y - 10)
    p.setFont("Helvetica-Bold", 14)
    p.drawString(50, y, "Detail des Absences Non Justifiees")
    y -= 20

    p.setFont("Helvetica", 10)
    for absence_obj in absences:
        seance = absence_obj.id_seance
        line = (
            f"Date: {seance.date_seance} | "
            f"Cours: {seance.id_cours.code_cours} | "
            f"Duree: {absence_obj.duree_absence}h | "
            f"Statut: {absence_obj.get_statut_display()}"
        )
        p.drawString(60, y, line)
        y -= 15
        y = check_page_break(y)

    p.showPage()
    p.save()

    buf.seek(0)
    safe_email = "".join(
        c if c.isalnum() or c in "._-@" else "_" for c in student.email
    )
    response = HttpResponse(buf.read(), content_type="application/pdf")
    response["Content-Disposition"] = (
        f'attachment; filename="rapport_absences_{safe_email}.pdf"'
    )
    return response


@extend_schema(
    summary="Export at-risk students as Excel (admin/secretary)",
    tags=["Exports"],
    responses={(200, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"): bytes},
)
def _export_status(ins, rate, seuil):
    """Return export status label based on exemption logic."""
    seuil_eff = min(seuil + ins.exemption_margin, 100) if ins.exemption_40 else seuil
    if rate >= seuil_eff:
        return "BLOQUE"
    if ins.exemption_40:
        return "SOUS EXEMPTION"
    return "A RISQUE"


@api_view(["GET"])
@permission_classes([IsAdminOrSecretary])
def export_at_risk_excel_api(request):
    """Export students exceeding absence threshold to Excel."""
    academic_year = AnneeAcademique.objects.filter(active=True).first()
    system_threshold = get_system_threshold()

    all_inscriptions = Inscription.objects.filter(
        status=Inscription.Status.EN_COURS
    ).select_related("id_cours", "id_etudiant")
    if academic_year:
        all_inscriptions = all_inscriptions.filter(id_annee=academic_year)

    inscription_ids = list(
        all_inscriptions.values_list("id_inscription", flat=True)
    )
    absence_sums = dict(
        Absence.objects.filter(
            id_inscription__in=inscription_ids,
            statut__in=[
                Absence.Statut.NON_JUSTIFIEE,
                Absence.Statut.EN_ATTENTE,
            ],
        )
        .values("id_inscription")
        .annotate(total=Sum("duree_absence"))
        .values_list("id_inscription", "total")
    )

    wb = Workbook()
    ws = wb.active
    ws.title = "Etudiants a Risque"
    ws.append([
        "Nom",
        "Prenom",
        "Email",
        "Cours",
        "Heures Manquees",
        "Taux Absence (%)",
        "Statut",
    ])

    for ins in all_inscriptions:
        cours = ins.id_cours
        if cours.nombre_total_periodes > 0:
            total_abs = float(absence_sums.get(ins.id_inscription, 0) or 0)
            rate = (total_abs / cours.nombre_total_periodes) * 100
            seuil = (
                cours.seuil_absence
                if cours.seuil_absence is not None
                else system_threshold
            )
            if rate >= seuil:
                ws.append([
                    ins.id_etudiant.nom,
                    ins.id_etudiant.prenom,
                    ins.id_etudiant.email,
                    f"{cours.nom_cours} ({cours.code_cours})",
                    total_abs,
                    round(rate, 2),
                    _export_status(ins, rate, seuil),
                ])

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    response = HttpResponse(
        buf.read(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = (
        'attachment; filename="etudiants_a_risque.xlsx"'
    )
    return response
