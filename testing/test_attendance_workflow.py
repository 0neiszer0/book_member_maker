import unittest
from datetime import date
from attendance_workflow import build_term_attendance, match_roster_rows, parse_roster_text, expected_member_ids


class AttendanceWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.members = [{'id': 1, 'name': '독서', 'student_id': '202600001', 'is_active': True},
                        {'id': 2, 'name': '호반', 'student_id': '202600002', 'is_active': True},
                        {'id': 3, 'name': '동명', 'student_id': '202600003', 'is_active': True},
                        {'id': 4, 'name': '동명', 'student_id': '202600004', 'is_active': True}]

    def report(self, **overrides):
        kwargs = dict(members=self.members, histories=[], sessions=[], events=[], event_attendees=[],
                      brick_sessions=[], brick_members=[], start='2026-08-01', end='2026-08-31', today=date(2026, 8, 31))
        kwargs.update(overrides)
        return build_term_attendance(**kwargs)

    def test_exact_matching_and_ambiguous_unknown_duplicate_reporting(self):
        matched, issues = match_roster_rows(parse_roster_text('이름 학번\n독서 202600001\n동명\n호반\n호반\n없는사람'), self.members)
        self.assertEqual([m['id'] for m in matched], [1, 2])
        self.assertEqual(len(issues), 3)
        self.assertEqual(issues[0]['line'], 3)

    def test_student_id_does_not_override_wrong_name(self):
        matched, issues = match_roster_rows([['호반', '202600001']], self.members)
        self.assertEqual(matched, [])
        self.assertEqual(len(issues), 1)

    def test_thursday_subtracts_and_monday_includes_without_capacity(self):
        self.assertEqual(expected_member_ids('absence', [2], [1, 2, 3]), [1, 3])
        self.assertEqual(expected_member_ids('attendance', list(range(1, 101)), list(range(1, 101))), list(range(1, 101)))
        self.assertEqual(expected_member_ids('attendance', [], [1, 2]), [])
        self.assertEqual(expected_member_ids('absence', [], [1, 2]), [1, 2])
        with self.assertRaises(ValueError):
            expected_member_ids('attendance', [9], [1, 2])

    def test_zero_attendees_and_empty_term_remain_visible(self):
        report = self.report()
        self.assertEqual(len(report['members']), 4)
        self.assertTrue(all(m['total'] == 0 and m['shortage'] == 3 for m in report['members']))

    def test_week_dedup_ot_brick_sum_and_separate_date_matrix(self):
        report = self.report(sessions=[
            {'id': 'thu', 'meeting_date': '2026-08-13', 'actual_member_ids': [1], 'attendance_confirmed_at': 'yes'},
            {'id': 'mon', 'meeting_date': '2026-08-17', 'actual_member_ids': [1], 'attendance_confirmed_at': 'yes'}],
            events=[{'id': 'ot', 'event_date': '2026-08-10', 'counts_toward_attendance': True, 'attendance_confirmed_at': 'yes'}],
            event_attendees=[{'event_id': 'ot', 'member_id': 1}],
            brick_sessions=[{'id': 'brick', 'meeting_date': '2026-08-20'}],
            brick_members=[{'session_id': 'brick', 'member_id': 1}, {'session_id': 'brick', 'member_id': 1}])
        self.assertEqual(report['members'][0]['total'], 3)
        self.assertEqual(report['members'][0]['counts'], {'seminar': 1, 'ot': 1, 'brick': 1})
        self.assertEqual(len(report['columns']), 4)

    def test_unconfirmed_and_future_events_do_not_count(self):
        report = self.report(histories=[{'id': 'h', 'date': '2026-08-13', 'present': ['독서']}],
                             sessions=[{'id': 's', 'meeting_date': '2026-09-03', 'actual_member_ids': [1], 'attendance_confirmed_at': 'yes'}],
                             events=[{'id': 'ot', 'event_date': '2026-08-10', 'counts_toward_attendance': True}],
                             event_attendees=[{'event_id': 'ot', 'member_id': 1}])
        self.assertEqual(report['members'][0]['total'], 0)

    def test_legacy_ambiguous_names_are_not_guessed(self):
        report = self.report(histories=[{'id': 'h', 'date': '2026-08-13', 'present': ['동명', '독서'], 'attendance_confirmed_at': 'yes'}])
        self.assertEqual([m['total'] for m in report['members']], [1, 0, 0, 0])
        self.assertEqual(len(report['warnings']), 1)

    def test_actual_snapshot_survives_group_edit(self):
        report = self.report(histories=[{'id': 'h', 'date': '2026-08-13', 'present': ['호반'], 'actual_member_ids': [1], 'attendance_confirmed_at': 'yes'}])
        self.assertEqual([m['total'] for m in report['members']], [1, 0, 0, 0])

    def test_no_show_and_cancellation_apply_to_legacy_history(self):
        history = [{'id': 'h', 'date': '2026-08-13', 'present': ['독서'], 'seminar_session_id': 's', 'attendance_confirmed_at': 'yes'}]
        no_show = {'session_id': 's', 'member_id': 1, 'cancelled_at': None}
        self.assertEqual(self.report(histories=history, no_shows=[no_show])['members'][0]['total'], 0)
        no_show['cancelled_at'] = 'yes'
        self.assertEqual(self.report(histories=history, no_shows=[no_show])['members'][0]['total'], 1)

    def test_cross_month_week_and_term_bounds(self):
        report = self.report(sessions=[{'id': 's', 'meeting_date': '2026-08-27', 'actual_member_ids': [1], 'attendance_confirmed_at': 'yes'},
                                      {'id': 't', 'meeting_date': '2026-08-31', 'actual_member_ids': [1], 'attendance_confirmed_at': 'yes'}])
        self.assertEqual(report['members'][0]['total'], 1)


if __name__ == '__main__':
    unittest.main()
