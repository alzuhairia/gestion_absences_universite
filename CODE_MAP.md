# MAP DU CODE - Navigation Rapide Soutenance

> Derniere mise a jour : 2026-03-21 (apres refactoring complet)
> Total : ~14 000 lignes Python | 10 apps Django | ~60 templates
> Tous les fichiers sont documentes avec en-tetes et sections

---

## COEUR METIER : Gestion des Absences

### Modeles de donnees (`apps/absences/models.py`)
| Classe | Ligne | Description |
|--------|-------|-------------|
| `Absence` | 26 | Absence etudiant a une seance (type, duree, statut) |
| `Absence.TypeAbsence` | 32 | ABSENT, PARTIEL |
| `Absence.Statut` | 43 | EN_ATTENTE, JUSTIFIEE, NON_JUSTIFIEE |
| `Justification` | 175 | Document de justification (workflow EN_ATTENTE -> ACCEPTEE/REFUSEE) |
| `QRAttendanceToken` | 272 | Token QR a duree limitee avec support GPS |
| `QRScanRecord` | 323 | Enregistrement du scan QR etudiant |
| `QRScanLog` | 361 | Log audit de CHAQUE tentative de scan |

### Logique metier (`apps/absences/services.py`)
| Fonction | Ligne | Description |
|----------|-------|-------------|
| `get_justification_deadline()` | 43 | Calcule date limite de justification |
| `calculer_absence_stats()` | 68 | Statistiques d'absences pour une inscription |
| `calculer_pourcentage_absence()` | 117 | Taux d'absence etudiant/cours (heures reelles) |
| `etudiants_en_alerte()` | 213 | Liste etudiants depassant le seuil pour un cours |
| `recalculer_eligibilite()` | 303 | **CRITIQUE** : Recalcul eligibilite apres absence |
| `get_system_threshold()` | 450 | Seuil systeme par defaut |
| `calculer_risque_inscription()` | 465 | Calcul statut de risque centralise |
| `get_at_risk_count_for_queryset()` | 521 | Comptage etudiants a risque (SQL optimise) |
| `predict_absence_risk()` | 582 | Detection predictive tendance vers seuil |

### Signaux (`apps/absences/signals.py`)
| Fonction | Ligne | Description |
|----------|-------|-------------|
| `absence_post_save()` | 43 | Recalcule eligibilite apres sauvegarde absence |
| `absence_post_delete()` | 56 | Recalcule eligibilite apres suppression absence |

---

## ENREGISTREMENT DES ABSENCES (`apps/absences/views.py`)

### Justifications Etudiant
| Fonction | Ligne | Description |
|----------|-------|-------------|
| `absence_details()` | 69 | Details absence + justifications + deadline |
| `upload_justification()` | 169 | Upload document justificatif (validation fichier) |

### Marquage Manuel (Professeur)
| Fonction | Ligne | Description |
|----------|-------|-------------|
| `session_create()` | 423 | Point d'entree : creer seance + choisir mode (manuel/QR) |
| `mark_absence()` | 554 | **VUE PRINCIPALE** : Enregistrer presences/absences |
| `mark_absence_htmx()` | 979 | Mise a jour HTMX sans rechargement page |
| `validate_session()` | 1151 | Verrouiller seance apres validation |

### Systeme QR Code
| Fonction | Ligne | Description |
|----------|-------|-------------|
| `_haversine()` | 1203 | Calcul distance GPS (formule Haversine) |
| `_generate_qr_data_uri()` | 1213 | Genere QR code PNG en base64 data-URI |
| `qr_generate()` | 1228 | Prof cree seance + genere QR pour scan etudiants |
| `qr_dashboard()` | 1325 | Dashboard live : QR + liste scans temps reel (HTMX) |
| `qr_refresh_token()` | 1395 | Desactive QR actuel + nouveau token |
| `qr_finalize()` | 1452 | Marque non-scannes absents + verrouille seance |
| `_log_scan_attempt()` | 1523 | Log chaque tentative de scan (succes/echec) |
| `qr_scan()` | 1555 | **SCAN ETUDIANT** : Verification GPS + anti-doublon |

---

## VALIDATION DES ABSENCES (`apps/absences/views_validation.py`)

| Fonction | Ligne | Description |
|----------|-------|-------------|
| `validation_list()` | 82 | Liste absences filtrees par statut (pagination) |
| `process_justification()` | 151 | **Approuver/Rejeter** justification (transaction + lock) |
| `create_justified_absence()` | 315 | Secretaire encode absence directement justifiee |
| `student_absence_history_api()` | 560 | API historique absences etudiant (JSON) |
| `justified_absences_list()` | 652 | Liste toutes les absences justifiees |

### Edition (`apps/absences/views_manager.py`)
| Fonction | Ligne | Description |
|----------|-------|-------------|
| `edit_absence()` | 47 | Modifier type/statut/duree absence (audit log) |

---

## DASHBOARDS PAR ROLE

