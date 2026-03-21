# Resume Soutenance - Gestion des Absences Universitaires

## Le Projet en 3 Phrases

Systeme complet de gestion des absences pour une universite, avec marquage
par QR Code et verification GPS anti-fraude. Quatre roles (Etudiant,
Professeur, Secretaire, Admin) avec dashboards dedies et permissions strictes.
Stack technique : Django, PostgreSQL, Redis, Docker, API REST, HTMX temps reel.

---

## Architecture Technique

```
                    +------------------+
                    |     Nginx        |  SSL/HSTS/CSP
                    |  (reverse proxy) |
                    +--------+---------+
                             |
                    +--------+---------+
                    |  Django/Gunicorn  |  10 apps modulaires
                    |  (backend)        |
                    +--+-----+------+--+
                       |     |      |
              +--------+  +--+--+  +--------+
              | PostgreSQL| |Redis| |  Media  |
              |   (DB)    | |(cache)| |(uploads)|
              +-----------+ +------+ +---------+
```

**10 apps Django :**
- `accounts` : Authentification, 4 roles, mots de passe
- `academics` : Facultes, Departements, Cours
- `academic_sessions` : Annees academiques, Seances
- `absences` : Absences, Justifications, QR Code (coeur metier)
- `enrollments` : Inscriptions, Regles d'absence, Exemptions
- `dashboard` : Interfaces par role (etudiant, prof, secretaire, admin)
- `api` : API REST (DRF) avec Swagger/ReDoc
- `messaging` : Messagerie interne
- `notifications` : Emails + notifications in-app
- `audits` : Journal d'audit complet

---

## Les 6 Fonctionnalites Cles

### 1. Marquage des Absences (Manuel)
- **Ou** : `apps/absences/views.py` L554 `mark_absence()`
- **Comment** : Prof cree seance, coche present/absent pour chaque etudiant
- **Puis** : Signal recalcule automatiquement l'eligibilite

### 2. Systeme QR Code + GPS
- **Ou** : `apps/absences/views.py` L1228-1555
- **Comment** : Prof genere QR -> Etudiant scanne -> GPS verifie la distance
- **Securite** : Token UUID expire (15 min), anti-doublon, log audit chaque scan

### 3. Calcul Automatique d'Eligibilite
- **Ou** : `apps/absences/services.py` L303 `recalculer_eligibilite()`
- **Comment** : Signal post_save -> calcul taux -> blocage si >= seuil
- **Regle** : taux = heures_absences / total_periodes * 100

### 4. Justifications avec Workflow
- **Ou** : `apps/absences/views_validation.py` L151 `process_justification()`
- **Workflow** : Etudiant upload -> Secretaire approuve/rejette -> Email envoye
- **Securite** : Triple validation fichier (extension + MIME + signature binaire)

### 5. Dashboards Multi-Roles
- **Etudiant** : `views_student.py` - absences, cours, statistiques
- **Professeur** : `views_professor.py` - cours, etudiants a risque
- **Secretaire** : `views.py` - inscriptions, exports, seuils
- **Admin** : `views_admin_*.py` - CRUD complet, parametres, audit

### 6. API REST Complete
- **Ou** : `apps/api/views.py` - 6 ViewSets + endpoints analytics
- **Doc** : Swagger UI auto-generee (`/api/docs/`)
- **Auth** : Session + Token, permissions par role

---

## Securite (Points a Mentionner)

| Couche | Implementation |
|--------|---------------|
| Authentification | Login rate-limited, session timeout 15 min |
| Autorisation | Decorateurs par role (`@admin_required`, etc.) |
| Mots de passe | Validateur configurable, force change au 1er login |
| Uploads | Triple validation (extension + MIME + magic bytes) |
| CSRF/XSS | Middleware Django, CSP nonce-based, SRI sur CDN |
| Audit | Chaque action critique logguee (utilisateur, IP, timestamp) |
| GPS anti-fraude | Haversine distance, rayon configurable |

---

## Chiffres Cles

| Metrique | Valeur |
|----------|--------|
| Lignes de code Python | ~14 000 |
| Applications Django | 10 |
| Templates HTML | ~60 |
| Tests automatises | 65 (tous passants) |
| Lignes de documentation | 1 338 |
| Modeles de donnees | 12 |
| Endpoints API | 20+ |
| Templates email | 9 |

---

## Demo : Scenario en 7 Minutes

**Etape 1 - Login Professeur (1 min)**
- Montrer le dashboard prof avec KPIs
- Montrer la liste des cours

**Etape 2 - Creer Seance + QR Code (2 min)**
- Cliquer "Nouvelle seance"
- Generer le QR Code
- Montrer le dashboard live avec HTMX

**Etape 3 - Scan Etudiant (1 min)**
- Ouvrir un autre navigateur (incognito)
- Se connecter en tant qu'etudiant
- Scanner le QR (ou montrer le flux)

**Etape 4 - Validation Secretaire (1 min)**
- Se connecter en secretaire
- Voir les absences en attente
- Approuver une justification

**Etape 5 - Statistiques Admin (1 min)**
- Se connecter en admin
- Montrer les statistiques globales
- Exporter un rapport Excel

**Etape 6 - Montrer le Code (1 min)**
- Ouvrir CODE_MAP.md
- Montrer la structure du projet
- Naviguer vers une fonction demandee

---

## Si le Prof Demande...

| Question | Reponse courte | Fichier a ouvrir |
|----------|---------------|-----------------|
| "Le QR Code ?" | Generation + scan + GPS | `absences/views.py` L1228 |
| "L'eligibilite ?" | Signal auto + seuil configurable | `absences/services.py` L303 |
| "La securite ?" | 7 couches (voir tableau) | `dashboard/decorators.py` |
| "Les tests ?" | 65 tests, pytest, CI GitHub | `tests/` |
| "L'API ?" | DRF, 6 ViewSets, Swagger | `api/views.py` |
| "La base de donnees ?" | PostgreSQL, 12 modeles | `apps/*/models.py` |
