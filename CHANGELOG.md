# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [1.2.0] - 2026-04-11

### Added
- TOTP 2FA (Google Authenticator / Authy) with QR provisioning and 6-digit verification
- 8 single-use backup codes generated at setup, hashed at rest, one-shot display page
- Backup-code login fallback when the authenticator device is lost
- Admin "Réinitialiser la 2FA" action on user form (audited as CRITIQUE) for lost-device recovery
- Password-gated backup code regeneration from the profile page
- Management commands `seed_demo` and `seed_at_risk` for reproducible demo datasets

### Changed
- Login page: removed non-functional "Se souvenir de moi" checkbox
- Auth shell rebranded (Scholar Nexus mentions removed in favour of UniAbsences)
- Print button on backup codes page uses a nonce'd handler to remain CSP-compliant

### Fixed
- `recalculer_eligibilite()` wrapped in `transaction.atomic()` for notification + audit atomicity
- Missing `select_for_update()` on `toggle_exemption` and `process_justification` race paths

## [1.1.0] - 2026-03-19

### Added
- QR code attendance system with auto-refresh tokens and configurable expiration
- GPS anti-fraud verification: location check within configurable radius, suspicious scan flagging
- QR scan audit logging (QRScanLog) with read-only admin interface and dedicated logs page
- Predictive absence detection: 30/60-day trend analysis, end-of-term rate projection, HIGH/MEDIUM/LOW risk classification
- HTMX real-time attendance marking without page reload
- REST API with DRF: ViewSets for absences, courses, inscriptions, justifications, students
- Swagger/OpenAPI documentation via drf-spectacular
- API analytics, export endpoints, and notification endpoints
- HTML email templates for notifications with async sending and weekly summary
- Password reset functionality with rate limiting
- Session security: inactivity timeout, session expiration, cookie hardening
- Nonce-based Content Security Policy (CSP) across all templates
- Unified session creation workflow with mode selector (manual / QR)
- Conditional exemption with configurable margin for absence threshold
- Trend arrows and combined risk-trend badges on instructor dashboards
- Advanced absence statistics page for admin dashboard

### Changed
- Renamed "Regle des 40%" to "Gestion des seuils d'absence" (configurable threshold)
- Replaced magic strings with Django TextChoices constants
- Split views_admin.py monolith into 4 focused sub-modules
- Upgraded Django 6.0.2 to 6.0.3 (CVE-2026-25673, CVE-2026-25674)

### Fixed
- Race conditions with `select_for_update()` on concurrent justification processing and exemption toggling
- Missing `transaction.atomic()` on multi-step writes (edit_absence, validate_session, toggle_exemption)
- N+1 query optimization with `select_related`/`prefetch_related` across views
- XSS prevention: `escapeHtml()` in enrollment recap modal, innerHTML removal
- SRI integrity hashes on all CDN resources
- HTTP method enforcement (`@require_GET`, `@require_POST`) on all views
- Academic year and EN_COURS status filters on all student/course queries
- Null FK guards on audit logs and messaging templates
- GPS `.strftime()` null guards on optional time fields
- CI test fixes: `secure=True` for SSL redirect compatibility

### Security
- CVE-2026-25673 and CVE-2026-25674 patched (Django 6.0.3)
- QR scan log audit trail for every attendance attempt (success and failure)
- Silenced drf-spectacular cosmetic warnings in deploy checks

## [1.0.0] - 2026-03-11

### Added
- 4-role system: Admin, Secretary, Professor, Student with strict separation of responsibilities
- Attendance tracking: per-session roll call with automatic absence rate calculation
- Justification workflow: student submission, secretary validation/rejection with document upload
- Direct justified absence encoding by secretary
- Automatic blocking at configurable absence threshold (default 40%) with exemption mechanism
- Multi-course and full-level enrollment with prerequisite validation
- Complete audit trail for all sensitive actions
- Internal messaging system between users
- Real-time notification system
- PDF and Excel export for reports and student data
- Session validation/locking mechanism for attendance
- Initial superadmin creation (CLI command + `/setup` page)

### Infrastructure
- Docker Compose stack: Django + Gunicorn, PostgreSQL 16, Nginx, Redis 7
- Let's Encrypt SSL with auto-renewal scripts
- Uptime Kuma monitoring on dedicated port
- Health check endpoint (`/api/health/`)
- Automated entrypoint: DB wait, migrate, collectstatic

### Security
- CI pipeline: Black, isort, Ruff linting + pytest with PostgreSQL/Redis services
- Security scanning: Bandit (SAST), pip-audit, Gitleaks, Trivy, CodeQL
- SRI integrity hashes on all CDN resources
- Rate limiting on login and health check endpoints
- Non-root container user, read-only filesystem, no-new-privileges
- HSTS, CSP, secure cookies, CSRF protection

### Fixed
- 80+ bugs resolved across 7 audit batches (see commit history for details)
- Race conditions with `select_for_update()` on concurrent operations
- Missing `transaction.atomic()` on multi-step writes
- Academic year filters on all student/course queries
- HTTP method enforcement (`@require_GET`, `@require_POST`) on all views
- XSS prevention in enrollment recap modal
- Audit log injection via control character sanitization
