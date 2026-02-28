# Contributing Guide

This project follows a simple and strict Git workflow so the repository stays clean and easy to review.

## 1. Branch Strategy

- `Dev`: integration branch for validated development work.
- `main`: production branch, must stay stable.
- `feature/*`: one branch per feature or fix.

Examples:

- `feature/cache-systemsettings`
- `feature/pagination-admin`
- `feature/fix-trivy-docker`

## 2. Commit Rules

Each commit should contain one logical change only.

Use Conventional Commit style:

```text
<type>(<scope>): <short message>
```

Examples:

- `feat(dashboard): add caching for SystemSettings.get_settings()`
- `fix(admin): add pagination on faculties and departments`
- `style(settings): update language and timezone defaults`
- `docs(api): add docstrings for get_departments and health_check`

Allowed commit `type` values:

- `feat`
- `fix`
- `style`
- `docs`
- `refactor`
- `test`
- `chore`

## 3. Save Work In Progress

Before switching branch or pulling changes:

```bash
git add -A
git stash push -m "WIP: short description"
```

Restore later:

```bash
git stash pop
```

## 4. Sync With Dev

```bash
git checkout Dev
git pull origin Dev
```

Then return to your feature branch and continue.

## 5. Feature Workflow

Create branch from `Dev`:

```bash
git checkout Dev
git pull origin Dev
git checkout -b feature/<feature-name>
```

After coding and tests:

```bash
git push -u origin feature/<feature-name>
```

Open a PR to `Dev`.

## 6. PR Quality

Each PR should include:

- clear summary of changes
- testing notes (what was run)
- screenshots for UI changes
- related issue link if available

## 7. Issue and Label Usage

- Use GitHub Issues for tasks and bugs.
- Link PRs to Issues for traceability.
- Use labels (`feature`, `bugfix`, `docs`, `ci`, etc.).

## 8. Local Checks Before Commit

Required:

```bash
python manage.py test
```

PowerShell syntax for Python syntax check:

```powershell
git ls-files "*.py" | ForEach-Object { python -m py_compile $_ }
```

Optional quality checks:

```bash
black --check .
isort --profile black --check-only .
ruff check .
```

## 9. One-Time Local Setup (Recommended)

Run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/setup/setup_git_workflow.ps1
```

This configures:

- local commit template (`.gitmessage.txt`)
- local Git hook path (`.githooks`)
- commit message validation hook (`.githooks/commit-msg`)

## 10. Practical Summary

- Stash if needed -> Pull -> Pop stash
- One branch per feature/fix
- Atomic conventional commits
- Push -> PR -> Merge into `Dev`
- Run tests before every push
