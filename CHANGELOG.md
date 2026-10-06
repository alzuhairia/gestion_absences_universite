# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [1.6.3] - 2026-10-07

Every notification e-mail now uses the styled HTML template.

### Changed
- The exemption e-mail was the last notification still sent as plain text: it now uses `build_exemption_granted_email()` and the `emails/exemption_granted.html` template like the others, and tells the student their new effective absence threshold

### Added
- `send_weekly_summary --to EMAIL` sends a preview of the weekly secretariat summary (same data and template) to one address only; secretaries receive nothing

## [1.6.2] - 2026-10-07

Security release for the shared reverse proxy.

### Security
- Dockhand (Docker management UI, no login of its own, holds the Docker socket) was reachable from the Internet without authentication since nginx started serving the co-hosted sites on 443. It is back behind tinyauth: every request goes through `auth_request` to tinyauth, and the browser is sent to the login page without a valid session
- HTTPS requests for unknown host names (bare IP, stray DNS records, scanners) are refused at the TLS handshake by a catch-all `default_server` (`ssl_reject_handshake`) instead of reaching Django, which logged a DisallowedHost error for each

### Added
- `tinyauth.infotechno.eu` (login portal) and `it-tools.infotechno.eu` (behind tinyauth) served by nginx on 443 with their own Let's Encrypt certificates, renewed by `scripts/renew-ssl.sh` like the others
- `nginx/snippets/tinyauth-auth.conf`: shared tinyauth forward-auth locations, included by every protected server block

### Fixed
- CI quality gate checked no file on multi-file pushes: the changed-files list was escaped into a single bogus path; it is now read raw through an environment variable

## [1.6.1] - 2026-10-06

Bug fixes and code health: absence durations no longer crash a roll call,
the codebase is type-clean and uniformly formatted, and CI checks are
reliable again.

### Fixed
- Roll call (manual and HTMX): a partial absence with an empty, zero, too long or session-length duration fell back to the full session but kept type PARTIEL, which the model rejects, so the whole roll call failed with a 500. The fallback now records a full ABSENT
- Absence durations typed as `nan` or `inf` crashed the roll call and the secretariat edit page with a 500; they are now rejected like any invalid value
- Test suite no longer uses the production Redis (`cache.clear()` issued a FLUSHDB against it); every test gets an in-memory cache
- CI quality gate silently checked nothing on multi-commit pushes (shallow checkout); it now fetches the full history

### Changed
- Durations accept a comma as decimal separator (`1,5` as well as `1.5`)
- Weekly secretariat summary scheduled on the server (Mondays 07:00)
- Codebase formatted with Black 26.10 and isort 9.0 (one pure-formatting commit, listed in `.git-blame-ignore-revs`); CI and pre-commit pin the same black/isort/ruff versions
- Pyright/Pylance report 0 errors: `pyrightconfig.json`, `djangorestframework-types` in `requirements-dev.txt`, model type declarations (TYPE_CHECKING only), typed helpers for request users and form querysets
- 22 unused imports removed

## [1.6.0] - 2026-10-06

Faster roll calls and durable logs: e-mails no longer slow down requests,
logs survive restarts, and the e-mail history has a retention period.

### Added
- `purge_email_history` management command: deletes `EmailEnvoi` rows older than N days (default 365), meant for a weekly cron
- `EMAIL_ASYNC` setting (default on) to turn background sending off if needed

### Changed
- Notification e-mails are sent in the background through a bounded thread pool, once the current transaction commits: closing a roll call with 10 absent students no longer waits ~10 s for SMTP, and a rolled-back operation sends nothing. Logging and the `EmailEnvoi` record happen after the real send, so the history stays exact
- The weekly secretariat summary stays synchronous so its "sent" count is real
- `/app/logs` is now the `logs_volume` named volume instead of a tmpfs: `django.log` survives container restarts and deployments (rotation unchanged, 5 MB x 3)

### Fixed
- `/audits/logs/` always showed an empty list (the template read a variable the view never passed); it now redirects to the secretariat audit log page, keeping the query string

## [1.5.0] - 2026-10-06

E-mail proof of sending: every notification e-mail is now recorded and can be
shown on the website, to the secretariat and to the student concerned.

### Added
- `EmailEnvoi` history: every e-mail handed to the mail server (or failing) is stored with recipient, subject, status and date; the body is never stored (no OTP codes in the database)
- Secretariat page "Historique des e-mails" (Audit section): all sends, with search by name / e-mail / subject, status filter and date range
- Student page "Mes E-mails": each student sees only the e-mails sent to them, with a reminder to check the spam folder
- Read-only `EmailEnvoi` view in the Django admin (no add, change or delete)
- `requirements-dev.txt` with `django-types`, so Pylance/Pyright understand Django models (not installed in the Docker image)

### Changed
- Type annotations for Pyright: `User.objects` typed as `UserManager`, FK columns `id_cours_id` / `id_seance_id` declared; no runtime change

### Notes
- `/app/logs` was a tmpfs at this release, so `django.log` was lost on every container restart (fixed in 1.6.0); the `email_envoi` table is the durable record of sends

