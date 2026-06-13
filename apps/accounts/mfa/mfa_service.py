"""
Service de logique métier MFA pour le système accounts d'UniAbsences.

Ce module est la couche indépendante du HTTP pour l'authentification à deux
facteurs TOTP. Il ne contient aucune vue Django ni logique de requête et
peut être appelé depuis des vues, des commandes de gestion ou des tests.

Responsabilités
---------------
- Définir les constantes de clés de session utilisées par ``TwoFactorMiddleware``
  et les vues 2FA pour suivre l'état de configuration et le statut de vérification.
- Exposer ``_normalize_token`` — supprime les espaces et les non-chiffres
  d'un token TOTP saisi par l'utilisateur pour gérer le copier-coller
  depuis les applications d'authentification.
- Exposer ``_normalize_backup_code`` — normalise une chaîne brute de code
  de secours vers la forme canonique alphanumérique en majuscules utilisée
  pour la comparaison de hash.
- Exposer ``_format_backup_code`` — formate un code de 10 caractères en
  deux groupes de 5 caractères séparés par un tiret pour l'affichage
  (ex. ``ABCDE-FGHIJ``).
- Exposer ``_generate_backup_codes`` — crée un nouveau lot de codes de
  secours, supprime atomiquement les codes existants et retourne les
  valeurs en clair pour que l'appelant puisse les afficher exactement une fois.
- Exposer ``_consume_backup_code`` — vérifie et consomme un seul code de
  secours atomiquement en utilisant ``select_for_update`` pour empêcher le
  double usage concurrent.
- Ré-exporter ``_generate_qr_data_uri`` depuis ``apps.utils`` sous l'alias
  ``_generate_qr_data_uri`` pour la rétrocompatibilité avec les appelants
  qui l'importent depuis ce module.

Fait partie du système accounts / MFA d'UniAbsences.
"""

import logging
import secrets

from django.contrib.auth.hashers import check_password, make_password
from django.db import transaction
from django.utils import timezone

from apps.utils import generate_qr_data_uri as _generate_qr_data_uri  # noqa: F401

from ..models import TwoFactorBackupCode

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constantes de clés de session
# ---------------------------------------------------------------------------

#: Clé sous laquelle le secret TOTP temporaire est stocké dans la session
#: pendant l'assistant d'enrôlement 2FA. Effacée une fois l'enrôlement confirmé.
SETUP_SECRET_SESSION_KEY = "_2fa_setup_secret"

#: Clé mise à ``True`` dans la session une fois que l'utilisateur a passé le
#: portail TOTP pour la session courante. Lue par ``TwoFactorMiddleware`` à chaque requête.
VERIFIED_SESSION_KEY = "2fa_verified"

#: Clé qui suit le nombre de tentatives de vérification TOTP échouées dans la
#: session courante. L'utilisateur est déconnecté lorsque cette valeur atteint
#: ``MAX_VERIFY_ATTEMPTS``.
ATTEMPTS_SESSION_KEY = "_2fa_attempts"

#: Nombre maximum de tentatives consécutives échouées de vérification TOTP avant
#: que la session ne soit forcée à se terminer.
MAX_VERIFY_ATTEMPTS = 5

#: Nom de l'émetteur intégré dans l'URI de provisionnement TOTP et affiché
#: par les applications d'authentification (Google Authenticator, Authy, etc.).
TOTP_ISSUER = "UniAbsences"

#: Clé de session sous laquelle les codes de secours nouvellement générés
#: (en clair) sont stockés pour un aller-retour unique vers la page d'affichage
#: à usage unique. La clé est retirée immédiatement après le rendu de la page
#: afin que les codes ne puissent pas être revisités.
BACKUP_CODES_SESSION_KEY = "_2fa_new_backup_codes"

#: Nombre de caractères dans chaque code de secours. Le code est divisé en
#: deux groupes de 5 caractères pour l'affichage : ``ABCDE-FGHIJ``.
BACKUP_CODE_LENGTH = 10


# ---------------------------------------------------------------------------
# Helpers TOTP
# ---------------------------------------------------------------------------


def _normalize_token(raw: str) -> str:
    """
    Normalise une chaîne brute de token TOTP en vue de la comparaison.

    Supprime tous les espaces et caractères non numériques, puis tronque à 6
    chiffres. Cela rend la fonction tolérante à une saisie utilisateur
    incluant des espaces (ex. « 123 456 » d'une application d'authentification
    qui ajoute un espace pour la lisibilité).

    Paramètres :
        raw (str) : la chaîne brute soumise par l'utilisateur.

    Retour :
        str : une chaîne d'au plus 6 chiffres, ou une chaîne vide si ``raw``
              est faux (falsy).
    """
    if not raw:
        return ""
    return "".join(ch for ch in raw if ch.isdigit())[:6]


# ---------------------------------------------------------------------------
# Helpers de codes de secours
# ---------------------------------------------------------------------------


