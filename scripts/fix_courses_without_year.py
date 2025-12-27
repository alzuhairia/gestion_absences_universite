"""
Script pour assigner l'année académique active aux cours qui n'en ont pas
"""
import os
import sys
import django

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from apps.academics.models import Cours
from apps.academic_sessions.models import AnneeAcademique

# Trouver l'année académique active
active_year = AnneeAcademique.objects.filter(active=True).first()
if not active_year:
    print("Aucune annee academique active trouvee")
    exit(1)

print(f"Annee academique active: {active_year.libelle}")

# Trouver les cours sans année académique
courses_without_year = Cours.objects.filter(id_annee__isnull=True, actif=True)

print(f"\nCours sans annee academique: {courses_without_year.count()}")

if courses_without_year.exists():
    print("\nCours a corriger:")
    for course in courses_without_year:
        print(f"  - {course.code_cours} (niveau={course.niveau})")
    
    # Assigner automatiquement l'année active
    updated = courses_without_year.update(id_annee=active_year)
    print(f"\n{updated} cours mis a jour avec l'annee academique {active_year.libelle}")
else:
    print("\nAucun cours a corriger")