## [1.4.0] - 2026-10-06

Observability and infrastructure release: e-mail sends are now visible in the
logs, and the shared nginx serves the other sites co-hosted on the server.

### Added
- Every e-mail send attempt is logged at INFO: sent (sync and async), skipped (no address / inactive user) and dedup skips; previously only failures were logged, so a successful send left no trace. Only the recipient and subject are logged, never the body (no OTP codes in logs)

### Changed
- nginx terminates TLS for the other sites co-hosted on the server (absences stays the default server) and joins the external `frontend` network
- Dedup skip and dedup race messages raised from DEBUG to INFO so they show up in production

### Fixed
- `DB_NAME` fallback aligned to `unabsences_db` in `settings.py`, `entrypoint.sh` and `.env.example` (the entrypoint was waiting for a database that does not exist)
- SSL renewal renews all co-hosted certificates and reloads nginx, which reads them straight from `/etc/letsencrypt/live`

## [1.3.0] - 2026-09-28

Attendance anti-fraud release: trusted devices, anomaly detection, and a human
review loop (secretariat + professor) for suspicious QR scans. The system does
not claim to prove who holds the phone; it makes proxy attendance costly,
detected and traceable, and leaves the final decision to people.

### Added
- Student device binding: signed, HttpOnly device cookie (only its SHA-256 hash is stored), up to 2 approved devices per student, PENDING / APPROVED / REVOKED lifecycle, "Mes appareils" page
- New-device verification by e-mail OTP (6 digits, hashed, 10 min, 5 attempts per code), with an HTML template
- Secretariat device screen: approve / revoke / reactivate, plus a per-student view (search by e-mail or name) listing all devices, approved ones included, to revoke a lost phone
- Server-side GPS enforcement for QR sessions (`qr_gps_required`, on by default): the professor can no longer untick location checking
- Attendance anomaly engine (detective only, never blocks an approved device), with a risk score (suspicious from 30): `same_device_same_seance` (retroactively flags the first scan too), `multi_account_device`, `recently_approved`, `device_churn`, `geo_velocity`, `gps_too_perfect`, `new_ip`, `low_gps_accuracy`, `desktop_scan`
- Anomaly review queue for the secretariat: to review / confirmed / false positive, with reviewer, date and note, all audited
- Professor visual check on the live QR dashboard: "Vu en classe" / "Pas présent"; an invalidated attendance is kept as evidence (never deleted) and counted absent at finalization
- Device security e-mails: explicit anti-sharing warning with device, IP and time in the OTP e-mail; notification on every device approval or revocation
- "Reprendre la séance" banner to resume an active QR or manual roll call
- Admin: bulk course deletion, force delete for users with linked data, missing department delete button
- `seed_demo` auto-provisions faculties, departments and the academic year; `seed_at_risk` gains `--year-label`
- `.dockerignore`: `.env`, `.git`, local virtualenv and database backups are no longer copied into the image (image 414 MB → 294 MB)

### Changed
- Every new device now requires the OTP, including a student's first one (it was auto-approved)
- Only an approved device can revoke an approved device; a lost device goes through the secretariat
- OTP sending capped per user (3/hour, 10/day) and verification capped (10/hour); a refused resend no longer resets the attempt counter
- `multi_account_device` only counts another account that approved the device and used it within 30 days (no more lifelong flag on a shared family PC)
- `new_device` replaced by `recently_approved`, based on the approval date (pre-enrolling a device the day before no longer hides it)
- Rejected QR scans now record the device hash, so a "rejected → OTP → validated" sequence can be traced
- Native `alert()` / `confirm()` replaced by Bootstrap modals and inline alerts in admin and enrollment screens
- Web container healthcheck uses a Python probe (curl removed from the runtime image); build tools removed from the runtime image

### Fixed
- QR: missing GPS reference position, expiration and countdown desync
- QR finalization now e-mails students marked absent
- OTP attempt counting is atomic (concurrent requests cannot exceed 5 guesses) and a code superseded by a resend is rejected
- Stale `SystemSettings` cache purged on every deploy
- Password change rejects reusing the old password (server-side)
- Enrollment messages clarified; cross-level full enrollment blocked
- Auth templates flex layout, e-mail gradient fallback colour, admin sidebar user name, CSP `connect-src` for CDN source maps

### Security
- Dependencies upgraded to resolve known CVEs and pip-audit findings (Django 6.0.8, Pillow 12.3.0, idna 3.15, setuptools); Windows-only packages removed
- CI: daily apt layer cache bust so Trivy picks up Debian security patches; SARIF upload permissions; actions updated to v7

### Upgrade notes
- Migrations (additive only): `accounts.0011`, `absences.0021`–`0024`, `dashboard.0004`–`0006` — applied automatically by `entrypoint.sh`
- Students without a device will be asked for an e-mail OTP at their next scan: SMTP must be working
- Configure the establishment GPS coordinates and a realistic radius (e.g. 300 m): with GPS enforced, a QR cannot be generated without a reference position
- Runtime configuration must come from `env_file` / environment variables: `.env` is no longer baked into the image

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
