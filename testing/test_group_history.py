import unittest

from group_history import canonical_pair_key, matrix_rows_from_history, pair_keys_from_groups


class GroupHistoryTests(unittest.TestCase):
    def test_latest_meeting_falls_back_after_delete(self):
        rows = [
            {'date': '2026-01-01', 'groups': [['가', '나']]},
            {'date': '2026-02-01', 'groups': [['가', '나']]},
        ]
        self.assertEqual(matrix_rows_from_history(rows)['가-나']['last_met'], '2026-02-01')
        self.assertEqual(matrix_rows_from_history(rows[:1])['가-나']['last_met'], '2026-01-01')

    def test_past_record_does_not_replace_latest(self):
        rows = [
            {'date': '2026-06-01', 'groups': [['가', '나']]},
            {'date': '2025-06-01', 'groups': [['가', '나']]},
        ]
        result = matrix_rows_from_history(rows)['가-나']
        self.assertEqual(result['count'], 2)
        self.assertEqual(result['last_met'], '2026-06-01')

    def test_removed_only_meeting_removes_pair(self):
        self.assertEqual(matrix_rows_from_history([]), {})

    def test_unicode_pair_key_is_stable(self):
        self.assertEqual(canonical_pair_key('한결', '강민우'), '강민우-한결')
        self.assertEqual(canonical_pair_key('강민우', '한결'), '강민우-한결')

    def test_affected_pair_filter(self):
        rows = [{'date': '2026-01-01', 'groups': [['가', '나', '다']]}]
        result = matrix_rows_from_history(rows, {'가-나'})
        self.assertEqual(set(result), {'가-나'})
        self.assertEqual(pair_keys_from_groups([['가', '나']]), {'가-나'})


if __name__ == '__main__':
    unittest.main()
