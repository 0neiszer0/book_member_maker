import unittest
from datetime import datetime, timezone

from engagement_utils import clean_text, form_is_open, normalize_kyobo_url


class EngagementUtilsTests(unittest.TestCase):
    def test_kyobo_link_is_normalized_and_tracking_is_removed(self):
        self.assertEqual(
            normalize_kyobo_url(
                "https://product.kyobobook.co.kr/detail/S000001?utm_source=kakao&foo=bar#section"
            ),
            "https://product.kyobobook.co.kr/detail/S000001?foo=bar",
        )

    def test_non_kyobo_or_insecure_link_is_rejected(self):
        for value in (
            "https://example.com/book",
            "http://product.kyobobook.co.kr/detail/1",
            "https://kyobobook.co.kr.evil.example/detail/1",
        ):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    normalize_kyobo_url(value)

    def test_form_window_and_status_are_enforced(self):
        now = datetime(2026, 7, 24, 3, 0, tzinfo=timezone.utc)
        self.assertTrue(form_is_open({
            "status": "open",
            "open_at": "2026-07-24T00:00:00Z",
            "close_at": "2026-07-24T06:00:00Z",
        }, now))
        self.assertFalse(form_is_open({
            "status": "closed",
            "open_at": "2026-07-24T00:00:00Z",
            "close_at": "2026-07-24T06:00:00Z",
        }, now))
        self.assertFalse(form_is_open({
            "status": "open",
            "open_at": "2026-07-25T00:00:00Z",
        }, now))

    def test_text_is_trimmed_and_bounded(self):
        self.assertEqual(clean_text("  abcdef  ", 4), "abcd")


if __name__ == "__main__":
    unittest.main()
