import unittest

from seminar_absence import normalize_member_ids


class SeminarAbsenceInputTests(unittest.TestCase):
    def test_accepts_bulk_ids_and_removes_duplicates(self):
        self.assertEqual(
            normalize_member_ids({'member_ids': ['3', 1, '3', 2]}),
            [3, 1, 2],
        )

    def test_keeps_single_member_backwards_compatible(self):
        self.assertEqual(normalize_member_ids({'member_id': '7'}), [7])

    def test_rejects_empty_or_invalid_ids(self):
        for payload in ({'member_ids': []}, {'member_ids': ['x']}, {'member_id': None}):
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError):
                    normalize_member_ids(payload)


if __name__ == '__main__':
    unittest.main()
