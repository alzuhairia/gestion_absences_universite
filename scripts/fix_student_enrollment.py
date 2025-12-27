"""
Script pour réinscrire l'étudiant Louis VANDERVEKEN au niveau 2
"""
import os
import sys
import django

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from apps.accounts.models import User
from apps.academics.models import Cours
from apps.academic_sessions.models import AnneeAcademique
from apps.enrollments.models import Inscription
from django.db import transaction

# Trouver l'étudiant
student = User.objects.filter(email='louis.vanderveken@hainaut-promsoc.be').first()
if not student:
    print("Étudiant non trouvé")
    exit(1)

print(f"Étudiant trouvé: {student.get_full_name()}")
print(f"Niveau actuel: {student.niveau}")

# Trouver l'année académique active
active_year = AnneeAcademique.objects.filter(active=True).first()
if not active_year:
    print("Aucune année académique active trouvée")
    exit(1)

print(f"Année académique active: {active_year.libelle}")

# Trouver les cours de niveau 2 pour cette année
niveau = 2
level_courses = Cours.objects.filter(
    niveau=niveau,
    id_annee=active_year,
    actif=True
)

print(f"\nCours trouvés pour le niveau {niveau}: {level_courses.count()}")
for course in level_courses:
    print(f"  - {course.code_cours}: {course.nom_cours}")

if not level_courses.exists():
    print("\nAucun cours trouvé. Vérifiez que les cours ont bien le niveau 2 et l'année académique assignée.")
    exit(1)

# Mettre à jour le niveau de l'étudiant
student.niveau = niveau
student.save()
print(f"\nNiveau de l'étudiant mis à jour à {niveau}")

# Inscrire l'étudiant aux cours
enrolled_count = 0
skipped_count = 0

with transaction.atomic():
    for course in level_courses:
        # Vérifier si déjà inscrit
        if Inscription.objects.filter(
            id_etudiant=student,
            id_cours=course,
            id_annee=active_year
        ).exists():
            print(f"  [*] Deja inscrit a {course.code_cours}")
            skipped_count += 1
            continue
        
        # Créer l'inscription
        Inscription.objects.create(
            id_etudiant=student,
            id_cours=course,
            id_annee=active_year,
            type_inscription='NORMALE',
            eligible_examen=True,
            status='EN_COURS'
        )
        print(f"  [+] Inscrit a {course.code_cours}")
        enrolled_count += 1

print(f"\nRésultat:")
print(f"  - {enrolled_count} nouvelle(s) inscription(s) créée(s)")
print(f"  - {skipped_count} inscription(s) déjà existante(s)")

# Vérifier les inscriptions
total_inscriptions = Inscription.objects.filter(id_etudiant=student).count()
print(f"\nTotal inscriptions pour cet étudiant: {total_inscriptions}")

