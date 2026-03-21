# MAP DU CODE - Navigation Rapide Soutenance

> Fichier vivant - mis a jour a chaque fichier refactore
> Total : ~14 000 lignes Python | 10 apps Django | ~60 templates

---

## COEUR METIER : Gestion des Absences

### Modeles de donnees (`apps/absences/models.py` - 383 lignes)
| Classe | Ligne | Description |
|--------|-------|-------------|
| `Absence` | 9 | Absence etudiant a une seance (type, duree, statut) |
| `Absence.TypeAbsence` | 15 | ABSENT, PARTIEL |
| `Absence.Statut` | 26 | EN_ATTENTE, JUSTIFIEE, NON_JUSTIFIEE |
| `Justification` | 153 | Document de justification avec etat et suivi |
| `Justification.State` | 158 | EN_ATTENTE, ACCEPTEE, REFUSEE |
| `QRAttendanceToken` | 243 | Token QR a duree limitee avec support GPS |
| `QRScanRecord` | 294 | Enregistrement du scan QR etudiant |
| `QRScanLog` | 332 | Log audit de CHAQUE tentative de scan |

### Logique metier (`apps/absences/services.py` - 757 lignes)
| Fonction | Ligne | Description |
|----------|-------|-------------|
| `get_justification_deadline()` | 25 | Calcule date limite de justification |
| `is_justification_expired()` | 35 | Verifie si le delai est depasse |
| `calculer_absence_stats()` | 45 | Statistiques d'absences pour une inscription |
| `get_absences_queryset()` | 77 | Queryset optimise avec select_related |
| `calculer_pourcentage_absence()` | 89 | Taux d'absence etudiant/cours (heures reelles) |
| `etudiants_en_alerte()` | 180 | Liste etudiants depassant le seuil pour un cours |
| `recalculer_eligibilite()` | 265 | **CRITIQUE** : Recalcul eligibilite apres absence |
| `_send_threshold_emails()` | 393 | Emails seuil depasse (etudiant + prof) |
| `get_system_threshold()` | 407 | Seuil systeme par defaut |
| `calculer_risque_inscription()` | 417 | Calcul statut de risque centralise |
| `get_at_risk_count_for_queryset()` | 473 | Comptage etudiants a risque (SQL optimise) |
| `predict_absence_risk()` | 534 | Detection predictive tendance vers seuil |

### Signaux (`apps/absences/signals.py` - 65 lignes)
| Fonction | Ligne | Description |
|----------|-------|-------------|
| `_schedule_eligibility_recalc()` | 21 | Differe recalcul apres commit transaction |
| `absence_post_save()` | 43 | Recalcule eligibilite apres sauvegarde absence |
| `absence_post_delete()` | 56 | Recalcule eligibilite apres suppression absence |

---

## ENREGISTREMENT DES ABSENCES (`apps/absences/views.py` - 1714 lignes)

### Marquage Manuel (Professeur)
| Fonction | Ligne | Description |
|----------|-------|-------------|
| `session_create()` | 402 | Point d'entree : creer seance + choisir mode (manuel/QR) |
| `mark_absence()` | 533 | **VUE PRINCIPALE** : Enregistrer presences/absences |
| `mark_absence_htmx()` | 953 | Mise a jour HTMX sans rechargement page |
| `validate_session()` | 1120 | Verrouiller seance apres validation |

### Systeme QR Code
| Fonction | Ligne | Description |
|----------|-------|-------------|
| `_generate_qr_data_uri()` | 1182 | Genere QR code PNG en base64 data-URI |
| `qr_generate()` | 1197 | Prof cree seance + genere QR pour scan etudiants |
| `qr_dashboard()` | 1294 | Dashboard live : QR + liste scans temps reel (HTMX) |
| `qr_refresh_token()` | 1364 | Desactive QR actuel + nouveau token |
| `qr_finalize()` | 1421 | Marque non-scannes absents + verrouille seance |
| `_log_scan_attempt()` | 1492 | Log chaque tentative de scan (succes/echec) |
| `_get_establishment_gps()` | 1509 | Coordonnees GPS et rayon depuis SystemSettings |
| `qr_scan()` | 1519 | **SCAN ETUDIANT** : Verification GPS + anti-doublon |
| `_haversine()` | 1172 | Calcul distance GPS (formule Haversine) |

### Justifications Etudiant
| Fonction | Ligne | Description |
|----------|-------|-------------|
| `absence_details()` | 53 | Details absence + justifications + deadline |
| `upload_justification()` | 153 | Upload document justificatif (validation fichier) |
| `review_justification()` | 304 | Secretaire revoit justification soumise |
| `download_justification()` | 362 | Telechargement securise du document |

