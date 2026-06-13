# Guide de contribution

Ce projet suit un workflow Git simple et strict afin que le dépôt reste propre et facile à relire.

## 1. Stratégie de branches

- `Dev` : branche d'intégration pour le travail de développement validé.
- `main` : branche de production, doit rester stable.
- `feature/*` : une branche par fonctionnalité ou correctif.

Exemples :

- `feature/cache-systemsettings`
- `feature/pagination-admin`
- `feature/fix-trivy-docker`

## 2. Règles de commit

Chaque commit doit contenir un seul changement logique.

Utilisez le style Conventional Commit :

```text
<type>(<scope>): <message court>
```

Exemples :

- `feat(dashboard): ajouter le cache sur SystemSettings.get_settings()`
- `fix(admin): ajouter la pagination sur les facultés et départements`
- `style(settings): mettre à jour la langue et le fuseau horaire par défaut`
- `docs(api): ajouter les docstrings de get_departments et health_check`

Valeurs autorisées pour `type` :

- `feat`
- `fix`
- `style`
- `docs`
- `refactor`
- `test`
- `chore`

## 3. Mettre de côté le travail en cours

Avant de changer de branche ou de récupérer des modifications :

```bash
git add -A
git stash push -m "WIP: description courte"
```

Restaurer plus tard :

```bash
git stash pop
```

## 4. Synchroniser avec Dev

```bash
git checkout Dev
git pull origin Dev
```

Puis revenir à votre branche de fonctionnalité et continuer.

## 5. Workflow d'une fonctionnalité

Créer une branche à partir de `Dev` :

```bash
git checkout Dev
git pull origin Dev
git checkout -b feature/<nom-fonctionnalite>
```

Après le codage et les tests :

```bash
git push -u origin feature/<nom-fonctionnalite>
```

Ouvrir une PR vers `Dev`.

## 6. Qualité d'une PR

Chaque PR doit inclure :

- un résumé clair des changements
- les notes de test (ce qui a été exécuté)
- des captures d'écran pour les changements d'interface
- un lien vers une issue liée si disponible

## 7. Utilisation des issues et des labels

- Utiliser les Issues GitHub pour les tâches et bugs.
- Lier les PRs aux Issues pour la traçabilité.
- Utiliser les labels (`feature`, `bugfix`, `docs`, `ci`, etc.).

## 8. Vérifications locales avant commit

Obligatoire :

```bash
python -m pytest --tb=short -q
```

Vérifications de qualité optionnelles :

```bash
black --check .
isort --profile black --check-only .
ruff check .
```

## 9. Résumé pratique

- Stash si nécessaire -> Pull -> Pop stash
- Une branche par fonctionnalité/correctif
- Commits atomiques au format conventionnel
- Push -> PR -> Merge dans `Dev`
- Exécuter les tests avant chaque push
