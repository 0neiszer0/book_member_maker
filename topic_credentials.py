import hashlib
import hmac
import secrets


TOKEN_CONTEXT = b"book-member-maker:topic-edit:v2:"
REQUEST_CONTEXT = b"book-member-maker:topic-edit-request:v1:"
# Seminar review links reuse the same token scheme in their own HMAC domain, so a
# topic edit code can never verify a review (and vice versa).
REVIEW_TOKEN_CONTEXT = b"book-member-maker:seminar-review-edit:v1:"
REVIEW_REQUEST_CONTEXT = b"book-member-maker:seminar-review-request:v1:"


def generate_topic_edit_token():
    """Return a high-entropy URL-safe token shown only to the submitter."""
    return secrets.token_urlsafe(32)


def topic_edit_token_digest(token, secret, context=TOKEN_CONTEXT):
    normalized = str(token or "").strip()
    if not normalized or not secret:
        return ""
    return hmac.new(
        str(secret).encode("utf-8"),
        context + normalized.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def topic_edit_token_matches(stored_digest, token, secret, context=TOKEN_CONTEXT):
    expected = str(stored_digest or "").strip().lower()
    actual = topic_edit_token_digest(token, secret, context)
    return bool(expected and actual and hmac.compare_digest(expected, actual))


def review_edit_token_digest(token, secret):
    return topic_edit_token_digest(token, secret, REVIEW_TOKEN_CONTEXT)


def review_edit_token_matches(stored_digest, token, secret):
    return topic_edit_token_matches(stored_digest, token, secret, REVIEW_TOKEN_CONTEXT)


def legacy_pin_matches(stored_pin, supplied_pin):
    expected = str(stored_pin or "").strip()
    actual = str(supplied_pin or "").strip()
    return bool(
        len(expected) == 4
        and expected.isdigit()
        and hmac.compare_digest(expected, actual)
    )


def topic_request_fingerprint(address, event_id, secret, context=REQUEST_CONTEXT):
    if not secret:
        return ""
    payload = f"{address or 'unknown'}|{event_id or ''}".encode("utf-8")
    return hmac.new(
        str(secret).encode("utf-8"),
        context + payload,
        hashlib.sha256,
    ).hexdigest()


def review_request_fingerprint(address, form_id, secret):
    return topic_request_fingerprint(address, form_id, secret, REVIEW_REQUEST_CONTEXT)
