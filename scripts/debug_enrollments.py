"""
Script de débogage pour vérifier les inscriptions et les cours
"""
import os
import sys
import django

# Ajouter le répertoire parent au path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from apps.academics.models import Cours
from apps.academic_sessions.models import AnneeAcademique
from apps.accounts.models import User
from apps.enrollments.models import Inscription

print("=== VÉRIFICATION DES COURS ===")
print(f"\nTotal cours actifs: {Cours.objects.filter(actif=True).count()}")

print("\nCours par niveau:")
for n in [1, 2, 3]:
    c = Cours.objects.filter(niveau=n, actif=True)
    print(f"  Niveau {n}: {c.count()} cours")
    for course in c:
        year_str = course.id_annee.libelle if course.id_annee else "NULL"
        print(f"    - {course.code_cours}: année={year_str}")

print("\nCours par année académique:")
for y in AnneeAcademique.objects.all():
    c = Cours.objects.filter(id_annee=y, actif=True)
    print(f"  {y.libelle} (active={y.active}): {c.count()} cours")

print("\nCours sans année académique:")
c = Cours.objects.filter(id_annee__isnull=True, actif=True)
print(f"  {c.count()} cours")
for course in c:
    print(f"    - {course.code_cours} (niveau={course.niveau})")

print("\n=== VÉRIFICATION DES INSCRIPTIONS ===")
print(f"\nTotal inscriptions: {Inscription.objects.count()}")
print(f"Inscriptions EN_COURS: {Inscription.objects.filter(status='EN_COURS').count()}")

active_year = AnneeAcademique.objects.filter(active=True).first()
if active_year:
    print(f"\nInscriptions pour l'année active ({active_year.libelle}):")
    inscriptions = Inscription.objects.filter(id_annee=active_year, status='EN_COURS')
    print(f"  {inscriptions.count()} inscriptions")
    for ins in inscriptions:
        print(f"    - {ins.id_etudiant.get_full_name()} -> {ins.id_cours.code_cours} (niveau={ins.id_cours.niveau})")
else:
    print("\nAucune année académique active trouvée")

print("\n=== VÉRIFICATION DE L'ÉTUDIANT ===")
student = User.objects.filter(email='louis.vanderveken@hainaut-promsoc.be').first()
if student:
    print(f"\nÉtudiant trouvé: {student.get_full_name()}")
    print(f"  Niveau: {student.niveau}")
    print(f"  Inscriptions: {Inscription.objects.filter(id_etudiant=student).count()}")
    for ins in Inscription.objects.filter(id_etudiant=student):
        print(f"    - {ins.id_cours.code_cours} (année={ins.id_annee.libelle}, statut={ins.status})")
else:
    print("\nÉtudiant non trouvé")

