## Summary

Describe clearly what this PR changes and why.

## Type Of Change

- [ ] `feat` (new feature)
- [ ] `fix` (bug fix)
- [ ] `refactor`
- [ ] `test`
- [ ] `docs`
- [ ] `chore`

## Scope

Example: `dashboard`, `absences`, `accounts`, `ci`, etc.

## Checklist

- [ ] Branch is based on `Dev`
- [ ] Commits follow conventional format: `<type>(<scope>): <message>`
- [ ] Local tests pass (`python manage.py test`)
- [ ] Python syntax check done
- [ ] CI checks pass

## Testing Notes

Commands executed and key results:

```bash
python manage.py test
```

```powershell
git ls-files "*.py" | ForEach-Object { python -m py_compile $_ }
```

## Screenshots (if UI changes)

Add before/after screenshots if relevant.

## Related Issue

Closes #
