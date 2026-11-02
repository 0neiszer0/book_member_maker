import logging
import os
import unittest
from unittest.mock import patch

import signup_notify
from testing import test_local_login as base

FAKE_TOKEN = "123456:FAKE-token-never-logged"


class FakeResponse:
    def __init__(self, ok=True, status=200):
        self.ok, self.status_code = ok, status

    def json(self):
        return {"ok": self.ok}


class FakeHttp:
    def __init__(self, response=None, error=None):
        self.calls, self.response, self.error = [], response or FakeResponse(), error

    def post(self, url, data=None, timeout=None):
        self.calls.append(dict(url=url, data=data, timeout=timeout))
        if self.error:
            raise self.error
        return self.response


class SignupNotifyUnitTests(unittest.TestCase):
    def setUp(self):
        signup_notify.limiter = signup_notify._Limiter()
        self.env = patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": FAKE_TOKEN, "TELEGRAM_CHAT_IDS": "111"})
        self.env.start()
        self.logger = logging.getLogger("test-signup-notify")

    def tearDown(self):
        self.env.stop()

    def test_message_has_only_name_id_and_admin_link(self):
        text = signup_notify.build_message("newbie_01", "정신입")
        self.assertEqual(text, "[책반우] 새 가입 신청이 들어왔어요: 정신입 (newbie_01)\n승인: https://knu-read.xyz/admin/members")

    def test_sends_plain_text_with_short_timeout(self):
        http = FakeHttp()
        self.assertTrue(signup_notify.notify_signup("newbie_01", "정신입", self.logger, background=False, http=http))
        call = http.calls[0]
        self.assertEqual(call["timeout"], 5)
        self.assertEqual(call["data"]["chat_id"], "111")
        self.assertNotIn("parse_mode", call["data"])

    def test_failure_is_logged_without_token(self):
        http = FakeHttp(error=RuntimeError(f"connection failed for https://api.telegram.org/bot{FAKE_TOKEN}/sendMessage"))
        with self.assertLogs(self.logger, level="INFO") as logs:
            self.assertFalse(signup_notify.notify_signup("x_user", "이름", self.logger, background=False, http=http))
        self.assertTrue(logs.output)
        self.assertFalse(any(FAKE_TOKEN in line or "FAKE-token" in line for line in logs.output))

    def test_telegram_not_ok_counts_as_failure(self):
        http = FakeHttp(response=FakeResponse(ok=False, status=401))
        with self.assertLogs(self.logger, level="WARNING") as logs:
            self.assertFalse(signup_notify.notify_signup("x_user", "이름", self.logger, background=False, http=http))
        self.assertIn("HTTP 401", logs.output[0])

    def test_missing_config_does_nothing(self):
        http = FakeHttp()
        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": ""}):
            self.assertFalse(signup_notify.notify_signup("x_user", "이름", self.logger, background=False, http=http))
        self.assertEqual(http.calls, [])

    def test_flood_is_capped_and_summarized(self):
        now = [0.0]
        signup_notify.limiter = signup_notify._Limiter(limit=2, window=3600, clock=lambda: now[0])
        http = FakeHttp()
        for i in range(5):
            signup_notify.notify_signup(f"user_{i}", "이름", self.logger, background=False, http=http)
        self.assertEqual(len(http.calls), 2)
        now[0] = 3601
        signup_notify.notify_signup("user_9", "이름", self.logger, background=False, http=http)
        self.assertEqual(len(http.calls), 3)
        self.assertIn("3건", http.calls[-1]["data"]["text"])

    def test_background_send_never_raises(self):
        http = FakeHttp(error=TimeoutError())
        with patch("threading.Thread.start", side_effect=RuntimeError("no threads")):
            self.assertFalse(signup_notify.notify_signup("x_user", "이름", self.logger, http=http))


class SignupNotifyRouteTests(base.LocalLoginTests):
    """Only successful pending requests notify; rejected attempts don't."""

    def setUp(self):
        super().setUp()
        self.notify = patch.object(signup_notify, "notify_signup", return_value=True)
        self.mock = self.notify.start()

    def tearDown(self):
        self.notify.stop()
        super().tearDown()

    def test_notifies_once_for_successful_signup_only(self):
        self.assertEqual(self.signup(signup_code="WRONG1").status_code, 400)
        self.assertEqual(self.signup(password="short", password_confirm="short").status_code, 400)
        self.mock.assert_not_called()
        self.assertEqual(self.signup().status_code, 200)
        self.mock.assert_called_once()
        args = self.mock.call_args.args
        self.assertEqual(args[:2], ("newbie_01", "정신입"))
        self.assertEqual(self.signup().status_code, 400)  # same id again: rejected, no second notice
        self.mock.assert_called_once()

    def test_no_notice_when_signup_closed(self):
        self.db.rows["signup_codes"] = []
        self.assertEqual(self.signup().status_code, 403)
        self.mock.assert_not_called()


