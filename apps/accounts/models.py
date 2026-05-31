"""
Hub de réexport public des modèles pour l'application accounts d'UniAbsences.

Tout code externe (vues, serializers, signaux, commandes de management, etc.)
doit importer les modèles depuis ce module plutôt que depuis les sous-modules
individuels. Cela maintient une API publique stable même si l'organisation
interne des fichiers est réorganisée.

Mapping des sous-modules
------------------------
models_user.py
    ``UserManager`` et ``User`` — AUTH_USER_MODEL de Django.
    Définit l'utilisateur personnalisé basé sur l'email avec énumération de
    rôles et champs d'authentification à deux facteurs TOTP.

models_security.py
    ``UserSession`` — suit les sessions de navigateur actives par utilisateur
    et applique la limite de sessions par utilisateur.
    ``TwoFactorBackupCode`` — stocke les codes de récupération à usage unique
    hashés en bcrypt, émis lorsqu'un utilisateur active la 2FA.

Responsabilités
---------------
- Fournir une surface d'import unique et stable pour tous les modèles
  accounts afin que les appelants ne dépendent pas de l'organisation
  interne des fichiers.
- Conserver les marqueurs ``# noqa: F401`` pour que les linters ne signalent
  pas les réexports comme imports inutilisés.

Fait partie du système de comptes UniAbsences.
"""

from apps.accounts.models_user import User, UserManager  # noqa: F401
from apps.accounts.models_security import TwoFactorBackupCode, UserSession  # noqa: F401
