# 📋 PLAN DE RÉORGANISATION DU PROJET

## 🎯 OBJECTIFS
1. Nettoyer les fichiers temporaires, logs et scripts de test
2. Réorganiser selon les meilleures pratiques Django
3. Regrouper la documentation
4. Créer une structure claire et maintenable
5. Mettre à jour tous les imports automatiquement

---

## 📊 ANALYSE ACTUELLE

### ✅ Structure déjà correcte
- `apps/` - Applications Django bien organisées
- `config/` - Configuration Django
- `templates/` - Templates bien organisés
- `static/` - Fichiers statiques
- `media/` - Fichiers média (vide, OK)

### ❌ Problèmes identifiés

#### 1. Fichiers à la racine (à nettoyer)
- **Scripts de test/setup** (15 fichiers) :
  - `setup_test_data.py`, `setup_test_data_v2.py`, `setup_test_data_v3.py`, `setup_test_data_v4.py`
  - `setup_test_data_justif.py`, `setup_uat_data.py`, `setup_teacher.py`
  - `verify_*.py` (9 fichiers)
  - `check_schema.py`, `check_schema_django.py`
  - `fix_migrations.py`, `force_add_column.py`
  - `create_system_settings_table.py`
  - `reset_messaging_db.py`, `reproduce_issue.py`
  - `test_final.py`

- **Fichiers temporaires** :
  - `models_temp.py`
  - `gestion_absences_universite` (fichier sans extension)
  - `db.sqlite3` (base de données SQLite, devrait être ignorée)

- **Fichiers de logs** :
  - `error.log`
  - `debug_log.txt`
  - `traceback.txt`

- **Documentation dispersée** (15 fichiers .md) :
  - `README.md` (garder à la racine)
  - Tous les autres .md (14 fichiers) à déplacer dans `docs/`

- **Fichiers de backup** :
  - `templates/dashboard/student_index.bak`