---

## VALIDATION DES ABSENCES (`apps/absences/views_validation.py` - 723 lignes)

| Fonction | Ligne | Description |
|----------|-------|-------------|
| `validation_list()` | 66 | Liste absences filtrees par statut (pagination) |
| `process_justification()` | 130 | **Approuver/Rejeter** justification (transaction + lock) |
| `create_justified_absence()` | 289 | Secretaire encode absence directement justifiee |
| `student_absence_history_api()` | 529 | API historique absences etudiant (JSON) |
| `justified_absences_list()` | 616 | Liste toutes les absences justifiees |
| `_send_justification_decision_emails()` | 42 | Emails decision (etudiant + prof) |

### Edition (`apps/absences/views_manager.py` - 187 lignes)
| Fonction | Ligne | Description |
|----------|-------|-------------|
| `edit_absence()` | 38 | Modifier type/statut/duree absence (audit log) |

---

## DASHBOARDS PAR ROLE

### Dashboard Etudiant (`apps/dashboard/views_student.py` - 707 lignes)
| Fonction | Ligne | Description |
|----------|-------|-------------|
| `student_dashboard()` | 19 | KPIs : inscriptions, absences, alertes |
| `student_statistics()` | 135 | Statistiques detaillees + graphiques |
| `student_course_detail()` | 271 | Detail cours : seances + absences |
| `student_courses()` | 426 | Liste cours inscrits avec taux absence |
| `student_absences()` | 567 | Historique complet absences + justifications |
| `student_reports()` | 655 | Page telechargement rapports PDF |

### Dashboard Professeur (`apps/dashboard/views_professor.py` - 566 lignes)
| Fonction | Ligne | Description |
|----------|-------|-------------|
| `instructor_dashboard()` | 21 | KPIs : cours, etudiants a risque |
| `instructor_course_detail()` | 151 | Detail cours : etudiants, seances, stats |
| `instructor_courses()` | 299 | Liste cours assignes au prof |
| `instructor_sessions()` | 414 | Liste seances pour tous les cours |
| `instructor_statistics()` | 463 | Statistiques globales du prof |

### Dashboard Secretaire (`apps/dashboard/views.py` - 580 lignes)
| Fonction | Ligne | Description |
|----------|-------|-------------|
| `dashboard_redirect()` | 21 | Redirige vers dashboard selon role |
| `secretary_dashboard()` | 69 | KPIs : absences, etudiants a risque |
| `secretary_enrollments()` | 165 | Gestion inscriptions (filtres + pagination) |
| `secretary_seuils_absence()` | 265 | Etudiants en infraction de seuil |
| `secretary_exports()` | 342 | Page exports Excel/PDF |
| `get_active_courses_queryset()` | 399 | Cours actifs (filtre actif=True) |
| `active_courses()` | 431 | Cours actifs avec inscriptions/seances |

### Dashboard Admin
| Fichier | Fonction | Ligne | Description |
|---------|----------|-------|-------------|
| `views_admin_stats.py` | `admin_dashboard_main()` | 32 | KPIs admin + vue d'ensemble |
| `views_admin_stats.py` | `admin_statistics()` | 164 | Statistiques avancees + graphiques |
| `views_admin_users.py` | `admin_users()` | 32 | Liste/filtrer utilisateurs |
| `views_admin_users.py` | `admin_user_create()` | 77 | Creer utilisateur |
| `views_admin_users.py` | `admin_user_edit()` | 111 | Modifier utilisateur |
| `views_admin_users.py` | `admin_user_reset_password()` | 166 | Reset mot de passe |
| `views_admin_users.py` | `admin_user_delete()` | 414 | Supprimer utilisateur |
| `views_admin_users.py` | `admin_users_delete_multiple()` | 230 | Suppression en lot |
| `views_admin_courses.py` | `admin_faculties()` | 42 | CRUD Facultes |
| `views_admin_courses.py` | `admin_departments()` | 248 | CRUD Departements |
| `views_admin_courses.py` | `admin_courses()` | 453 | CRUD Cours |
| `views_admin_courses.py` | `admin_academic_years()` | 658 | CRUD Annees academiques |
| `views_admin_settings.py` | `admin_settings()` | 30 | Parametres systeme |
| `views_admin_settings.py` | `admin_audit_logs()` | 83 | Logs audit avec filtres |
| `views_admin_settings.py` | `admin_export_audit_csv()` | 150 | Export CSV audit |
| `views_admin_settings.py` | `admin_qr_scan_logs()` | 235 | Logs scans QR |

---

## GESTION ACADEMIQUE

