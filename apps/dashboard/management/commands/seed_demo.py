"""
Management command: populate the database with demo data for manual testing.

Usage:
    python manage.py seed_demo
    python manage.py seed_demo --reset   # wipe previously-seeded demo_* users/courses first

Creates (prefixed with "demo_"/"DEMO_" so they can be identified and removed):
    - Faculties + departments + active academic year (only if none exist)
    - 20 professors
    - 30 students (distributed across niveaux 1/2/3)
    - 30 courses (distributed across the existing departments and 3 niveaux)
    - Enrollments: every student is enrolled in every course of their own niveau
    - ~10 seances per course over the last 10 weeks
    - Random absences (~25% rate) across past seances

All demo accounts share the same password: Demo2026!
"""

import random
from datetime import date, time, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.absences.models import Absence
from apps.academic_sessions.models import AnneeAcademique, Seance
from apps.academics.models import Cours, Departement, Faculte
from apps.accounts.models import User
from apps.enrollments.models import Inscription


DEMO_PASSWORD = "Demo2026!"

FIRST_NAMES = [
    "Ahmed", "Yassine", "Karim", "Mehdi", "Omar", "Rachid", "Sami", "Hamza",
    "Youssef", "Anas", "Bilal", "Tarik", "Nabil", "Adil", "Jamal", "Walid",
    "Reda", "Khalid", "Said", "Marouane", "Fatima", "Amina", "Salma", "Nora",
    "Ikram", "Zineb", "Houda", "Lina", "Sara", "Meryem", "Asma", "Hajar",
    "Kenza", "Imane", "Chaima", "Dounia", "Layla", "Rania", "Soukaina", "Wafa",
    "Kamal", "Hicham", "Zakaria", "Ismail", "Othmane", "Amine", "Ayman", "Ilyas",
]

LAST_NAMES = [
    "Benali", "Tazi", "Bennani", "Alaoui", "Idrissi", "Berrada", "Fassi",
    "Chraibi", "Amrani", "Lahlou", "Zerhouni", "Belmahi", "Ouazzani", "Sebti",
    "Kadiri", "Rami", "Harti", "Mansouri", "Hajji", "Lakhdar", "Saidi", "Daoudi",
    "Benjelloun", "Zouhair", "Kabbaj", "Slimani", "Bourkia", "Ennaji", "Filali",
]

DEFAULT_FACULTIES = [
    ("Faculte des Sciences et Techniques", [
        "Informatique",
        "Mathematiques",
        "Physique",
    ]),
    ("Faculte des Sciences Economiques et Gestion", [
        "Gestion",
        "Economie",
    ]),
    ("Faculte des Lettres et Sciences Humaines", [
        "Langues",
    ]),
]

COURSE_TOPICS_BY_NIVEAU = {
    1: [
        ("Introduction a l'informatique", "INFO"),
        ("Algorithmique I", "ALGO"),
        ("Mathematiques discretes", "MATH"),
        ("Bases de donnees I", "BDD"),
        ("Programmation Python", "PY"),
        ("Anglais technique", "ENG"),
        ("Logique et raisonnement", "LOG"),
        ("Electromagnetisme", "EM"),
        ("Physique generale", "PHY"),
        ("Statistiques", "STA"),
    ],
    2: [
        ("Programmation orientee objet", "POO"),
        ("Structures de donnees", "DS"),
        ("Reseaux informatiques", "NET"),
        ("Systemes d'exploitation", "OS"),
        ("Bases de donnees II", "BDD"),
        ("Genie logiciel", "GL"),
        ("Developpement web", "WEB"),
        ("Probabilites", "PROB"),
        ("Architecture des ordinateurs", "ARCH"),
        ("Analyse numerique", "AN"),
    ],
    3: [
        ("Intelligence artificielle", "AI"),
        ("Securite informatique", "SEC"),
        ("Cloud computing", "CLOUD"),
        ("Big Data", "BIG"),
        ("Mobile development", "MOB"),
        ("DevOps", "DEVOPS"),
        ("Machine Learning", "ML"),
        ("Cryptographie", "CRY"),
        ("Microservices", "MICRO"),
        ("Projet de fin d'etude", "PFE"),
    ],
}


