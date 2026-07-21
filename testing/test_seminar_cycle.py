import unittest
from datetime import date

from seminar_cycle import cycle_monday, is_member_signup_session, next_seminar_cycle


class SeminarCycleTests(unittest.TestCase):
    def test_thursday_and_following_monday_share_cycle_key(self):
        self.assertEqual(cycle_monday(date(2026, 7, 23)), date(2026, 7, 27))
        self.assertEqual(cycle_monday(date(2026, 7, 27)), date(2026, 7, 27))

    def test_next_cycle_is_thursday_then_following_monday(self):
        self.assertEqual(
            next_seminar_cycle(date(2026, 7, 22)),
            [date(2026, 7, 23), date(2026, 7, 27)],
        )
        self.assertEqual(
            next_seminar_cycle(date(2026, 7, 24)),
            [date(2026, 7, 23), date(2026, 7, 27)],
        )
        self.assertEqual(
            next_seminar_cycle(date(2026, 7, 28)),
            [date(2026, 7, 30), date(2026, 8, 3)],
        )

    def test_thursday_includes_today(self):
        self.assertEqual(
            next_seminar_cycle(date(2026, 7, 23)),
            [date(2026, 7, 23), date(2026, 7, 27)],
        )
        self.assertEqual(
            next_seminar_cycle(date(2026, 7, 27)),
            [date(2026, 7, 23), date(2026, 7, 27)],
        )

    def test_member_signup_only_shows_monday_opt_in(self):
        self.assertTrue(is_member_signup_session({'day_type': 'mon', 'participation_mode': 'opt_in'}))
        self.assertFalse(is_member_signup_session({'day_type': 'thu', 'participation_mode': 'absence_only'}))
        self.assertFalse(is_member_signup_session({'day_type': 'thu', 'participation_mode': 'legacy_explicit'}))


if __name__ == '__main__':
    unittest.main()
