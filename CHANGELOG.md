# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

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