class Command(BaseCommand):
    help = "Populate the database with realistic demo data for manual testing."

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Delete previous demo_* users/courses before seeding.",
        )
        parser.add_argument(
            "--nb-students", type=int, default=30,
            help="Number of students to create (default: 30).",
        )
        parser.add_argument(
            "--nb-professors", type=int, default=20,
            help="Number of professors to create (default: 20).",
        )
        parser.add_argument(
            "--nb-courses", type=int, default=30,
            help="Number of courses to create (default: 30).",
        )
        parser.add_argument(
            "--nb-seances", type=int, default=10,
            help="Number of seances to create per course (default: 10).",
        )
        parser.add_argument(
            "--absence-rate", type=float, default=0.25,
            help="Probability that a student is absent in a seance (default: 0.25).",
        )
        parser.add_argument(
            "--year-label", type=str, default=None,
            help="Label of the academic year to create/use (e.g. 2025-2026). "
                 "If omitted, uses the active year or computes one from today.",
        )

    def handle(self, *args, **options):
        random.seed(42)

        nb_students = options["nb_students"]
        nb_profs = options["nb_professors"]
        nb_courses = options["nb_courses"]
        nb_seances = options["nb_seances"]
        absence_rate = options["absence_rate"]

        if options["reset"]:
            self._reset_demo_data()

        with transaction.atomic():
            year = self._ensure_academic_year(options.get("year_label"))
            self._ensure_faculties_and_departments()
            departements = list(Departement.objects.filter(actif=True))
            if not departements:
                raise CommandError("Failed to provision active departements.")

            encoder = User.objects.filter(role__in=["ADMIN", "SECRETAIRE"]).first()
            if encoder is None:
                raise CommandError(
                    "No ADMIN/SECRETAIRE user to own encoded absences. "
                    "Run 'python manage.py createsuperadmin' first."
                )

            profs = self._create_professors(nb_profs, departements)
            students = self._create_students(nb_students)
            courses = self._create_courses(nb_courses, departements, profs, year)
            self._enroll_students(students, courses, year)
            seances = self._create_seances(courses, year, nb_seances)
            nb_absences = self._create_absences(seances, students, encoder, absence_rate)

        self.stdout.write(self.style.SUCCESS(
            "\nDone. Created:\n"
            f"  - {len(profs)} professors\n"
            f"  - {len(students)} students\n"
            f"  - {len(courses)} courses\n"
            f"  - {len(seances)} seances\n"
            f"  - {nb_absences} absences\n"
            f"\nDemo password for every account: {DEMO_PASSWORD}\n"
            "Sample logins:\n"
            f"  Prof:    {profs[0].email}\n"
            f"  Student: {students[0].email}\n"
        ))

    # ------------------------------------------------------------------ #
    #  Academic year                                                     #
    # ------------------------------------------------------------------ #
    def _ensure_academic_year(self, label=None):
        """Return an active AnneeAcademique, creating one if needed."""
        if label:
            year, created = AnneeAcademique.objects.get_or_create(
                libelle=label,
                defaults={"active": True},
            )
            if not year.active and not AnneeAcademique.objects.filter(active=True).exists():
                year.active = True
                year.save()
            self.stdout.write(
                f"Academic year: {year.libelle} ({'created' if created else 'reused'}, active={year.active})"
            )
            return year

        existing_active = AnneeAcademique.objects.filter(active=True).first()
        if existing_active:
            self.stdout.write(f"Academic year: reusing active {existing_active.libelle}")
            return existing_active

        today = date.today()
        start_year = today.year if today.month >= 9 else today.year - 1
        computed_label = f"{start_year}-{start_year + 1}"
        year, created = AnneeAcademique.objects.get_or_create(
            libelle=computed_label,
            defaults={"active": True},
        )
        if not year.active:
            year.active = True
            year.save()
        self.stdout.write(
            f"Academic year: {year.libelle} ({'created' if created else 'activated'})"
        )
        return year

    # ------------------------------------------------------------------ #
    #  Faculties + departments                                           #
    # ------------------------------------------------------------------ #
    def _ensure_faculties_and_departments(self):
        """Create default faculties+departments if none exist."""
        if Departement.objects.filter(actif=True).exists():
            self.stdout.write("Faculties/departments: existing setup detected, skipping.")
            return

        self.stdout.write("Creating default faculties and departments...")
        for fac_name, dept_names in DEFAULT_FACULTIES:
            faculte, _ = Faculte.objects.get_or_create(
                nom_faculte=fac_name,
                defaults={"actif": True},
            )
            for dept_name in dept_names:
                Departement.objects.get_or_create(
                    nom_departement=dept_name,
                    id_faculte=faculte,
                    defaults={"actif": True},
                )
        nb_fac = Faculte.objects.count()
        nb_dept = Departement.objects.count()
        self.stdout.write(f"  -> {nb_fac} faculties / {nb_dept} departments ready.")

    # ------------------------------------------------------------------ #
    #  Reset                                                             #
    # ------------------------------------------------------------------ #
    def _reset_demo_data(self):
        self.stdout.write("Resetting previous demo data...")
        # Order matters — Absence -> Inscription -> Seance -> Cours -> User
        demo_users = User.objects.filter(email__startswith="demo_")
        demo_courses = Cours.objects.filter(code_cours__startswith="DEMO_")

        Absence.objects.filter(
            id_inscription__id_etudiant__in=demo_users
        ).delete()
        Inscription.objects.filter(id_etudiant__in=demo_users).delete()
        Seance.objects.filter(id_cours__in=demo_courses).delete()
        Absence.objects.filter(id_inscription__id_cours__in=demo_courses).delete()
        Inscription.objects.filter(id_cours__in=demo_courses).delete()
        demo_courses.delete()
        demo_users.delete()
        self.stdout.write(self.style.WARNING("  previous demo data removed."))

    # ------------------------------------------------------------------ #
    #  Users                                                             #
    # ------------------------------------------------------------------ #
    def _create_professors(self, n, departements):
        self.stdout.write(f"Creating {n} professors...")
        profs = []
        for i in range(n):
            first = random.choice(FIRST_NAMES)
            last = random.choice(LAST_NAMES)
            email = f"demo_prof{i + 1:02d}@uni.edu"
            user, created = User.objects.get_or_create(
                email=email,
                defaults={
                    "nom": last,
                    "prenom": first,
                    "role": User.Role.PROFESSEUR,
                    "actif": True,
                },
            )
            if created:
                user.set_password(DEMO_PASSWORD)
                user.save()
            profs.append(user)
        return profs

    def _create_students(self, n):
        self.stdout.write(f"Creating {n} students...")
        students = []
        for i in range(n):
            first = random.choice(FIRST_NAMES)
            last = random.choice(LAST_NAMES)
            email = f"demo_etu{i + 1:02d}@uni.edu"
            niveau = (i % 3) + 1  # distribute 1/2/3 evenly
            user, created = User.objects.get_or_create(
                email=email,
                defaults={
                    "nom": last,
                    "prenom": first,
                    "role": User.Role.ETUDIANT,
                    "niveau": niveau,
                    "actif": True,
                },
            )
            if created:
                user.set_password(DEMO_PASSWORD)
                user.save()
            students.append(user)
        return students

    # ------------------------------------------------------------------ #
    #  Courses                                                           #
    # ------------------------------------------------------------------ #
    def _create_courses(self, n, departements, profs, year):
        self.stdout.write(f"Creating {n} courses...")
        courses = []
        # Spread courses across niveaux 1/2/3
        niveau_order = [1, 2, 3]
        per_niveau = {1: [], 2: [], 3: []}
        for i in range(n):
            niveau = niveau_order[i % 3]
            per_niveau[niveau].append(i)

        counter = 0
        for niveau, indices in per_niveau.items():
            topics = COURSE_TOPICS_BY_NIVEAU[niveau]
            for idx, _i in enumerate(indices):
                topic_name, topic_code = topics[idx % len(topics)]
                code = f"DEMO_{topic_code}_{niveau}{idx + 1:02d}"
                dept = departements[counter % len(departements)]
                prof = profs[counter % len(profs)]
                course, created = Cours.objects.get_or_create(
                    code_cours=code,
                    defaults={
                        "nom_cours": f"{topic_name} (N{niveau})",
                        "nombre_total_periodes": random.choice([30, 40, 50, 60]),
                        "seuil_absence": None,  # use system default
                        "id_departement": dept,
                        "professeur": prof,
                        "id_annee": year,
                        "niveau": niveau,
                        "actif": True,
                    },
                )
                courses.append(course)
                counter += 1
        return courses

    # ------------------------------------------------------------------ #
    #  Enrollments                                                       #
    # ------------------------------------------------------------------ #
    def _enroll_students(self, students, courses, year):
        self.stdout.write("Enrolling students...")
        from django.db import IntegrityError
        count = 0
        for student in students:
            # Each student is enrolled in every course of their own niveau.
            matching = [c for c in courses if c.niveau == student.niveau]
            for course in matching:
                try:
                    _obj, created = Inscription.objects.get_or_create(
                        id_etudiant=student,
                        id_cours=course,
                        id_annee=year,
                        defaults={
                            "type_inscription": Inscription.TypeInscription.NORMALE,
                            "status": Inscription.Status.EN_COURS,
                            "eligible_examen": True,
                        },
                    )
                    if created:
                        count += 1
                except IntegrityError:
                    pass
        self.stdout.write(f"  -> {count} enrollments created.")

    # ------------------------------------------------------------------ #
    #  Seances                                                           #
    # ------------------------------------------------------------------ #
    def _create_seances(self, courses, year, nb_per_course):
        self.stdout.write(f"Creating ~{nb_per_course} seances per course...")
        seances = []
        today = date.today()
        # Slots (heure_debut, heure_fin) — 2h sessions
        slots = [
            (time(8, 0), time(10, 0)),
            (time(10, 15), time(12, 15)),
            (time(13, 0), time(15, 0)),
            (time(15, 15), time(17, 15)),
        ]
        for course in courses:
            # Generate unique dates spread across the past ~10 weeks (2/week).
            base_day = today - timedelta(days=nb_per_course * 3)
            offsets = random.sample(range(nb_per_course * 3), nb_per_course)
            offsets.sort()
            for k, offset in enumerate(offsets):
                seance_date = base_day + timedelta(days=offset)
                start, end = slots[k % len(slots)]
                # Skip if already exists (unique cours+date)
                if Seance.objects.filter(id_cours=course, date_seance=seance_date).exists():
                    continue
                seance = Seance.objects.create(
                    id_cours=course,
                    id_annee=year,
                    date_seance=seance_date,
                    heure_debut=start,
                    heure_fin=end,
                )
                seances.append(seance)
        self.stdout.write(f"  -> {len(seances)} seances created.")
        return seances

    # ------------------------------------------------------------------ #
    #  Absences                                                          #
    # ------------------------------------------------------------------ #
    def _create_absences(self, seances, students, encoder, rate):
        self.stdout.write(
            f"Marking absences (rate ~ {rate:.0%})... students not absent = present."
        )
        count = 0
        today = date.today()
        for seance in seances:
            if seance.date_seance > today:
                continue  # only past seances
            # Get all inscriptions for this course
            inscriptions = list(
                Inscription.objects.filter(
                    id_cours=seance.id_cours,
                    id_annee=seance.id_annee,
                    status=Inscription.Status.EN_COURS,
                ).select_related("id_etudiant")
            )
            duree_seance = Decimal(str(seance.duree_heures()))
            for insc in inscriptions:
                if random.random() > rate:
                    continue  # present
                try:
                    # Mix of full absences and partial absences
                    is_partial = random.random() < 0.25
                    if is_partial:
                        duree = round(
                            Decimal(str(random.uniform(0.25, float(duree_seance) - 0.5))),
                            2,
                        )
                        type_abs = Absence.TypeAbsence.PARTIEL
                    else:
                        duree = duree_seance
                        type_abs = Absence.TypeAbsence.ABSENT

                    statut = random.choices(
                        [
                            Absence.Statut.NON_JUSTIFIEE,
                            Absence.Statut.EN_ATTENTE,
                            Absence.Statut.JUSTIFIEE,
                        ],
                        weights=[70, 15, 15],
                        k=1,
                    )[0]

                    Absence.objects.create(
                        id_inscription=insc,
                        id_seance=seance,
                        type_absence=type_abs,
                        duree_absence=duree,
                        statut=statut,
                        encodee_par=encoder,
                    )
                    count += 1
                except Exception as exc:
                    self.stdout.write(self.style.WARNING(
                        f"    skip absence: {exc}"
                    ))
        return count
