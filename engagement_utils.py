import re
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


KYOBO_HOST = re.compile(r"(^|\.)kyobobook\.co\.kr$", re.IGNORECASE)


def clean_text(value, maximum):
    return (value or "").strip()[:maximum]


def normalize_kyobo_url(raw):
    value = (raw or "").strip()
    parts = urlsplit(value)
    host = (parts.hostname or "").lower()
    if parts.scheme.lower() != "https" or not KYOBO_HOST.search(host):
        raise ValueError("교보문고 상품 링크(https://…kyobobook.co.kr/…)를 입력해주세요.")
    clean_query = [
        (key, val) for key, val in parse_qsl(parts.query, keep_blank_values=True)
        if not key.lower().startswith("utm_") and key.lower() not in {"napa", "source"}
    ]
    path = parts.path.rstrip("/") or "/"
    return urlunsplit(("https", parts.netloc.lower(), path, urlencode(clean_query), ""))


def form_is_open(row, now=None):
    if not row or row.get("status") != "open":
        return False
    current = now or datetime.now(timezone.utc)
    for key, is_after in (("open_at", True), ("close_at", False)):
        raw = row.get(key)
        if not raw:
            continue
        stamp = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if is_after and current < stamp:
            return False
        if not is_after and current > stamp:
            return False
    return True