### Modeles (`apps/academics/models.py` - 264 lignes)
| Classe | Ligne | Description |
|--------|-------|-------------|
| `Faculte` | 5 | Faculte universitaire |
| `Departement` | 33 | Departement dans une faculte |
| `Cours` | 77 | Cours avec niveau, seuil, prerequis |
| `Cours.get_seuil_absence()` | 255 | Seuil du cours ou seuil systeme par defaut |

### Sessions (`apps/academic_sessions/models.py`)
| Classe | Ligne | Description |
|--------|-------|-------------|
| `AnneeAcademique` | 8 | Annee academique (une seule active) |
| `Seance` | 83 | Seance de cours avec date/heure |
| `Seance.duree_heures()` | 163 | Duree en heures decimales |

### Inscriptions (`apps/enrollments/models.py`)
| Classe | Ligne | Description |
|--------|-------|-------------|
| `Inscription` | 7 | Inscription etudiant/cours/annee |
| `Inscription.TypeInscription` | 13 | NORMALE, A_PART |
| `Inscription.Status` | 17 | EN_COURS, VALIDE, NON_VALIDE |
| `Inscription.cloture()` | 150 | Cloture inscription |

---

## INSCRIPTIONS (`apps/enrollments/views.py` - 790 lignes)

| Fonction | Ligne | Description |
|----------|-------|-------------|
| `enrollment_manager()` | 34 | UI gestion inscriptions |
| `get_departments()` | 49 | API : departements par faculte |
| `get_courses()` | 100 | API : cours actifs par departement |
| `get_courses_by_year()` | 178 | API : cours par annee academique |
| `get_courses_by_student()` | 275 | API : cours inscrits d'un etudiant |
| `enroll_student()` | 362 | **Inscrire etudiant** (niveau ou cours specifiques) |

### Regles (`apps/enrollments/views_rules.py` - 189 lignes)
| Fonction | Ligne | Description |
|----------|-------|-------------|
| `rules_management()` | 20 | Etudiants en infraction + exemptions |
| `toggle_exemption()` | 107 | Accorder/revoquer exemption seuil |

---

## AUTHENTIFICATION (`apps/accounts/`)

### Modele User (`models.py` - 281 lignes)
| Element | Ligne | Description |
|---------|-------|-------------|
| `UserManager` | 10 | Manager custom pour creation utilisateur |
| `User` | 51 | Modele custom avec 4 roles |
| `User.Role` | 100 | ADMIN, SECRETAIRE, PROFESSEUR, ETUDIANT |
| `User._sync_role_flags()` | 207 | Synchronise is_staff/is_superuser selon role |

### Vues (`views.py` - 305 lignes)
| Fonction | Ligne | Description |
|----------|-------|-------------|
| `RateLimitedLoginView` | 44 | Login avec rate limiting |
| `profile_view()` | 65 | Profil selon role (template dynamique) |
| `settings_view()` | 89 | Preferences utilisateur |
| `download_report_pdf()` | 121 | Genere PDF rapport absences |
| `CustomPasswordChangeView` | 246 | Changement mot de passe + flag must_change |

### Setup initial (`views_setup.py` - 115 lignes)
| Fonction | Ligne | Description |
|----------|-------|-------------|
| `initial_setup()` | 78 | Page unique creation premier admin |
| `setup_complete()` | 107 | Page succes apres creation admin |

### Securite
| Fichier | Element | Ligne | Description |
|---------|---------|-------|-------------|
| `middleware.py` | `SessionInactivityMiddleware` | 36 | Deconnexion auto apres inactivite |
| `middleware.py` | `RoleMiddleware` | 62 | Verification permissions par role |
| `validators.py` | `SystemSettingsPasswordValidator` | 8 | Validation mot de passe configurable |

---

## API REST (`apps/api/views.py` - 959 lignes)

| ViewSet/Fonction | Ligne | Description |
|------------------|-------|-------------|
| `StudentViewSet` | 80 | CRUD etudiants |
| `CoursViewSet` | 144 | CRUD cours |
| `InscriptionViewSet` | 207 | CRUD inscriptions |
| `AbsenceViewSet` | 267 | CRUD absences |
| `JustificationViewSet` | 336 | Justifications + action process |
| `JustificationViewSet.process()` | 417 | Approuver/rejeter via API |
| `NotificationViewSet` | 487 | Notifications + mark_read |
| `dashboard_analytics()` | 530 | KPIs admin (JSON) |
| `statistics_analytics()` | 613 | Stats avancees (JSON) |
| `export_student_pdf_api()` | 725 | Export PDF via API |
| `export_at_risk_excel_api()` | 881 | Export Excel etudiants a risque |

