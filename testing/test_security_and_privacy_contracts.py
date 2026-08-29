import subprocess
import unittest
from pathlib import Path

from security_utils import forwarded_client_address, safe_internal_next_url


ROOT = Path(__file__).resolve().parents[1]


class SecurityHelperTests(unittest.TestCase):
    def test_safe_internal_next_url_only_accepts_same_site_paths(self):
        self.assertEqual(safe_internal_next_url("/my-page?tab=1#top"), "/my-page?tab=1#top")
        for value in (
            None,
            "",
            "https://evil.example/path",
            "//evil.example/path",
            "/%2f%2fevil.example/path",
            "/\\evil.example/path",
            "javascript:alert(1)",
            "relative/path",
        ):
            with self.subTest(value=value):
                self.assertIsNone(safe_internal_next_url(value))

    def test_forwarded_address_uses_edge_adjacent_value(self):
        self.assertEqual(
            forwarded_client_address("spoofed, 203.0.113.7", "127.0.0.1"),
            "203.0.113.7",
        )
        self.assertEqual(forwarded_client_address("", "127.0.0.1"), "127.0.0.1")


class SecurityContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app_source = (ROOT / "app.py").read_text(encoding="utf-8")
        cls.header = (ROOT / "templates" / "_header.html").read_text(encoding="utf-8")
        cls.vote = (ROOT / "templates" / "seminar_vote.html").read_text(encoding="utf-8")

    def test_notification_details_are_rendered_as_text(self):
        start = self.header.index("function render(notifs)")
        block = self.header[
            start:self.header.index("window.__fetchWoodNotifications", start)
        ]
        self.assertNotIn("d.innerHTML", block)
        self.assertIn("titleNode.textContent = title", block)
        self.assertIn("metaNode.textContent = meta", block)

    def test_oauth_state_and_redirect_are_validated(self):
        self.assertIn('session["oauth_state"] = state', self.app_source)
        self.assertIn("secrets.compare_digest(expected_state, received_state)", self.app_source)
        self.assertGreaterEqual(self.app_source.count("safe_internal_next_url("), 2)

    def test_admin_authorization_is_refreshed_from_members(self):
        self.assertIn('"role, is_active, member_status, account_status"', self.app_source)
        self.assertIn('user_role not in ("admin", "officer")', self.app_source)

    def test_cookie_headers_and_http_timeouts_are_explicit(self):
        for token in (
            "SESSION_COOKIE_HTTPONLY=True",
            "SESSION_COOKIE_SECURE=_cookie_secure",
            'SESSION_COOKIE_SAMESITE="Lax"',
            '"X-Content-Type-Options": "nosniff"',
            '"Strict-Transport-Security"',
            "timeout=EXTERNAL_HTTP_TIMEOUT",
        ):
            self.assertIn(token, self.app_source)

    def test_counts_url_does_not_contain_identity_fields(self):
        refresh = self.vote[
            self.vote.index("async function refreshCounts"):
            self.vote.index("document.getElementById('refreshBtn')")
        ]
        self.assertIn("viewer_token", refresh)
        self.assertNotIn("student_id", refresh)
        self.assertNotIn("verified.name", refresh)

    def test_sensitive_exports_are_not_tracked(self):
        tracked = subprocess.check_output(
            ["git", "ls-files", "--", "data/*.json", "data/*.csv", ".claude/settings.local.json"],
            cwd=ROOT,
            text=True,
            encoding="utf-8",
        ).strip()
        self.assertEqual(tracked, "")
        dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")
        self.assertIn(".env", dockerignore.splitlines())
        self.assertIn("data", dockerignore.splitlines())


if __name__ == "__main__":
    unittest.main()