### Dashboard Etudiant (`apps/dashboard/views_student.py`)
| Fonction | Ligne | Description |
|----------|-------|-------------|
| `student_dashboard()` | 37 | KPIs : inscriptions, absences, alertes |
| `student_statistics()` | 158 | Statistiques detaillees + graphiques |
| `student_course_detail()` | 299 | Detail cours : seances + absences |
| `student_courses()` | 459 | Liste cours inscrits avec taux absence |
| `student_absences()` | 600 | Historique complet absences + justifications |
| `student_reports()` | 693 | Page telechargement rapports PDF |

### Dashboard Professeur (`apps/dashboard/views_professor.py`)
| Fonction | Ligne | Description |
|----------|-------|-------------|
| `instructor_dashboard()` | 38 | KPIs : cours, etudiants a risque |
| `instructor_course_detail()` | 173 | Detail cours : etudiants, seances, stats |
| `instructor_courses()` | 326 | Liste cours assignes au prof |
| `instructor_sessions()` | 441 | Liste seances pour tous les cours |
| `instructor_statistics()` | 495 | Statistiques globales du prof |

### Dashboard Secretaire (`apps/dashboard/views.py`)
| Fonction | Ligne | Description |
|----------|-------|-------------|
| `dashboard_redirect()` | 33 | Redirige vers dashboard selon role |
| `secretary_dashboard()` | 85 | KPIs : absences, etudiants a risque |
| `secretary_enrollments()` | 181 | Gestion inscriptions (filtres + pagination) |
| `secretary_seuils_absence()` | 281 | Etudiants en infraction de seuil |
| `secretary_exports()` | 358 | Page exports Excel/PDF |
| `active_courses()` | 451 | Cours actifs avec inscriptions/seances |

### Dashboard Admin
| Fichier | Fonction | Ligne | Description |
|---------|----------|-------|-------------|
| `views_admin_stats.py` | `admin_dashboard_main()` | 44 | KPIs admin + vue d'ensemble |
| `views_admin_stats.py` | `admin_statistics()` | 176 | Statistiques avancees + graphiques |
| `views_admin_users.py` | `admin_users()` | 44 | Liste/filtrer utilisateurs |
| `views_admin_users.py` | `admin_user_create()` | 89 | Creer utilisateur |
| `views_admin_users.py` | `admin_user_edit()` | 123 | Modifier utilisateur |
| `views_admin_courses.py` | `admin_faculties()` | 54 | CRUD Facultes |
| `views_admin_courses.py` | `admin_departments()` | 260 | CRUD Departements |
| `views_admin_courses.py` | `admin_courses()` | 465 | CRUD Cours |
| `views_admin_courses.py` | `admin_academic_years()` | 670 | CRUD Annees academiques |
| `views_admin_settings.py` | `admin_settings()` | 42 | Parametres systeme |
| `views_admin_settings.py` | `admin_audit_logs()` | 99 | Logs audit avec filtres |
| `views_admin_settings.py` | `admin_export_audit_csv()` | 166 | Export CSV audit |

---

## GESTION ACADEMIQUE

### Modeles (`apps/academics/models.py`)
| Classe | Ligne | Description |
|--------|-------|-------------|
| `Faculte` | 16 | Faculte universitaire |
| `Departement` | 44 | Departement dans une faculte |
| `Cours` | 88 | Cours avec niveau, seuil, prerequis |
| `Cours.get_seuil_absence()` | 266 | Seuil du cours ou seuil systeme par defaut |

### Sessions (`apps/academic_sessions/models.py`)
| Classe | Ligne | Description |
|--------|-------|-------------|
| `AnneeAcademique` | 23 | Annee academique (une seule active) |
| `Seance` | 102 | Seance de cours avec date/heure |
| `Seance.duree_heures()` | 182 | Duree en heures decimales |

### Inscriptions (`apps/enrollments/models.py`)
| Classe | Ligne | Description |
|--------|-------|-------------|
| `Inscription` | 18 | Inscription etudiant/cours/annee |
| `Inscription.TypeInscription` | 24 | NORMALE, A_PART |
| `Inscription.Status` | 28 | EN_COURS, VALIDE, NON_VALIDE |
| `Inscription.cloture()` | 161 | Cloture inscription |

---

## INSCRIPTIONS (`apps/enrollments/views.py`)

| Fonction | Ligne | Description |
|----------|-------|-------------|
| `enrollment_manager()` | 49 | UI gestion inscriptions |
| `get_departments()` | 68 | API : departements par faculte |
| `get_courses()` | 119 | API : cours actifs par departement |
| `enroll_student()` | 381 | **Inscrire etudiant** (niveau ou cours specifiques) |

### Regles (`apps/enrollments/views_rules.py`)
| Fonction | Ligne | Description |
|----------|-------|-------------|
| `rules_management()` | 29 | Etudiants en infraction + exemptions |
| `toggle_exemption()` | 116 | Accorder/revoquer exemption seuil |

