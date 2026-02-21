import ipaddress

from django.conf import settings


def _parse_ip(value: str):
    if not value:
        return None
    try:
        return ipaddress.ip_address(value.strip())
    except ValueError:
        return None


def _proxy_networks():
    networks = []
    for cidr in getattr(settings, 'TRUSTED_PROXY_CIDRS', []):
        try:
            networks.append(ipaddress.ip_network(cidr, strict=False))
        except ValueError:
            continue
    return networks


def _is_trusted_proxy(remote_ip) -> bool:
    if remote_ip is None:
        return False
    for network in _proxy_networks():
        if remote_ip in network:
            return True
    return False


def extract_client_ip(request) -> str:
    """
    Determine client IP without trusting X-Forwarded-For blindly.

    Trust X-Real-IP only when the direct peer is in TRUSTED_PROXY_CIDRS.
    Otherwise use REMOTE_ADDR.
    """
    remote_ip = _parse_ip(request.META.get('REMOTE_ADDR', ''))
    real_ip = _parse_ip(request.META.get('HTTP_X_REAL_IP', ''))

    if real_ip is not None and _is_trusted_proxy(remote_ip):
        return str(real_ip)

    if remote_ip is not None:
        return str(remote_ip)

    return '0.0.0.0'


def ratelimit_client_ip(group, request) -> str:
    """Key function compatible with django-ratelimit decorators."""
    return extract_client_ip(request)


def ratelimit_login_ip_username(group, request) -> str:
    """
    Login throttle key based on client IP + submitted username/email.

    This reduces brute force via credential stuffing while remaining proxy-safe.
    """
    identity = ''
    if request.method == 'POST':
        identity = (
            request.POST.get('username')
            or request.POST.get('email')
            or ''
        )
    normalized_identity = identity.strip().lower() or 'anonymous'
    return f"{extract_client_ip(request)}:{normalized_identity}"