#### 2. Dossiers à créer
- `scripts/` - Scripts utilitaires et de maintenance
- `docs/` - Documentation du projet
- `tests/` - Tests unitaires (structure pour l'avenir)

#### 3. Fichiers __pycache__ et .pyc
- À nettoyer (normalement ignorés par git, mais présents localement)

---

## 🏗️ NOUVELLE STRUCTURE PROPOSÉE

```
gestion_absences_universite/
│
├── apps/                          # Applications Django (GARDER)
│   ├── accounts/
│   ├── academics/
│   ├── academic_sessions/
│   ├── absences/
│   ├── audits/
│   ├── dashboard/
│   ├── enrollments/
│   ├── messaging/
│   └── notifications/
│
├── config/                        # Configuration Django (GARDER)
│   ├── settings.py
│   ├── urls.py
│   ├── wsgi.py
│   └── asgi.py
│
├── templates/                      # Templates HTML (GARDER)
│   ├── accounts/
│   ├── absences/
│   ├── audits/
│   ├── dashboard/
│   ├── enrollments/
│   ├── messaging/
│   └── base_*.html
│
├── static/                         # Fichiers statiques (GARDER)
│   ├── css/
│   ├── js/
│   └── images/
│
├── media/                          # Fichiers média (GARDER)
│
├── scripts/                        # ✨ NOUVEAU - Scripts utilitaires
│   ├── setup/
│   │   ├── setup_test_data.py
│   │   ├── setup_uat_data.py
│   │   └── setup_teacher.py
│   ├── verify/
│   │   ├── verify_at_risk.py
│   │   ├── verify_audits.py
│   │   ├── verify_enrollments.py
│   │   ├── verify_exports.py
│   │   ├── verify_rules.py
│   │   ├── verify_validation.py
│   │   ├── verify_correction.py
│   │   ├── verify_roles.py
│   │   └── verify_database_health.py
│   ├── maintenance/
│   │   ├── check_schema.py
│   │   ├── check_schema_django.py
│   │   ├── fix_migrations.py
│   │   ├── force_add_column.py
│   │   ├── create_system_settings_table.py
│   │   └── reset_messaging_db.py
│   └── __init__.py
│
├── docs/                           # ✨ NOUVEAU - Documentation
│   ├── README.md                   # Documentation principale
│   ├── audits/
│   │   ├── AUDIT_ADMIN_MODULE_PART1.md
│   │   ├── AUDIT_ADMIN_MODULE_PART1_RESUME.md
│   │   ├── AUDIT_DATABASE_PART2.md
│   │   ├── AUDIT_DATABASE_RESUME.md
│   │   └── AUDIT_FRONTEND_LANGUE_PART3.md
│   ├── validations/
│   │   ├── VALIDATION_MODULE_ADMIN.md
│   │   ├── VALIDATION_MODULE_PROFESSEUR.md
│   │   ├── VALIDATION_MODULE_ETUDIANT.md
│   │   └── VALIDATION_MODULE_SECRETAIRE.md
│   ├── corrections/
│   │   ├── CORRECTION_ERREUR_LANCEMENT.md
│   │   ├── CORRECTIONS_DATABASE_APPLIQUEES.md
│   │   └── AMELIORATION_PAGE_CONNEXION.md
│   └── summaries/
│       ├── AUDIT_MODULES_PROFESSEUR_ETUDIANT.md
│       ├── RESUME_FINAL_AUDIT_MODULES.md
│       └── FINALISATION_COMPLETE.md
│
├── tests/                          # ✨ NOUVEAU - Tests (structure pour l'avenir)
│   └── __init__.py
│
├── .gitignore                      # Mettre à jour
├── manage.py                       # GARDER
├── README.md                       # GARDER (documentation principale)
├── requirements.txt                # ✨ À CRÉER (si pas présent)
└── .env.example                    # ✨ À CRÉER (template pour .env)
```

---

## 🗑️ FICHIERS À SUPPRIMER

### Fichiers temporaires
- `models_temp.py`
- `gestion_absences_universite` (fichier sans extension)
- `templates/dashboard/student_index.bak`

### Fichiers de logs (à supprimer ou déplacer)
- `error.log`
- `debug_log.txt`
- `traceback.txt`

### Base de données SQLite (devrait être dans .gitignore)
- `db.sqlite3` (garder si nécessaire pour dev, mais ajouter à .gitignore)

---

## 📝 ACTIONS À EFFECTUER

### Phase 1 : Création des nouveaux dossiers
1. Créer `scripts/setup/`
2. Créer `scripts/verify/`
3. Créer `scripts/maintenance/`
4. Créer `docs/audits/`
5. Créer `docs/validations/`
6. Créer `docs/corrections/`
7. Créer `docs/summaries/`
8. Créer `tests/`

### Phase 2 : Déplacement des fichiers
1. Déplacer les scripts de setup → `scripts/setup/`
2. Déplacer les scripts verify → `scripts/verify/`
3. Déplacer les scripts maintenance → `scripts/maintenance/`
4. Déplacer la documentation → `docs/` (sous-dossiers appropriés)

### Phase 3 : Mise à jour des imports
1. Mettre à jour tous les imports dans les scripts déplacés
2. Mettre à jour les références dans la documentation
3. Vérifier que tous les chemins relatifs fonctionnent

### Phase 4 : Nettoyage
1. Supprimer les fichiers temporaires
2. Supprimer les fichiers de logs
3. Supprimer les fichiers .bak
4. Nettoyer les __pycache__ (optionnel, se régénèrent)

### Phase 5 : Mise à jour de .gitignore
1. Ajouter les patterns pour logs/
2. S'assurer que db.sqlite3 est ignoré
3. Ajouter patterns pour fichiers temporaires

---

## ⚠️ POINTS D'ATTENTION

### Imports à mettre à jour dans les scripts
Tous les scripts qui utilisent :
```python
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
```

Devront être mis à jour avec le chemin relatif correct :
```python
import os
import sys
from pathlib import Path

# Ajouter le répertoire racine au path
BASE_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BASE_DIR))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
```

### Fichiers à garder à la racine
- `manage.py` (obligatoire Django)
- `README.md` (documentation principale)
- `.gitignore`
- `.env` (ne pas commiter, mais garder à la racine)
- `requirements.txt` (si présent)

---

## ✅ VALIDATION

Après réorganisation, vérifier :
1. ✅ Tous les scripts fonctionnent depuis leur nouveau emplacement
2. ✅ Les imports sont corrects
3. ✅ La documentation est accessible
4. ✅ Le projet Django démarre correctement
5. ✅ Les migrations fonctionnent
6. ✅ Les tests (s'il y en a) passent

---

## 🚀 PROCHAINES ÉTAPES

Une fois ce plan validé, je procéderai à :
1. Création des dossiers
2. Déplacement des fichiers
3. Mise à jour automatique de tous les imports
4. Nettoyage des fichiers inutiles
5. Mise à jour du .gitignore
6. Test de fonctionnement

**Confirmez-vous ce plan avant que je procède ?**