# Don't rerun the inherited login tests from this module.
for _name in [n for n in dir(base.LocalLoginTests) if n.startswith("test_")]:
    setattr(SignupNotifyRouteTests, _name, None)
del _name


class OpenSignupTests(base.LocalLoginTests):
    """No-code mode: officer approval is the only gate; code field hidden; spam guards stay."""

    def setUp(self):
        super().setUp()
        self.notify = patch.object(signup_notify, "notify_signup", return_value=True)
        self.mock = self.notify.start()
        self.db.rows["signup_codes"] = []
        self.admin_session()
        res = self.admin_post("/api/admin/signup-code", {"action": "open"})
        self.assertEqual(res.status_code, 200, res.get_data(as_text=True)[:300])
        self.client.get("/logout")
        with self.client.session_transaction() as s:
            s.clear()

    def tearDown(self):
        self.notify.stop()
        super().tearDown()

    def admin_session(self):
        self.as_member(1)

    def test_open_mode_hides_code_field_and_accepts_signup_without_code(self):
        html = self.client.get("/signup").get_data(as_text=True)
        self.assertNotIn('name="signup_code"', html)
        self.assertIn('name="website"', html)
        result = self.signup(signup_code="")
        self.assertEqual(result.status_code, 200, result.get_data(as_text=True)[:300])
        self.assertEqual(self.cred("newbie_01")["status"], "pending")
        self.mock.assert_called_once()
        self.assertEqual(self.login("newbie_01", base.GOOD_PW).status_code, 403)  # still needs approval

    def test_honeypot_fakes_success_but_stores_and_notifies_nothing(self):
        result = self.signup(signup_code="", website="http://spam.example")
        self.assertEqual(result.status_code, 200)
        self.assertIsNone(self.cred("newbie_01"))
        self.mock.assert_not_called()

    def test_per_ip_cap_on_created_requests(self):
        import local_auth
        for i in range(local_auth.SIGNUP_CREATE_LIMIT[0]):
            self.assertEqual(self.signup(signup_code="", login_id=f"spam_{i:02d}", student_id=f"20269999{i:02d}").status_code, 200)
        self.assertEqual(self.signup(signup_code="", login_id="spam_xx", student_id="2026999999").status_code, 429)
        self.assertIsNone(self.cred("spam_xx"))
        self.assertEqual(self.mock.call_count, local_auth.SIGNUP_CREATE_LIMIT[0])

    def test_per_ip_cap_on_submissions(self):
        import local_auth
        for _ in range(local_auth.SIGNUP_POST_LIMIT[0]):
            self.signup(signup_code="", login_id="x")  # invalid id -> 400, still counted
        self.assertEqual(self.signup(signup_code="").status_code, 429)

    def test_officer_switches_back_to_code_without_deploy(self):
        self.admin_session()
        self.assertEqual(self.admin_post("/api/admin/signup-code", {"action": "set", "code": "BACK2026"}).status_code, 200)
        self.client.get("/logout")
        with self.client.session_transaction() as s:
            s.clear()
        self.assertIn('name="signup_code"', self.client.get("/signup").get_data(as_text=True))
        self.assertEqual(self.signup(signup_code="").status_code, 400)
        self.assertEqual(self.signup(signup_code="back2026").status_code, 200)

    def test_marker_cannot_be_used_as_code_and_open_mode_ends_with_term(self):
        import local_auth
        self.admin_session()
        r = self.admin_post("/api/admin/signup-code", {"action": "set", "code": local_auth.OPEN_SIGNUP_MARKER})
        self.assertEqual(r.status_code, 400)
        page = self.client.get("/admin/members").get_data(as_text=True)
        self.assertIn("가입 코드 없이", page)
        self.assertNotIn(local_auth.OPEN_SIGNUP_MARKER, page)
        self.db.rows["seminar_terms"][0]["end_date"] = "2020-01-01"
        self.client.get("/logout")
        with self.client.session_transaction() as s:
            s.clear()
        self.assertEqual(self.signup(signup_code="").status_code, 403)


for _name in [n for n in dir(base.LocalLoginTests) if n.startswith("test_")]:
    setattr(OpenSignupTests, _name, None)
del _name