---

## AUTHENTIFICATION (`apps/accounts/`)

### Modele User (`models.py`)
| Element | Ligne | Description |
|---------|-------|-------------|
| `UserManager` | 22 | Manager custom pour creation utilisateur |
| `User` | 62 | Modele custom avec 4 roles |
| `User.Role` | 111 | ADMIN, SECRETAIRE, PROFESSEUR, ETUDIANT |
| `User._sync_role_flags()` | 218 | Synchronise is_staff/is_superuser selon role |

### Securite
| Fichier | Element | Description |
|---------|---------|-------------|
| `middleware.py` | `SessionInactivityMiddleware` L47 | Deconnexion auto apres inactivite |
| `middleware.py` | `RoleMiddleware` L73 | Verification permissions par role |
| `validators.py` | `SystemSettingsPasswordValidator` L17 | Validation mot de passe configurable |

---

## API REST (`apps/api/views.py`)

| ViewSet/Fonction | Ligne | Description |
|------------------|-------|-------------|
| `StudentViewSet` | 94 | CRUD etudiants |
| `CoursViewSet` | 158 | CRUD cours |
| `AbsenceViewSet` | 281 | CRUD absences |
| `JustificationViewSet` | 350 | Justifications + action process |
| `dashboard_analytics()` | 545 | KPIs admin (JSON) |
| `statistics_analytics()` | 628 | Stats avancees (JSON) |
| `export_student_pdf_api()` | 740 | Export PDF via API |
| `export_at_risk_excel_api()` | 896 | Export Excel etudiants a risque |

---

## MESSAGERIE (`apps/messaging/views.py`)

| Fonction | Ligne | Description |
|----------|-------|-------------|
| `inbox()` | 41 | Messages recus (pagination) |
| `sent_box()` | 65 | Messages envoyes |
| `compose()` | 89 | Composer message (filtrage destinataires par role) |
| `message_detail()` | 133 | Detail message + marquer lu |

---

## NOTIFICATIONS (`apps/notifications/email.py`)

| Fonction | Ligne | Description |
|----------|-------|-------------|
| `send_notification_email()` | 35 | Envoi email unitaire (jamais d'exception) |
| `send_email_async()` | 87 | Envoi asynchrone (thread) |
| `send_with_dedup()` | 118 | Anti-doublon avec fenetre cooldown |
| `build_threshold_exceeded_email()` | 160 | Email seuil depasse (etudiant) |
| `build_eligibility_restored_email()` | 204 | Email eligibilite restauree |
| `build_justification_decision_email()` | 241 | Email decision justification |
| `build_absence_recorded_email()` | 287 | Email absence enregistree |
| `build_weekly_summary_email()` | 309 | Resume hebdomadaire secretaires |

---

## SECURITE TRANSVERSALE

| Fichier | Element | Description |
|---------|---------|-------------|
| `apps/dashboard/decorators.py` | `admin_required()` L89 | Decorateur verification admin |
| `apps/dashboard/decorators.py` | `secretary_required()` L138 | Decorateur verification secretaire |
| `apps/dashboard/decorators.py` | `professor_required()` L204 | Decorateur verification professeur |
| `apps/dashboard/decorators.py` | `student_required()` L253 | Decorateur verification etudiant |
| `apps/dashboard/decorators.py` | `api_login_required()` L58 | Login requis API (retourne 401 JSON) |
| `apps/api/permissions.py` | `IsAdmin` | Permission DRF admin |
| `apps/api/permissions.py` | `IsAdminOrSecretary` | Permission DRF admin ou secretaire |
| `apps/absences/utils_upload.py` | `validate_uploaded_file()` | Validation stricte fichiers (ext + MIME + signature) |

---

## TESTS (`tests/` - 9 fichiers, 65 tests)

| Fichier | Description |
|---------|-------------|
| `test_absence_logic.py` | Logique metier absences |
| `test_absences.py` | Vues absences |
| `test_api_auth.py` | Authentification API |
| `test_ci_checks.py` | Verifications CI |
| `test_frontend_session_contract.py` | Contrat front/back sessions |
| `test_health.py` | Health check endpoint |
| `test_password_policy.py` | Politique mots de passe |
| `test_performance_queries.py` | Performance requetes SQL |
| `test_qr_gps.py` | QR code + GPS |

---

## ARCHITECTURE TEMPLATES

```
templates/
  base.html                    -- Layout principal
  base_admin.html              -- Layout admin
  base_auth.html               -- Layout authentification
  base_instructor.html         -- Layout professeur
  base_secretary.html          -- Layout secretaire
  base_student.html            -- Layout etudiant
  absences/                    -- 12 templates absence/QR
  accounts/                    -- 12 templates auth/profil
  dashboard/                   -- 30+ templates par role
  enrollments/                 -- 3 templates inscription
  messaging/                   -- 16 templates (4 par role)
  emails/                      -- 9 templates email
  audits/                      -- 1 template logs
```
