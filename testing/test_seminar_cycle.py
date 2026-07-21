import unittest
from datetime import date

from seminar_cycle import cycle_monday, next_seminar_cycle


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


if __name__ == '__main__':
    unittest.main()