def _normalize_backup_code(raw: str) -> str:
    """
    Normalise un code de secours brut en vue de la comparaison de hash.

    Convertit en majuscules et conserve uniquement les caractères
    alphanumériques, puis tronque à ``BACKUP_CODE_LENGTH`` (10). Cela rend la
    fonction tolérante aux entrées formatées avec un tiret séparateur
    (ex. ``ABCDE-FGHIJ`` devient ``ABCDEFGHIJ``).

    Paramètres :
        raw (str) : la chaîne brute du code soumis par l'utilisateur.

    Retour :
        str : le code normalisé (jusqu'à 10 caractères alphanumériques
              majuscules), ou une chaîne vide si ``raw`` est faux (falsy).
    """
    if not raw:
        return ""
    return "".join(ch for ch in raw.upper() if ch.isalnum())[: BACKUP_CODE_LENGTH]


def _format_backup_code(raw: str) -> str:
    """
    Formate un code de secours de 10 caractères en deux groupes de 5 caractères séparés par un tiret.

    Utilisé pour l'affichage des codes nouvellement générés afin qu'ils
    soient plus faciles à lire et à recopier (ex. ``ABCDE-FGHIJ``).

    Paramètres :
        raw (str) : un code de secours alphanumérique de 10 caractères.

    Retour :
        str : le code formaté en ``XXXXX-XXXXX``.
    """
    mid = BACKUP_CODE_LENGTH // 2
    return f"{raw[:mid]}-{raw[mid:]}"


def _generate_backup_codes(user, nb=TwoFactorBackupCode.CODES_PER_BATCH):
    """
    Génère un nouveau lot de codes de secours pour un utilisateur, en remplaçant tous les anciens.

    Tous les codes de secours existants de l'utilisateur (utilisés ou non) sont
    supprimés dans une transaction atomique avant que le nouveau lot ne soit
    créé. Seuls les hashes bcrypt des nouveaux codes sont persistés ; les
    valeurs en clair sont retournées à l'appelant afin qu'il puisse les
    afficher à l'utilisateur exactement une fois.

    Le jeu de caractères exclut volontairement les caractères visuellement
    ambigus (``O``, ``0``, ``1``, ``I``) afin de réduire les erreurs de recopie.

    Paramètres :
        user : l'instance ``User`` pour laquelle les codes sont générés.
        nb (int) : nombre de codes à générer. Par défaut
                   ``TwoFactorBackupCode.CODES_PER_BATCH`` (8).

    Retour :
        list[str] : codes en clair de longueur ``BACKUP_CODE_LENGTH``. Ils
                    **ne sont pas** stockés ; l'appelant doit les afficher à
                    l'utilisateur puis les jeter.
    """
    # Jeu de caractères non ambigus : pas de O/0/1/I pour éviter les erreurs de recopie.
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    plaintext = []
    with transaction.atomic():
        # Supprime tous les codes existants (utilisés ou non) afin d'éviter
        # toute ambiguïté sur les codes actuellement valides.
        TwoFactorBackupCode.objects.filter(user=user).delete()
        rows = []
        for _ in range(nb):
            raw = "".join(secrets.choice(alphabet) for _ in range(BACKUP_CODE_LENGTH))
            plaintext.append(raw)
            rows.append(
                TwoFactorBackupCode(
                    user=user,
                    # Stocke seulement le hash ; le clair n'est jamais persisté.
                    code_hash=make_password(raw),
                )
            )
        TwoFactorBackupCode.objects.bulk_create(rows)
    return plaintext


def _consume_backup_code(user, candidate: str) -> bool:
    """
    Vérifie et consomme un code de secours atomiquement.

    Tous les codes de secours inutilisés de l'utilisateur sont récupérés sous
    un verrou ``SELECT FOR UPDATE`` pour empêcher la vérification concurrente
    du même code par deux requêtes simultanées (attaque classique de
    double-dépense).

    Chaque hash est comparé à ``candidate`` à l'aide de ``check_password``
    (le wrapper à temps constant de Django autour du hasher configuré). La
    boucle **ne s'interrompt pas** sur un code non correspondant et itère
    sur tous les codes inutilisés pour éviter des canaux auxiliaires
    temporels qui pourraient révéler le nombre de codes restants.

    En cas de correspondance réussie, le code est immédiatement marqué
    ``used=True`` et ``used_at`` est renseigné afin qu'il ne puisse pas être
    réutilisé.

    Paramètres :
        user : l'instance ``User`` tentant la connexion par code de secours.
        candidate (str) : le code de secours normalisé (alphanumérique
                          majuscules) soumis par l'utilisateur. Doit faire
                          exactement ``BACKUP_CODE_LENGTH`` caractères.

    Retour :
        bool : ``True`` si un code inutilisé correspondant a été trouvé et
               consommé, ``False`` sinon.
    """
    # Rejette les entrées trivialement invalides sans frapper la base.
    if not candidate or len(candidate) != BACKUP_CODE_LENGTH:
        return False
    with transaction.atomic():
        # Verrouille tous les codes inutilisés de cet utilisateur pour la
        # durée de la transaction afin d'empêcher la consommation
        # concurrente du même code.
        unused = list(
            TwoFactorBackupCode.objects.select_for_update()
            .filter(user=user, used=False)
        )
        for row in unused:
            if check_password(candidate, row.code_hash):
                # Marque comme utilisé immédiatement pour empêcher la réutilisation.
                row.used = True
                row.used_at = timezone.now()
                row.save(update_fields=["used", "used_at"])
                return True
    return False
