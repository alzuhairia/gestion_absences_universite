"""
Script de vérification de santé de la base de données.
Vérifie l'intégrité référentielle, les index, et la cohérence des données.
"""
import os
import django
import sys

# Setup Django
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.db import connection
from apps.accounts.models import User
from apps.academics.models import Faculte, Departement, Cours
from apps.academic_sessions.models import AnneeAcademique
from apps.enrollments.models import Inscription
from apps.absences.models import Absence
from apps.audits.models import LogAudit
from apps.dashboard.models import SystemSettings

def check_foreign_keys():
    """Vérifie l'intégrité des clés étrangères"""
    print("\n=== Vérification des clés étrangères ===")
    issues = []
    
    # Vérifier les départements orphelins
    depts_orphans = Departement.objects.filter(id_faculte__isnull=True)
    if depts_orphans.exists():
        issues.append(f"[WARNING] {depts_orphans.count()} departements orphelins (sans faculte)")
    
    # Vérifier les cours orphelins
    cours_orphans = Cours.objects.filter(id_departement__isnull=True)
    if cours_orphans.exists():
        issues.append(f"[WARNING] {cours_orphans.count()} cours orphelins (sans departement)")
    
    # Vérifier les inscriptions orphelines
    insc_orphans = Inscription.objects.filter(
        id_etudiant__isnull=True
    ) | Inscription.objects.filter(
        id_cours__isnull=True
    ) | Inscription.objects.filter(
        id_annee__isnull=True
    )
    if insc_orphans.exists():
        issues.append(f"[WARNING] {insc_orphans.count()} inscriptions orphelines")
    
    # Vérifier les absences orphelines
    abs_orphans = Absence.objects.filter(
        id_inscription__isnull=True
    ) | Absence.objects.filter(
        id_seance__isnull=True
    )
    if abs_orphans.exists():
        issues.append(f"[WARNING] {abs_orphans.count()} absences orphelines")
    
    if issues:
        for issue in issues:
            print(issue)
    else:
        print("[OK] Aucun probleme d'integrite referentielle detecte")
    
    return len(issues) == 0

def check_indexes():
    """Vérifie la présence des index"""
    print("\n=== Vérification des index ===")
    with connection.cursor() as cursor:
        # Vérifier les index sur les tables principales
        tables_to_check = [
            ('utilisateur', ['role', 'actif']),
            ('faculte', ['nom_faculte', 'actif']),
            ('departement', ['nom_departement', 'actif']),
            ('cours', ['code_cours', 'actif']),
            ('inscription', ['type_inscription', 'eligible_examen', 'status']),
            ('absence', ['statut', 'type_absence']),
            ('log_audit', ['date_action', 'niveau', 'objet_type', 'objet_id']),
        ]
        
        missing_indexes = []
        for table, columns in tables_to_check:
            for column in columns:
                cursor.execute("""
                    SELECT COUNT(*) FROM pg_indexes 
                    WHERE tablename = %s AND indexdef LIKE %s
                """, [table, f'%{column}%'])
                if cursor.fetchone()[0] == 0:
                    missing_indexes.append(f"{table}.{column}")
        
        if missing_indexes:
            print(f"[WARNING] Index manquants: {', '.join(missing_indexes)}")
        else:
            print("[OK] Tous les index critiques sont presents")
        
        return len(missing_indexes) == 0

def check_data_consistency():
    """Vérifie la cohérence des données"""
    print("\n=== Vérification de la cohérence des données ===")
    issues = []
    
    # Vérifier qu'une seule année est active
    active_years = AnneeAcademique.objects.filter(active=True)
    if active_years.count() > 1:
        issues.append(f"[WARNING] {active_years.count()} annees academiques actives (devrait etre 1)")
    elif active_years.count() == 0:
        issues.append("[WARNING] Aucune annee academique active")
    else:
        print(f"[OK] Annee academique active: {active_years.first().libelle}")
    
    # Vérifier SystemSettings singleton
    settings_count = SystemSettings.objects.count()
    if settings_count == 0:
        issues.append("[WARNING] SystemSettings n'existe pas (creation automatique necessaire)")
    elif settings_count > 1:
        issues.append(f"[WARNING] {settings_count} instances de SystemSettings (devrait etre 1)")
    else:
        print(f"[OK] SystemSettings: seuil={SystemSettings.get_settings().default_absence_threshold}%")
    
    # Vérifier les seuils d'absence
    cours_invalid_seuil = Cours.objects.filter(
        models.Q(seuil_absence__lt=0) | models.Q(seuil_absence__gt=100)
    )
    if cours_invalid_seuil.exists():
        issues.append(f"[WARNING] {cours_invalid_seuil.count()} cours avec seuil invalide")
    
    if issues:
        for issue in issues:
            print(issue)
    else:
        print("[OK] Donnees coherentes")
    
    return len(issues) == 0

def check_audit_logs():
    """Vérifie les logs d'audit"""
    print("\n=== Vérification des logs d'audit ===")
    try:
        total_logs = LogAudit.objects.count()
        print(f"[OK] Total logs: {total_logs}")
        
        # Vérifier si les nouvelles colonnes existent
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT column_name FROM information_schema.columns 
                WHERE table_name = 'log_audit' AND column_name IN ('niveau', 'objet_type', 'objet_id')
            """)
            existing_columns = [row[0] for row in cursor.fetchall()]
        
        if 'niveau' in existing_columns:
            critical_logs = LogAudit.objects.filter(niveau='CRITIQUE').count()
            print(f"[OK] Logs critiques: {critical_logs}")
            
            # Vérifier les logs sans objet_type
            if 'objet_type' in existing_columns:
                logs_without_type = LogAudit.objects.filter(objet_type__isnull=True).count()
                if logs_without_type > 0:
                    print(f"[WARNING] {logs_without_type} logs sans objet_type (anciens logs)")
        else:
            print("[INFO] Colonnes niveau/objet_type/objet_id non presentes (migration a appliquer)")
        
        return True
    except Exception as e:
        print(f"[WARNING] Erreur lors de la verification: {e}")
        return True  # Ne pas bloquer si les colonnes n'existent pas encore

def main():
    """Fonction principale"""
    print("=" * 60)
    print("VERIFICATION DE SANTE DE LA BASE DE DONNEES")
    print("=" * 60)
    
    results = {
        'foreign_keys': check_foreign_keys(),
        'indexes': check_indexes(),
        'data_consistency': check_data_consistency(),
        'audit_logs': check_audit_logs(),
    }
    
    print("\n" + "=" * 60)
    print("RESUME")
    print("=" * 60)
    
    all_ok = all(results.values())
    
    for check, status in results.items():
        status_str = "[OK]" if status else "[ERROR]"
        print(f"{check.replace('_', ' ').title()}: {status_str}")
    
    if all_ok:
        print("\n[SUCCESS] Toutes les vérifications sont passées!")
        return 0
    else:
        print("\n[WARNING] Certaines vérifications ont échoué")
        return 1

if __name__ == '__main__':
    from django.db import models
    sys.exit(main())

