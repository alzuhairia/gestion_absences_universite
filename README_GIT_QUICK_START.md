# Git Quick Start (Team)

Guide rapide pour appliquer un workflow Git/GitHub propre sur ce projet.

## 1) Setup local (une seule fois)

```powershell
powershell -ExecutionPolicy Bypass -File scripts/setup/setup_git_workflow.ps1
git config --get core.hooksPath
git config --get commit.template
```

## 2) Sauvegarder le travail en cours (si besoin)

```powershell
git status --short
if ((git status --porcelain).Length -gt 0) {
  git stash push -u -m "WIP: auto-before-sync $(Get-Date -Format 'yyyy-MM-dd_HH-mm')"
}
git stash list
```

## 3) Synchroniser `Dev`

```powershell
git checkout Dev
git pull --ff-only origin Dev
```

## 4) Creer une branche feature

```powershell
$FEATURE="feature/nom-de-la-feature"
git checkout -b $FEATURE
```

## 5) Travailler et faire des commits atomiques

Format commit:

```text
<type>(<scope>): <message clair>
```

Types autorises:

```text
feat, fix, style, docs, refactor, test, chore
```

Exemples:

```text
feat(dashboard): add caching for SystemSettings.get_settings()
fix(admin): pagination on admin_faculties and admin_departments
docs(api): add docstrings for endpoints
```

Commandes:

```powershell
git add <fichiers-pertinents>
git commit -m "fix(scope): message clair"
```

## 6) Tests avant push (obligatoire)

```powershell
python manage.py test
git ls-files "*.py" | ForEach-Object { python -m py_compile $_ }
```

Optionnel qualite:

```powershell
black --check .
isort --profile black --check-only .
ruff check .
```

## 7) Push de la feature

```powershell
git push -u origin $FEATURE
```

## 8) Ouvrir PR vers `Dev`

- Base: `Dev`
- Inclure: description, tests executes, screenshots (si UI), lien issue
- Ajouter labels: `feature`, `bugfix`, `docs`, `ci`, `refactor`, `test`, `chore`, `security`

Si `gh` est installe:

```powershell
$GH="C:\Program Files\GitHub CLI\gh.exe"
& $GH pr create --base Dev --head $FEATURE --title "feat(scope): titre PR"
```

## 9) Apres merge PR

```powershell
git checkout Dev
git pull --ff-only origin Dev
git branch -d $FEATURE
git stash pop  # seulement si stash cree au debut
```

## 10) Release production

```powershell
git checkout main
git pull --ff-only origin main
git merge --no-ff Dev -m "chore(release): merge Dev into main"
git push origin main
git checkout Dev
```
