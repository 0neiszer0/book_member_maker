"""Telegram notice to the officers' chat when a new signup request is waiting for approval.

Uses the existing TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_IDS settings. Sending happens on a
background thread with a short timeout so Telegram can never slow down or break signup.
The token is never logged: failures are logged by exception type / HTTP status only.
At most MAX_PER_WINDOW notices go out per WINDOW; the rest are counted and mentioned in
the next notice (the 회원 관리 page always lists every pending request).
"""

import os
import threading
import time
from collections import deque

import requests

ADMIN_URL = 'https://knu-read.xyz/admin/members'
TIMEOUT_SECONDS = 5
MAX_PER_WINDOW = 5
WINDOW_SECONDS = 3600


class _Limiter:
    def __init__(self, limit=MAX_PER_WINDOW, window=WINDOW_SECONDS, clock=time.monotonic):
        self.limit, self.window, self.clock = limit, window, clock
        self.sent = deque()
        self.suppressed = 0
        self.lock = threading.Lock()

    def take(self):
        """Return (allowed, suppressed_before) and update the window."""
        with self.lock:
            now = self.clock()
            while self.sent and now - self.sent[0] >= self.window:
                self.sent.popleft()
            if len(self.sent) >= self.limit:
                self.suppressed += 1
                return False, 0
            self.sent.append(now)
            skipped, self.suppressed = self.suppressed, 0
            return True, skipped


limiter = _Limiter()


def build_message(login_id, name, skipped=0):
    text = f'[책반우] 새 가입 신청이 들어왔어요: {name} ({login_id})\n승인: {ADMIN_URL}'
    if skipped:
        text += f'\n(알림 제한으로 못 보낸 신청 {skipped}건이 더 있어요)'
    return text


def _chat_ids():
    return [c.strip() for c in (os.environ.get('TELEGRAM_CHAT_IDS') or '').split(',') if c.strip()]


def send(text, logger, http=requests):
    """Send text to every configured chat. Returns the number of chats that accepted it."""
    token = os.environ.get('TELEGRAM_BOT_TOKEN')
    chats = _chat_ids()
    if not token or not chats:
        logger.warning('Signup telegram notice skipped: TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_IDS not set')
        return 0
    delivered = 0
    for index, chat_id in enumerate(chats, 1):
        try:
            response = http.post(f'https://api.telegram.org/bot{token}/sendMessage',
                                 data={'chat_id': chat_id, 'text': text, 'disable_web_page_preview': 'true'},
                                 timeout=TIMEOUT_SECONDS)
            ok = False
            try:
                ok = bool(response.json().get('ok'))
            except Exception:
                pass
            if ok:
                delivered += 1
                # WARNING level on purpose: the app logger drops INFO, and officers want a trace in the journal.
                logger.warning('Signup telegram notice sent (chat %d/%d, ok=true)', index, len(chats))
            else:
                logger.warning('Signup telegram notice failed (chat %d/%d, HTTP %s)', index, len(chats),
                               getattr(response, 'status_code', '?'))
        except Exception as exc:  # never include str(exc): request errors can carry the URL with the token
            logger.warning('Signup telegram notice failed (chat %d/%d, %s)', index, len(chats), type(exc).__name__)
    return delivered


def notify_signup(login_id, name, logger, *, background=True, http=requests):
    """Queue a notice for one successful (pending) signup request. Never raises."""
    try:
        allowed, skipped = limiter.take()
        if not allowed:
            logger.warning('Signup telegram notice rate-limited')
            return False
        text = build_message(login_id, name, skipped)
        if not background:
            return send(text, logger, http) > 0
        threading.Thread(target=send, args=(text, logger, http), name='signup-telegram', daemon=True).start()
        return True
    except Exception as exc:
        logger.warning('Signup telegram notice not queued (%s)', type(exc).__name__)
        return False
