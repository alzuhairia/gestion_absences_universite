"""
Validateur de mot de passe dynamique pour le système universitaire de gestion des absences UniAbsences.

Les exigences de complexité du mot de passe dans UniAbsences ne sont pas
codées en dur — elles sont configurées à l'exécution via le modèle
d'administration ``SystemSettings``. Ce module fournit un validateur de
mot de passe compatible Django qui lit ces paramètres et les applique
de manière cohérente à travers les flux de création de compte, changement
de mot de passe et réinitialisation de mot de passe.

Responsabilités :
  - Lire les règles de mot de passe actives depuis ``SystemSettings``
    (longueur minimale, exigences de classes de caractères).
  - Lever ``ValidationError`` avec un message descriptif pour chaque règle
    non satisfaite.
  - Se dégrader gracieusement quand la base de données n'est pas encore
    disponible (par ex. lors des migrations ou de la configuration initiale
    ``manage.py``), afin que le système puisse démarrer sans erreurs.

Fait partie du système de comptes UniAbsences.
"""

import re

from django.core.exceptions import ValidationError
from django.db import OperationalError, ProgrammingError
from django.utils.translation import gettext as _


class SystemSettingsPasswordValidator:
    """
    Validateur de mot de passe Django qui applique les règles stockées dans ``SystemSettings``.

    Cette classe suit le protocole Django ``AUTH_PASSWORD_VALIDATORS`` : elle
    expose une méthode ``validate`` appelée par ``validate_password`` et une
    méthode ``get_help_text`` utilisée pour afficher des indications dans les
    formulaires.

    Le validateur ignore intentionnellement la validation (passage silencieux)
    lorsque la table ``SystemSettings`` n'existe pas encore — cela évite de
    faire planter ``manage.py migrate`` ou ``manage.py createsuperadmin``
    avant que la configuration initiale de la base de données ne soit terminée.
    """

    def validate(self, password, user=None):
        """
        Valide ``password`` contre les règles ``SystemSettings`` actives.

        Collecte toutes les contraintes échouées dans une liste et lève une
        seule ``ValidationError`` contenant chaque message d'échec. Cela
        permet aux formulaires d'afficher tous les problèmes en une fois
        plutôt qu'un à la fois.

        Parameters:
            password (str): Le candidat mot de passe en texte clair à valider.
            user: L'instance utilisateur (optionnelle, inutilisée — présente
                  pour la compatibilité Django).

        Raises:
            ValidationError: Si une ou plusieurs règles de mot de passe sont violées.

        Effets de bord : aucun (accès en lecture seule à la base via ``SystemSettings``).
        """
        try:
            from apps.dashboard.models import SystemSettings

            settings = SystemSettings.get_settings()
        except (OperationalError, ProgrammingError, ImportError):
            # La table SystemSettings n'existe pas encore (migration fraîche)
            # ou l'app dashboard n'a pas été installée. Ignorer la validation
            # silencieusement pour ne pas bloquer le processus de bootstrap.
            return

        errors = []

        # Vérification de la longueur minimale — ignorer si le paramètre vaut 0 / None (désactivé).
        if (
            settings.password_min_length
            and len(password) < settings.password_min_length
        ):
            errors.append(
                _("Le mot de passe doit contenir au moins %(min_length)d caractères.")
                % {"min_length": settings.password_min_length}
            )

        # Vérifications de classes de caractères — chacune est configurable indépendamment.
        if settings.password_require_uppercase and not re.search(r"[A-Z]", password):
            errors.append(_("Le mot de passe doit contenir au moins une majuscule."))

        if settings.password_require_lowercase and not re.search(r"[a-z]", password):
            errors.append(_("Le mot de passe doit contenir au moins une minuscule."))

        if settings.password_require_numbers and not re.search(r"[0-9]", password):
            errors.append(_("Le mot de passe doit contenir au moins un chiffre."))

        # Un "caractère spécial" est tout ce qui n'est ni une lettre ni un chiffre.
        if settings.password_require_special and not re.search(
            r"[^A-Za-z0-9]", password
        ):
            errors.append(
                _("Le mot de passe doit contenir au moins un caractère spécial.")
            )

        if errors:
            raise ValidationError(errors)

    def get_help_text(self):
        """
        Retourne une brève description de la politique de mot de passe affichée dans les formulaires HTML.

        Returns:
            str: Chaîne d'indication traduite.
        """
        return _(
            "Le mot de passe doit respecter les règles définies dans les paramètres système."
        )
