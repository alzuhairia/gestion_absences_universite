"""
Utilitaires d'extraction sécurisée d'IP pour le système d'audit et de limitation de débit d'UniAbsences.

Ce module fournit des fonctions qui extraient en toute sécurité l'adresse
IP réelle du client à partir de requêtes pouvant transiter par des proxys
inverses ou des répartiteurs de charge de confiance, sans faire aveuglément
confiance à l'en-tête ``X-Forwarded-For``.

Fonctions
---------
``extract_client_ip``
    Lit ``X-Forwarded-For`` uniquement lorsque ``REMOTE_ADDR`` est un CIDR
    listé dans ``settings.TRUSTED_PROXY_CIDRS`` ; sinon, retombe sur
    ``REMOTE_ADDR``. Retourne une chaîne IP nettoyée.

``ratelimit_client_ip``
    Fonction de clé django-ratelimit — retourne l'IP du client pour la
    limitation de débit par IP (utilisée sur les endpoints de connexion
    et de réinitialisation de mot de passe).

``ratelimit_login_ip_username``
    Fonction de clé django-ratelimit — retourne ``IP:username_hash`` pour
    la protection combinée IP + compte contre la force brute sur
    l'endpoint de connexion.

Fait partie du système d'audit UniAbsences.
"""

import ipaddress

from django.conf import settings


def _parse_ip(value: str):
    """
    Analyse une chaîne brute en un objet ``ipaddress.IPv4Address`` ou ``IPv6Address``.

    Les espaces de tête/fin sont supprimés avant l'analyse pour tolérer
    de légères différences de formatage dans les valeurs des en-têtes HTTP.

    Paramètres
    ----------
    value : str
        Chaîne brute d'adresse IP (peut être vide ou malformée).

    Retourne
    --------
    ipaddress.IPv4Address | ipaddress.IPv6Address | None
        Objet adresse analysé, ou ``None`` si l'entrée est vide ou n'est
        pas une adresse IP valide.
    """
    if not value:
        return None
    try:
        # strip() protège contre les espaces que certains proxys insèrent
        return ipaddress.ip_address(value.strip())
    except ValueError:
        return None


def _proxy_networks():
    """
    Construit une liste de réseaux de proxy de confiance à partir des paramètres Django.

    Lit ``settings.TRUSTED_PROXY_CIDRS`` (une liste de chaînes CIDR telles que
    ``["10.0.0.0/8", "172.16.0.0/12"]``) et convertit chaque entrée en un
    objet ``ipaddress.ip_network``. Les chaînes CIDR malformées sont
    silencieusement ignorées afin qu'une entrée mal configurée ne fasse
    jamais planter l'application.

    ``strict=False`` permet aux bits d'hôte d'être positionnés dans la
    notation CIDR (par ex. ``10.0.0.1/24`` est traité comme ``10.0.0.0/24``).

    Retourne
    --------
    list[ipaddress.IPv4Network | ipaddress.IPv6Network]
        Liste d'objets réseaux de proxy de confiance ; vide si le paramètre
        est absent ou ne contient aucun CIDR valide.
    """
    networks = []
    for cidr in getattr(settings, "TRUSTED_PROXY_CIDRS", []):
        try:
            # strict=False : tolère les bits d'hôte positionnés dans le CIDR (par ex. 10.0.0.1/24)
            networks.append(ipaddress.ip_network(cidr, strict=False))
        except ValueError:
            # Ignore les chaînes CIDR invalides plutôt que de planter
            continue
    return networks


def _is_trusted_proxy(remote_ip) -> bool:
    """
    Retourne ``True`` si ``remote_ip`` se situe dans un CIDR de proxy de confiance.

    Itère sur les réseaux retournés par ``_proxy_networks()`` et vérifie
    l'appartenance via l'opérateur ``in`` sur les objets ``ip_network``,
    qui prend en charge à la fois IPv4 et IPv6.

    Paramètres
    ----------
    remote_ip : ipaddress.IPv4Address | ipaddress.IPv6Address | None
        L'adresse IP analysée du pair de connexion directe.

    Retourne
    --------
    bool
        ``True`` si l'adresse correspond à un réseau de proxy de confiance ;
        ``False`` si elle ne correspond pas ou si ``remote_ip`` est ``None``.
    """
    if remote_ip is None:
        return False
    for network in _proxy_networks():
        if remote_ip in network:
            return True
    return False


