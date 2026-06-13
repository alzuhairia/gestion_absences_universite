# Journal des modifications

Tous les changements notables de ce projet sont documentés dans ce fichier.

Le format est inspiré de [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/).

## [1.2.0] - 2026-04-11

### Ajouté
- 2FA TOTP (Google Authenticator / Authy) avec provisionnement QR et vérification à 6 chiffres
- 8 codes de secours à usage unique générés à l'activation, hachés au repos, page d'affichage unique
- Connexion de repli par code de secours en cas de perte de l'appareil d'authentification
- Action admin « Réinitialiser la 2FA » sur la fiche utilisateur (auditée en CRITIQUE) pour la récupération en cas de perte d'appareil
- Régénération des codes de secours protégée par mot de passe depuis la page de profil
- Commandes de gestion `seed_demo` et `seed_at_risk` pour des jeux de données de démo reproductibles

### Modifié
- Page de connexion : retrait de la case « Se souvenir de moi » non fonctionnelle
- Coquille d'authentification rebrandée (mentions Scholar Nexus retirées au profit d'UniAbsences)
- Le bouton d'impression sur la page des codes de secours utilise un handler nonce pour rester conforme à la CSP

### Corrigé
- `recalculer_eligibilite()` encapsulé dans `transaction.atomic()` pour l'atomicité notification + audit
- `select_for_update()` manquant sur les chemins de course de `toggle_exemption` et `process_justification`

## [1.1.0] - 2026-03-19

### Ajouté
- Système de présence par QR code avec rotation automatique des tokens et expiration configurable
- Vérification GPS anti-fraude : contrôle de localisation dans un rayon configurable, marquage des scans suspects
- Journal d'audit des scans QR (QRScanLog) avec interface admin en lecture seule et page de logs dédiée
- Détection prédictive des absences : analyse de tendance sur 30/60 jours, projection du taux en fin de semestre, classification de risque HIGH/MEDIUM/LOW
- Marquage de présence en temps réel via HTMX sans rechargement de page
- API REST avec DRF : ViewSets pour absences, cours, inscriptions, justificatifs, étudiants
- Documentation Swagger/OpenAPI via drf-spectacular
- Endpoints d'analytics API, d'export et de notifications
- Templates d'emails HTML pour les notifications avec envoi asynchrone et résumé hebdomadaire
- Fonctionnalité de réinitialisation de mot de passe avec rate limiting
- Sécurité de session : timeout d'inactivité, expiration de session, durcissement des cookies
- Content Security Policy (CSP) basée sur nonce sur tous les templates
- Workflow unifié de création de séance avec sélecteur de mode (manuel / QR)
- Exemption conditionnelle avec marge configurable pour le seuil d'absences
- Flèches de tendance et badges combinés risque-tendance sur les tableaux de bord professeurs
- Page de statistiques d'absences avancées pour le tableau de bord admin

### Modifié
- Renommé « Règle des 40% » en « Gestion des seuils d'absence » (seuil configurable)
- Remplacé les chaînes magiques par des constantes Django TextChoices
- Découpé le monolithe views_admin.py en 4 sous-modules ciblés
- Mise à jour Django 6.0.2 vers 6.0.3 (CVE-2026-25673, CVE-2026-25674)

### Corrigé
- Conditions de course avec `select_for_update()` sur le traitement concurrent des justificatifs et le basculement d'exemption
- `transaction.atomic()` manquant sur les écritures multi-étapes (edit_absence, validate_session, toggle_exemption)
- Optimisation des requêtes N+1 avec `select_related`/`prefetch_related` dans les vues
- Prévention XSS : `escapeHtml()` dans la modale de récapitulatif d'inscription, suppression d'innerHTML
- Hashes d'intégrité SRI sur toutes les ressources CDN
- Application des méthodes HTTP (`@require_GET`, `@require_POST`) sur toutes les vues
- Filtres d'année académique et statut EN_COURS sur toutes les requêtes étudiants/cours
- Gardes pour FK nulles sur les logs d'audit et les templates de messagerie
- Gardes nulles sur `.strftime()` GPS pour les champs horaires optionnels
- Corrections de tests CI : `secure=True` pour la compatibilité avec la redirection SSL

### Sécurité
- CVE-2026-25673 et CVE-2026-25674 corrigées (Django 6.0.3)
- Piste d'audit des scans QR pour chaque tentative de présence (succès et échec)
- Avertissements cosmétiques de drf-spectacular silencés dans les contrôles de déploiement

## [1.0.0] - 2026-03-11

### Ajouté
- Système à 4 rôles : Admin, Secrétariat, Professeur, Étudiant avec séparation stricte des responsabilités
- Suivi des présences : appel par séance avec calcul automatique du taux d'absence
- Workflow de justification : soumission étudiante, validation/refus par le secrétariat avec téléversement de document
- Encodage direct d'absences justifiées par le secrétariat
- Blocage automatique au seuil d'absences configurable (40% par défaut) avec mécanisme d'exemption
- Inscription multi-cours et inscription complète d'année avec validation des prérequis
- Piste d'audit complète pour toutes les actions sensibles
- Système de messagerie interne entre utilisateurs
- Système de notifications en temps réel
- Export PDF et Excel pour les rapports et données étudiantes
- Mécanisme de validation/verrouillage de séance pour les présences
- Création initiale du super-administrateur (commande CLI + page `/setup`)

### Infrastructure
- Stack Docker Compose : Django + Gunicorn, PostgreSQL 16, Nginx, Redis 7
- SSL Let's Encrypt avec scripts d'auto-renouvellement
- Monitoring Uptime Kuma sur port dédié
- Endpoint de health check (`/api/health/`)
- Entrypoint automatisé : attente de la base, migrate, collectstatic

### Sécurité
- Pipeline CI : linting Black, isort, Ruff + pytest avec services PostgreSQL/Redis
- Scan de sécurité : Bandit (SAST), pip-audit, Gitleaks, Trivy, CodeQL
- Hashes d'intégrité SRI sur toutes les ressources CDN
- Rate limiting sur les endpoints de connexion et de health check
- Utilisateur de conteneur non-root, système de fichiers en lecture seule, no-new-privileges
- HSTS, CSP, cookies sécurisés, protection CSRF

### Corrigé
- Plus de 80 bugs résolus à travers 7 lots d'audit (voir l'historique des commits pour les détails)
- Conditions de course avec `select_for_update()` sur les opérations concurrentes
- `transaction.atomic()` manquant sur les écritures multi-étapes
- Filtres d'année académique sur toutes les requêtes étudiants/cours
- Application des méthodes HTTP (`@require_GET`, `@require_POST`) sur toutes les vues
- Prévention XSS dans la modale de récapitulatif d'inscription
- Injection dans les logs d'audit via la sanitization des caractères de contrôle
