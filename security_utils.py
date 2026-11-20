"""Small security helpers that do not depend on Flask or production secrets."""

from urllib.parse import unquote, urlsplit


def safe_internal_next_url(value):
    """Return a same-site absolute path or ``None`` for external/ambiguous URLs."""
    if not isinstance(value, str):
        return None
    candidate = value.strip()
    if not candidate or not candidate.startswith("/"):
        return None
    decoded = unquote(candidate)
    if decoded.startswith("//") or "\\" in decoded:
        return None
    if any(char in candidate for char in ("\r", "\n", "\x00")):
        return None
    parsed = urlsplit(candidate)
    if parsed.scheme or parsed.netloc:
        return None
    return candidate


def forwarded_client_address(forwarded_for, remote_addr):
    """Use the address appended nearest to the trusted edge, not spoofable first input."""
    addresses = [part.strip() for part in (forwarded_for or "").split(",") if part.strip()]
    return addresses[-1] if addresses else (remote_addr or "unknown")


def trusted_client_address(headers, remote_addr, trusted_proxy=False):
    """Resolve the client address the club-room rate limiter should key on.

    When the request was forwarded by a trusted app proxy, prefer the
    app-attested ``X-App-Client-IP``; otherwise fall back to the edge-adjacent
    ``X-Forwarded-For`` value (or the direct remote address).
    """
    if trusted_proxy:
        client_ip = (headers.get('X-App-Client-IP') or '').strip()
        if client_ip:
            return client_ip
    return forwarded_client_address(headers.get('X-Forwarded-For'), remote_addr)
