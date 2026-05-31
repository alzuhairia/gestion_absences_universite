"""
Fonctions utilitaires d'audit pour le système UniAbsences.

Ce module constitue l'interface publique pour l'écriture des entrées de
journal d'audit. Toutes les vues, signaux et fonctions de service ayant
besoin d'enregistrer un événement de sécurité ou critique sur le plan
métier appellent ``log_action`` depuis ici.

Fonctions
---------
``log_action``
    Crée un enregistrement ``LogAudit``. Nettoie la chaîne ``detail`` pour
    supprimer les caractères de contrôle avant l'écriture, et retombe
    silencieusement en cas d'erreur de base de données pour éviter de
    perturber la transaction principale de l'appelant.

``get_client_ip``
    Mince enveloppe autour de ``ip_utils.extract_client_ip`` pour les
    appelants qui n'importent pas directement ``ip_utils``.

Fait partie du système d'audit UniAbsences.
"""

import re

from .ip_utils import extract_client_ip
from .models import LogAudit


def get_client_ip(request):
    """
    Extrait l'adresse IP réelle du client à partir d'une requête Django.

    Il s'agit d'une mince enveloppe autour de ``ip_utils.extract_client_ip``,
    fournie afin que les appelants d'autres modules puissent importer un
    seul nom depuis ``audits.utils`` sans avoir à connaître ``ip_utils``
    directement. Les en-têtes de proxy et de répartiteur de charge sont
    traités de manière sécurisée dans ``extract_client_ip``.

    Paramètres
    ----------
    request : django.http.HttpRequest
        La requête Django courante.

    Retourne
    --------
    str
        Chaîne d'adresse IP cliente normalisée.
    """
    return extract_client_ip(request)


def log_action(
    user, action, request=None, niveau="INFO", objet_type=None, objet_id=None
):
    """
    Crée une entrée dans le journal d'audit (``LogAudit``).

    Il s'agit de la seule fonction faisant autorité pour l'écriture
    d'enregistrements d'audit. Elle doit être appelée depuis les vues,
    les signaux et les fonctions de service à chaque fois qu'un événement
    de sécurité ou critique sur le plan métier se produit.

    Comportement
    ------------
    - Les utilisateurs non authentifiés ou ``None`` sont silencieusement
      ignorés — aucun enregistrement n'est créé.
    - La chaîne ``action`` est nettoyée en remplaçant les caractères de
      contrôle C0/C1 (``\\x00–\\x1f``, ``\\x7f–\\x9f``) par des espaces et
      en tronquant à 500 caractères. Un résultat vide après nettoyage est
      également silencieusement écarté.
    - Si l'action nettoyée contient le mot ``"CRITIQUE"`` (insensible à la
      casse) et que ``niveau`` n'a pas été explicitement surchargé depuis
      sa valeur par défaut ``"INFO"``, le niveau est automatiquement
      promu à ``"CRITIQUE"``. Cela permet aux appelants de passer une
      chaîne descriptive sans spécifier séparément la gravité.
    - L'IP du client retombe sur ``"0.0.0.0"`` lorsqu'aucune ``request``
      n'est fournie (par ex. commandes de gestion ou tâches Celery).

    Paramètres
    ----------
    user : django.contrib.auth.models.AbstractBaseUser
        L'utilisateur authentifié effectuant l'action. Si la valeur est
        falsy ou non authentifiée, l'appel est sans effet.
    action : str
        Description lisible de l'action (sera nettoyée et tronquée à
        500 caractères).
    request : django.http.HttpRequest, optionnel
        Requête Django courante, utilisée pour extraire l'IP du client.
        Passer ``None`` pour les contextes hors requête (commandes de
        gestion, tâches).
    niveau : str, optionnel
        Niveau de gravité : ``"INFO"`` (par défaut), ``"WARNING"`` ou
        ``"CRITIQUE"``.
    objet_type : str or None, optionnel
        Catégorie de l'objet affecté (par ex. ``"USER"``, ``"COURS"``).
        Doit être l'une de ``LogAudit.OBJET_TYPE_CHOICES`` ou ``None``.
    objet_id : int or None, optionnel
        Clé primaire de l'objet affecté, ou ``None``.

    Retourne
    --------
    None
        La fonction retourne toujours ``None``. Les erreurs de base de
        données ne sont pas supprimées — les appelants peuvent envelopper
        dans un try/except si nécessaire.
    """
    if not user or not user.is_authenticated:
        return

    # IP par défaut pour les contextes hors HTTP (commandes de gestion, tâches Celery)
    ip = "0.0.0.0"  # nosec B104
    if request:
        ip = get_client_ip(request)

    # Conversion en chaîne au cas où une non-chaîne aurait été transmise
    if not isinstance(action, str):
        action = str(action)
    # Remplace tous les caractères de contrôle C0 et C1 par des espaces afin de
    # prévenir les attaques par injection de logs, puis tronque à la limite de la colonne
    action = re.sub(r"[\x00-\x1f\x7f-\x9f]", " ", action)[:500]
    if not action.strip():
        return

    # Promotion automatique du niveau lorsque la description contient explicitement "CRITIQUE"
    # afin que les appelants puissent utiliser des chaînes descriptives sans définir niveau séparément
    if "CRITIQUE" in action.upper() and niveau == "INFO":
        niveau = "CRITIQUE"

    LogAudit.objects.create(
        id_utilisateur=user,
        action=action,
        adresse_ip=ip,
        niveau=niveau,
        objet_type=objet_type,
        objet_id=objet_id,
    )
