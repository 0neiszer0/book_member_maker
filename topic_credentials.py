import hashlib
import hmac
import secrets


TOKEN_CONTEXT = b"book-member-maker:topic-edit:v2:"
REQUEST_CONTEXT = b"book-member-maker:topic-edit-request:v1:"


def generate_topic_edit_token():
    """Return a high-entropy URL-safe token shown only to the submitter."""
    return secrets.token_urlsafe(32)


def topic_edit_token_digest(token, secret):
    normalized = str(token or "").strip()
    if not normalized or not secret:
        return ""
    return hmac.new(
        str(secret).encode("utf-8"),
        TOKEN_CONTEXT + normalized.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def topic_edit_token_matches(stored_digest, token, secret):
    expected = str(stored_digest or "").strip().lower()
    actual = topic_edit_token_digest(token, secret)
    return bool(expected and actual and hmac.compare_digest(expected, actual))


def legacy_pin_matches(stored_pin, supplied_pin):
    expected = str(stored_pin or "").strip()
    actual = str(supplied_pin or "").strip()
    return bool(
        len(expected) == 4
        and expected.isdigit()
        and hmac.compare_digest(expected, actual)
    )


def topic_request_fingerprint(address, event_id, secret):
    if not secret:
        return ""
    payload = f"{address or 'unknown'}|{event_id or ''}".encode("utf-8")
    return hmac.new(
        str(secret).encode("utf-8"),
        REQUEST_CONTEXT + payload,
        hashlib.sha256,
    ).hexdigest()
