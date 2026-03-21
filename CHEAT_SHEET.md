# Cheat Sheet Soutenance - Reponses Rapides

## Questions Probables du Prof

---

### Q: "Comment fonctionne le marquage des absences ?"
**R:** `apps/absences/views.py` ligne 554 - fonction `mark_absence()`
- Le prof cree une seance (`session_create()` L423), choisit mode manuel ou QR
- Mode manuel : formulaire avec liste etudiants, statut present/absent/partiel
- Chaque absence sauvegardee declenche un signal (`signals.py` L43) qui recalcule l'eligibilite
- Validation par le prof verrouille la seance (`validate_session()` L1151)

---

### Q: "Montre-moi le systeme QR Code"
**R:** `apps/absences/views.py` lignes 1203-1650
- Generation QR : `qr_generate()` L1228 - cree token + QR en base64
- Dashboard live : `qr_dashboard()` L1325 - affiche QR + liste scans en temps reel (HTMX polling)
- Scan etudiant : `qr_scan()` L1555 - verifie GPS + anti-doublon + token valide
- Verification GPS : `_haversine()` L1203 - formule mathematique distance GPS
- Finalisation : `qr_finalize()` L1452 - marque non-scannes absents
- Modeles : `QRAttendanceToken` L272, `QRScanRecord` L323, `QRScanLog` L361

---

### Q: "Comment gerez-vous les justifications ?"
**R:** Flux complet :
1. Etudiant upload document : `upload_justification()` views.py L169
2. Validation fichier (extension + MIME + signature binaire) : `utils_upload.py` L126
3. Secretaire voit liste : `validation_list()` views_validation.py L82
4. Approbation/rejet (avec lock + transaction) : `process_justification()` L151
5. Emails envoyes : `_send_justification_decision_emails()` L56
6. Deadline calculee : `services.py` L43 `get_justification_deadline()`

---

### Q: "Comment calculez-vous l'eligibilite ?"
**R:** `apps/absences/services.py` ligne 303 - `recalculer_eligibilite()`
- Taux absence = heures absence / volume horaire total du cours
- Seuil par cours (`Cours.get_seuil_absence()` academics/models.py L266) ou seuil systeme
- Si taux >= seuil : etudiant bloque (non eligible)
- Exemption possible (regle des 40%) : `toggle_exemption()` enrollments/views_rules.py L116
- Recalcul automatique via signal post_save/post_delete sur Absence

---

### Q: "Comment securisez-vous l'application ?"
**R:** Plusieurs couches :
- **Authentification** : Login rate-limited (`accounts/views.py` L55), session timeout (`middleware.py` L47)
- **Autorisation** : Decorateurs par role (`decorators.py` L89-299), permissions DRF (`api/permissions.py`)
- **Mots de passe** : Validateur configurable (`validators.py` L8), force change au premier login
- **Upload fichiers** : Triple validation extension + MIME + magic bytes (`utils_upload.py` L126)
- **Anti-injection** : Sanitization audit logs, ORM Django (pas de SQL brut)
- **CSRF** : Middleware Django actif, SRI sur CDN
- **GPS anti-fraude** : Verification distance Haversine pour scan QR

---

### Q: "Quels sont les 4 roles et leurs permissions ?"
**R:** `apps/accounts/models.py` ligne 111 - `User.Role`
| Role | Peut faire | Decorateur |
|------|-----------|-----------|
| ADMIN | Tout : CRUD users/cours/facultes, stats, audit, parametres | `admin_required()` L89 |
| SECRETAIRE | Inscriptions, absences justifiees, exports, structure acad. | `secretary_required()` L138 |
| PROFESSEUR | Marquer absences, voir ses cours/etudiants, stats | `professor_required()` L204 |
| ETUDIANT | Voir ses absences, soumettre justifications, messages | `student_required()` L253 |

---

### Q: "Comment fonctionne le systeme de notifications ?"
**R:** `apps/notifications/email.py` (344 lignes)
- Envoi asynchrone (thread) : `send_email_async()` L87
- Anti-doublon : `send_with_dedup()` L118 + modele `EmailLog` (digest SHA-256)
- Templates emails HTML : `templates/emails/` (9 templates)
- Types : seuil depasse, justification decidee, absence enregistree, resume hebdo
- Notifications in-app : modele `Notification` (`notifications/models.py` L9)

---

### Q: "Comment gerez-vous les inscriptions ?"
**R:** `apps/enrollments/views.py` ligne 381 - `enroll_student()`
- Inscription par niveau (tous les cours) ou cours specifiques
- Creation compte etudiant possible en meme temps (`StudentCreationForm`)
- Verification prerequis (non bloquant, avertissement) : `get_prerequisite_info()` L361
- API dynamique : departements/cours/annees chargees via AJAX
- Protection TOCTOU : `get_or_create()` pour inscription individuelle

---

### Q: "Quelle est l'architecture technique ?"
**R:**
- **Backend** : Django 5.x + DRF (API REST)
- **Base de donnees** : PostgreSQL 16
- **Cache** : Redis 7
- **Serveur** : Gunicorn + Nginx (SSL/HSTS/CSP)
- **Conteneurisation** : Docker Compose
- **Monitoring** : Uptime Kuma
- **CI/CD** : GitHub Actions (tests + securite)
- **Frontend** : Templates Django + HTMX (temps reel) + Bootstrap
- **Tests** : pytest (37 tests)

---

### Q: "Comment fonctionne l'API REST ?"
**R:** `apps/api/` - Django REST Framework
- 6 ViewSets : Student, Cours, Inscription, Absence, Justification, Notification
- Permissions par role : `api/permissions.py` (7 classes)
- Filtres avances : `api/filters.py` (5 classes FilterSet)
- Serializers : `api/serializers.py` (14 serializers)
- Documentation : Swagger UI + ReDoc auto-generee
- Endpoints analytics : `dashboard_analytics()` L545, `statistics_analytics()` L628

---

### Q: "Comment gerez-vous l'audit/tracabilite ?"
**R:** `apps/audits/`
- Chaque action critique logguee : `log_action()` utils.py L26
- Modele `LogAudit` : utilisateur, action, IP, timestamp, details
- Sanitization caracteres de controle (regex) avant ecriture
- Export CSV : `admin_export_audit_csv()` dashboard/views_admin_settings.py L166
- IP extraction via proxies de confiance : `extract_client_ip()` ip_utils.py L44

---

### Q: "Montrez-moi la gestion des erreurs / cas limites"
**R:** Exemples concrets :
- Race condition justification : `select_for_update()` dans `process_justification()` views_validation.py L151
- Seuil = 0 : guard specifique dans `student_dashboard` et `student_courses`
- Fichier upload : triple validation (extension + MIME + magic bytes)
- Email : `send_notification_email()` ne leve jamais d'exception (try/except global)
- GPS null : guard `.strftime()` sur champs time potentiellement None
- Annee active multiple : `AnneeAcademique.save()` desactive les autres automatiquement
