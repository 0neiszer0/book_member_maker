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
