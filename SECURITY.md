# Security Policy

## Supported Versions

| Version | Supported          |
|---------|--------------------|
| 1.0.x   | :white_check_mark: |

## Reporting a Vulnerability

If you discover a security vulnerability in this project, please report it responsibly.

**Do NOT open a public GitHub issue.**

Instead, send an email to the maintainer with:

- A description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (if any)

We will acknowledge receipt within **48 hours** and aim to release a fix within **7 days** for critical issues.

## Security Measures

This project implements the following security practices:

- **CI/CD security gates**: Bandit (SAST), pip-audit (dependency vulnerabilities), Gitleaks (secret scanning), Trivy (container scanning), CodeQL (semantic analysis)
- **Runtime hardening**: CSRF protection, rate limiting, SRI on CDN assets, CSP headers, HSTS, secure cookies
- **Access control**: Role-based decorators, server-side permission checks, forced password change on first login
- **Audit trail**: All sensitive actions are logged with user, timestamp, and action details
- **Container security**: Non-root user, read-only filesystem, no-new-privileges, minimal base image

## Dependencies

Dependencies are monitored via:
- `pip-audit` in CI (blocks on fixable vulnerabilities)
- GitHub Dependabot (automated PRs for updates)
- Trivy container scanning (OS + library CVEs)
