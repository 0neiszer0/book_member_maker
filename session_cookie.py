"""Session cookie that is only refreshed by real page navigations.

Flask re-sends the whole signed session cookie on every response when the
session is permanent and SESSION_REFRESH_EACH_REQUEST is on. A background
response (static file, service worker check, manifest, notification poll)
that started with an older cookie could then overwrite a newer one, for
example bringing back flash messages that a page had already shown.

Here a response only sets the cookie when the session data really changed,
or when it answers a top-level page navigation (which keeps the 90-day
remembered login rolling).
"""
from flask import request
from flask.sessions import SecureCookieSessionInterface

QUIET_ENDPOINTS = frozenset({'static', 'push_service_worker', 'push_manifest', 'storage_image'})
QUIET_PREFIXES = ('/api/', '/static/', '/media/')


def is_page_navigation(req):
    """True for a top-level document request that may roll the login expiry."""
    if req.method not in ('GET', 'HEAD'):
        return False
    if req.endpoint in QUIET_ENDPOINTS or req.path.startswith(QUIET_PREFIXES):
        return False
    mode = (req.headers.get('Sec-Fetch-Mode') or '').lower()
    dest = (req.headers.get('Sec-Fetch-Dest') or '').lower()
    if mode or dest:
        return mode == 'navigate' or dest == 'document'
    # Older browsers/webviews without Fetch Metadata: treat page GETs as navigations.
    return True


class QuietRefreshSessionInterface(SecureCookieSessionInterface):
    def open_session(self, app, req):
        session = super().open_session(app, req)
        if session is not None:
            session.baseline_snapshot = self._snapshot(session)
        return session

    def _snapshot(self, session):
        try:
            return self.serializer.dumps(dict(session))
        except Exception:
            return None

    def should_set_cookie(self, app, session):
        if not super().should_set_cookie(app, session):
            return False
        baseline = getattr(session, 'baseline_snapshot', None)
        changed = baseline is None or self._snapshot(session) != baseline
        if changed:
            return True
        return is_page_navigation(request)
