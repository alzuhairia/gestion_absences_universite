<p align="center">
  <h1 align="center">UniAbsences</h1>
  <p align="center">
    Plateforme de gestion des absences universitaires
    <br />
    <em>Django &middot; PostgreSQL &middot; Docker &middot; Nginx</em>
  </p>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.13-blue?logo=python&logoColor=white" alt="Python 3.13" />
  <img src="https://img.shields.io/badge/django-6.0.3-green?logo=django&logoColor=white" alt="Django 6.0.3" />
  <img src="https://img.shields.io/badge/PostgreSQL-16-336791?logo=postgresql&logoColor=white" alt="PostgreSQL 16" />
  <img src="https://img.shields.io/badge/docker-ready-2496ED?logo=docker&logoColor=white" alt="Docker Ready" />
  <a href="https://github.com/alzuhairia/gestion_absences_universite/actions/workflows/ci.yml">
    <img src="https://github.com/alzuhairia/gestion_absences_universite/actions/workflows/ci.yml/badge.svg?branch=Dev" alt="CI" />
  </a>
</p>

---

## Apercu

UniAbsences automatise le suivi des presences et absences dans un contexte universitaire : saisie par les professeurs, justificatifs par les etudiants, validation par le secretariat, configuration par l'administrateur.

**Fonctionnalites cles :**

- 4 roles distincts (Admin, Secretariat, Professeur, Etudiant) avec separation stricte des responsabilites
- Saisie des presences/absences par seance avec calcul automatique des taux
- Presence par QR code avec verification GPS anti-fraude
- Detection predictive des etudiants a risque (projection de fin de semestre)
- Marquage en temps reel via HTMX (sans rechargement de page)
- Workflow complet de justificatifs (soumission, validation, refus)
- Blocage automatique au seuil d'absences configurable (avec exemptions)
- Authentification a deux facteurs (TOTP) avec 8 codes de secours a usage unique et reinitialisation admin en cas de perte du telephone
- API REST complete (DRF + documentation Swagger/OpenAPI)
- Notifications par email (HTML templates, envoi asynchrone, resume hebdomadaire)
- Reinitialisation de mot de passe avec rate limiting
- Journal d'audit complet de toutes les actions sensibles
- Messagerie interne et notifications
- Export PDF / Excel

## Captures d'ecran

<details>
<summary>Cliquer pour voir les captures d'ecran</summary>

| Vue | Apercu |
|-----|--------|
| Page de connexion | ![Login](docs/screenshots/login.png) |
| Dashboard Admin | ![Admin](docs/screenshots/dashboard-admin.png) |
| Dashboard Professeur | ![Professor](docs/screenshots/dashboard-professor.png) |
| Dashboard Etudiant | ![Student](docs/screenshots/dashboard-student.png) |
| Saisie des absences | ![Attendance](docs/screenshots/mark-absence.png) |
| Gestion des justificatifs | ![Justifications](docs/screenshots/justifications.png) |

</details>

> Pour ajouter des captures : placer les images PNG dans `docs/screenshots/` avec les noms ci-dessus.

## Architecture

```
                    Client (navigateur)
                          |
                     [ Nginx ]          port 80 / 443
                     SSL, static,       reverse proxy
                     media, gzip
                          |
                  [ Gunicorn + Django ] port 8000
                     logique metier,
                     auth, API
                     /           \
            [ PostgreSQL 16 ]   [ Redis 7 ]
              donnees             cache, rate-limit
```

| Service   | Image                 | Role                                |
|-----------|-----------------------|-------------------------------------|
| `web`     | `python:3.13-slim`    | Application Django (Gunicorn)       |
| `db`      | `postgres:16-alpine`  | Base de donnees                     |
| `nginx`   | `nginx:alpine`        | Reverse proxy, fichiers statiques   |
| `redis`   | `redis:7-alpine`      | Cache distribue, rate limiting      |
| `monitor` | `louislam/uptime-kuma`| Monitoring de disponibilite         |

## Structure du projet

```
apps/
  accounts/           Utilisateurs et authentification
  academics/          Facultes, Departements, Cours
  academic_sessions/  Annees academiques, Seances
  enrollments/        Inscriptions etudiants
  absences/           Absences et justificatifs
  dashboard/          Tableaux de bord par role
  audits/             Journal d'audit
  messaging/          Messagerie interne
  notifications/      Notifications
  health/             Endpoint de health check
```

## Demarrage rapide

### Prerequis

- [Docker](https://docs.docker.com/get-docker/) >= 20.10
- [Docker Compose](https://docs.docker.com/compose/) >= 2.0

### 1. Cloner le projet

```bash
git clone https://github.com/alzuhairia/gestion_absences_universite.git
cd gestion_absences_universite
```

### 2. Configurer l'environnement

```bash
cp .env.example .env
# Editer .env : renseigner SECRET_KEY, DB_PASSWORD, ALLOWED_HOSTS, etc.
```

> Generer une `SECRET_KEY` :
> ```bash
> python3 -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
> ```

### 3. Lancer les services

```bash
docker compose up -d --build
```

### 4. Creer un administrateur

```bash
docker compose exec web python manage.py createsuperuser
```

L'application est accessible sur `http://localhost` (ou votre domaine configure).

## Developpement local (sans Docker)

```bash
python -m venv env && source env/bin/activate   # Windows: env\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                             # Configurer pour SQLite/PostgreSQL local
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

## Tests et qualite

```bash
# Tests unitaires
python -m pytest --tb=short -q

# Linting
black --check .
isort --profile black --check-only .
ruff check --select E9,F63,F7,F82 .
```

La CI GitHub Actions execute automatiquement :
- Linting (Black, isort, Ruff)
- Tests avec PostgreSQL + Redis
- Audit de securite (Bandit, pip-audit, Gitleaks)
- Analyse CodeQL
- Build Docker + scan Trivy

## Documentation

| Document | Description |
|----------|-------------|
| [`docs/deployment.md`](docs/deployment.md) | Guide complet de deploiement VPS |
| [`docs/docker-setup.md`](docs/docker-setup.md) | Configuration Docker detaillee |
| [`docs/monitoring.md`](docs/monitoring.md) | Monitoring avec Uptime Kuma |
| [`CONTRIBUTING.md`](CONTRIBUTING.md) | Guide de contribution et conventions Git |
| [`.env.example`](.env.example) | Variables d'environnement documentees |

## Stack technique

| Categorie      | Technologies                                         |
|----------------|------------------------------------------------------|
| Backend        | Python 3.13, Django 6.0.3, DRF, Gunicorn             |
| Base de donnees| PostgreSQL 16, Redis 7                               |
| Frontend       | Bootstrap 5.3, FontAwesome 6, HTMX, JavaScript       |
| Infrastructure | Docker, Nginx, Let's Encrypt                         |
| CI/CD          | GitHub Actions (lint, test, security, Docker, CodeQL) |
| Monitoring     | Uptime Kuma, health check endpoint                   |
| Securite       | Bandit, pip-audit, Trivy, Gitleaks, SRI, CSP, HSTS   |

## Licence

Ce projet est distribue sous licence [MIT](LICENSE).

---

<sub>Derniere mise a jour : Avril 2026</sub>
