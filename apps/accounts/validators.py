import re
from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _


class SystemSettingsPasswordValidator:
    """
    Enforce password rules from SystemSettings when available.
    Falls back silently if settings are unavailable (e.g., during migrations).
    """

    def validate(self, password, user=None):
        try:
            from apps.dashboard.models import SystemSettings
            settings = SystemSettings.get_settings()
        except Exception:
            return

        errors = []

        if settings.password_min_length and len(password) < settings.password_min_length:
            errors.append(
                _("Le mot de passe doit contenir au moins %(min_length)d caractères.")
                % {"min_length": settings.password_min_length}
            )

        if settings.password_require_uppercase and not re.search(r"[A-Z]", password):
            errors.append(_("Le mot de passe doit contenir au moins une majuscule."))

        if settings.password_require_lowercase and not re.search(r"[a-z]", password):
            errors.append(_("Le mot de passe doit contenir au moins une minuscule."))

        if settings.password_require_numbers and not re.search(r"[0-9]", password):
            errors.append(_("Le mot de passe doit contenir au moins un chiffre."))

        if settings.password_require_special and not re.search(r"[^A-Za-z0-9]", password):
            errors.append(_("Le mot de passe doit contenir au moins un caractère spécial."))

        if errors:
            raise ValidationError(errors)

    def get_help_text(self):
        return _(
            "Le mot de passe doit respecter les règles définies dans les paramètres système."
        )