---

## MESSAGERIE (`apps/messaging/views.py` - 154 lignes)

| Fonction | Ligne | Description |
|----------|-------|-------------|
| `inbox()` | 31 | Messages recus (pagination) |
| `sent_box()` | 55 | Messages envoyes |
| `compose()` | 79 | Composer message (filtrage destinataires par role) |
| `message_detail()` | 123 | Detail message + marquer lu |

---

## NOTIFICATIONS (`apps/notifications/email.py` - 344 lignes)

| Fonction | Ligne | Description |
|----------|-------|-------------|
| `send_notification_email()` | 35 | Envoi email unitaire (jamais d'exception) |
| `send_email_async()` | 87 | Envoi asynchrone (thread) |
| `send_with_dedup()` | 118 | Anti-doublon avec fenetre cooldown |
| `build_threshold_exceeded_email()` | 160 | Email seuil depasse (etudiant) |
| `build_threshold_exceeded_professor_email()` | 181 | Email seuil depasse (prof) |
| `build_eligibility_restored_email()` | 204 | Email eligibilite restauree |
| `build_justification_decision_email()` | 241 | Email decision justification |
| `build_absence_recorded_email()` | 287 | Email absence enregistree |
| `build_weekly_summary_email()` | 309 | Resume hebdomadaire secretaires |

---

## AUDIT (`apps/audits/`)

| Fichier | Element | Ligne | Description |
|---------|---------|-------|-------------|
| `models.py` | `LogAudit` | 5 | Modele log audit (lecture seule) |
| `utils.py` | `log_action()` | 17 | Cree entree audit (validation + sanitization) |
| `ip_utils.py` | `extract_client_ip()` | 34 | IP client via proxies de confiance |
| `ip_utils.py` | `ratelimit_client_ip()` | 53 | Cle rate limiting par IP |
| `views.py` | `audit_list()` | 16 | Liste filtree logs audit |

---

## EXPORTS (`apps/dashboard/views_export.py` - 264 lignes)

| Fonction | Ligne | Description |
|----------|-------|-------------|
| `export_student_pdf()` | 22 | PDF rapport absences etudiant |
| `export_at_risk_excel()` | 172 | Excel etudiants a risque |

---

## CONFIGURATION (`config/settings.py` - 490 lignes)

| Element | Ligne | Description |
|---------|-------|-------------|
| `env_bool()` | 16 | Parse variable env booleenne |
| `env_int()` | 23 | Parse variable env entiere |
| `env_list()` | 33 | Parse variable env liste |
| `env_cidr_list()` | 38 | Parse liste CIDR avec validation |

---

## SECURITE TRANSVERSALE

| Fichier | Element | Description |
|---------|---------|-------------|
| `apps/dashboard/decorators.py` | `admin_required()` L89 | Decorateur verification admin |
| `apps/dashboard/decorators.py` | `secretary_required()` L138 | Decorateur verification secretaire |
| `apps/dashboard/decorators.py` | `professor_required()` L204 | Decorateur verification professeur |
| `apps/dashboard/decorators.py` | `student_required()` L253 | Decorateur verification etudiant |
| `apps/dashboard/decorators.py` | `api_login_required()` L58 | Login requis API (retourne 401 JSON) |
| `apps/api/permissions.py` | `IsAdmin` L6 | Permission DRF admin |
| `apps/api/permissions.py` | `IsAdminOrSecretary` L37 | Permission DRF admin ou secretaire |
| `apps/absences/utils_upload.py` | `validate_uploaded_file()` L116 | Validation stricte fichiers (ext + MIME + signature) |

---

## FORMULAIRES PRINCIPAUX

| Fichier | Classe | Description |
|---------|--------|-------------|
| `apps/absences/forms.py` | `SecretaryJustifiedAbsenceForm` | Encodage absence justifiee |
| `apps/enrollments/forms.py` | `StudentCreationForm` | Creation etudiant a l'inscription |
| `apps/enrollments/forms.py` | `EnrollmentForm` | Inscription etudiant (niveau/cours) |
| `apps/messaging/forms.py` | `MessageForm` | Composition message (filtrage role) |
| `apps/accounts/forms.py` | `CustomAuthenticationForm` | Formulaire login |
| `apps/dashboard/forms_admin.py` | `CoursForm` L47 | CRUD cours (admin/secretaire) |
| `apps/dashboard/forms_admin.py` | `UserForm` L207 | CRUD utilisateurs |
| `apps/dashboard/forms_admin.py` | `SystemSettingsForm` L334 | Parametres systeme |

---

## TESTS (`tests/` - 9 fichiers)

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