def extract_client_ip(request) -> str:
    """
    Détermine l'adresse IP réelle du client à partir d'un objet requête Django.

    Modèle de sécurité
    ------------------
    ``X-Real-IP`` (défini par nginx ou un répartiteur de charge de confiance)
    n'est honoré *que* lorsque le pair de connexion directe (``REMOTE_ADDR``)
    se trouve lui-même dans ``settings.TRUSTED_PROXY_CIDRS``. Cela empêche
    un utilisateur final malveillant d'usurper son IP en injectant un
    en-tête ``X-Real-IP`` directement. Si le pair direct n'est pas un proxy
    de confiance, ``REMOTE_ADDR`` est retourné tel quel.

    Paramètres
    ----------
    request : django.http.HttpRequest
        La requête Django courante. Doit disposer d'un dictionnaire ``META`` peuplé.

    Retourne
    --------
    str
        La meilleure adresse IP client disponible sous forme de chaîne normalisée.
        Retombe sur ``"0.0.0.0"`` si ``REMOTE_ADDR`` est absent ou non
        analysable (ne devrait pas se produire en production).
    """
    remote_ip = _parse_ip(request.META.get("REMOTE_ADDR", ""))
    real_ip = _parse_ip(request.META.get("HTTP_X_REAL_IP", ""))

    # On ne fait confiance à X-Real-IP que si le pair direct est un proxy de confiance connu
    if real_ip is not None and _is_trusted_proxy(remote_ip):
        return str(real_ip)

    if remote_ip is not None:
        return str(remote_ip)

    return "0.0.0.0"  # nosec B104


def ratelimit_client_ip(group, request) -> str:
    """
    Fonction de clé django-ratelimit pour la limitation de débit par IP.

    Cette fonction satisfait le contrat de l'appelable ``key`` de
    django-ratelimit (arguments positionnels ``group`` + ``request``) et
    retourne l'IP client nettoyée extraite via ``extract_client_ip``.
    À utiliser sur les endpoints devant être limités uniquement par IP
    cliente (par ex. réinitialisation de mot de passe, endpoints d'API
    anonymes).

    Paramètres
    ----------
    group : str
        Le nom de groupe de limitation de débit fourni par django-ratelimit
        (inutilisé ici mais requis par la convention d'appel).
    request : django.http.HttpRequest
        La requête Django courante.

    Retourne
    --------
    str
        Chaîne d'adresse IP cliente utilisée comme clé de bucket de limitation.
    """
    return extract_client_ip(request)


def ratelimit_login_ip_username(group, request) -> str:
    """
    Fonction de clé django-ratelimit combinant l'IP cliente et les identifiants soumis.

    Produit une clé composite de la forme ``"<IP>:<identité_normalisée>"``
    où ``identité_normalisée`` est la valeur en minuscules et trimée du
    champ POST ``username`` ou ``email`` (selon celui présent), ou la
    chaîne littérale ``"anonymous"`` si aucun n'est fourni.

    Cette clé fournit deux protections complémentaires :

    - **Limitation par IP** : un attaquant essayant successivement des
      identifiants depuis une seule IP est rapidement bloqué.
    - **Limitation par compte** : les attaques de credential-stuffing qui
      répartissent les tentatives sur de nombreuses IP mais ciblent le
      même compte sont également limitées, car le nom de compte fait
      partie de la clé.

    Paramètres
    ----------
    group : str
        Le nom de groupe de limitation de débit fourni par django-ratelimit (inutilisé).
    request : django.http.HttpRequest
        La requête Django courante. Les champs ``username`` / ``email``
        ne sont lus que sur les requêtes ``POST``.

    Retourne
    --------
    str
        Clé composite de bucket de limitation ``"<IP>:<identité>"``.
    """
    identity = ""
    if request.method == "POST":
        # Accepte un champ "username" ou "email" pour couvrir les deux formulaires de connexion
        identity = request.POST.get("username") or request.POST.get("email") or ""
    # Normalisation : minuscules + suppression des espaces ; retour à "anonymous" si vide
    normalized_identity = identity.strip().lower() or "anonymous"
    return f"{extract_client_ip(request)}:{normalized_identity}"
