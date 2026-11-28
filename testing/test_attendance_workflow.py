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

class GroupedMemberIdsTests(unittest.TestCase):
    def test_exact_unique_names_only(self):
        from attendance_workflow import grouped_member_ids
        members = [{'id': 1, 'name': '가'}, {'id': 2, 'name': '나'}, {'id': 3, 'name': '나'}]
        ids, issues = grouped_member_ids([{'present': ['가', ' 나 ', '다', '가']}], members)
        self.assertEqual(ids, [1])
        self.assertEqual([(i['name'], i['reason']) for i in issues], [('나', '동명이인'), ('다', '회원 명단에 없음')])

    def test_groups_fallback_and_no_plan(self):
        from attendance_workflow import grouped_member_ids
        members = [{'id': 1, 'name': '가'}]
        self.assertEqual(grouped_member_ids([{'present': None, 'groups': [['가'], 'bad']}], members), ([1], []))
        self.assertEqual(grouped_member_ids([], members), (None, []))
        self.assertEqual(grouped_member_ids([{'present': None, 'groups': None}], members), (None, []))

    def test_active_member_preferred_and_unicode_nfc_normalized(self):
        import unicodedata
        from attendance_workflow import grouped_member_ids
        nfd_name = unicodedata.normalize('NFD', '홍길동')
        members = [
            {'id': 1, 'name': '홍길동', 'is_active': True},
            {'id': 2, 'name': '홍길동', 'is_active': False},
            {'id': 3, 'name': '이순신', 'is_active': False},
            {'id': 4, 'name': '김철수', 'is_active': True},
            {'id': 5, 'name': '김철수', 'is_active': True},
        ]
        ids, issues = grouped_member_ids(
            [{'present': [f' {nfd_name} ', '이순신', '김철수']}],
            members,
        )
        self.assertEqual(ids, [1, 3])
        self.assertEqual([(i['name'], i['reason']) for i in issues], [('김철수', '동명이인')])

    def test_match_roster_rows_normalizes_unicode_nfc(self):
        import unicodedata
        nfd = unicodedata.normalize('NFD', '독서')
        members = [{'id': 1, 'name': '독서', 'student_id': '202600001', 'is_active': True}]
        matched, issues = match_roster_rows([[f' {nfd} ']], members)
        self.assertEqual([m['id'] for m in matched], [1])
        self.assertEqual(issues, [])


class AttendanceGroupCardsTests(unittest.TestCase):
    members = [
        {'id': 1, 'name': '가', 'student_id': '202600001', 'department': '국문', 'is_active': True},
        {'id': 2, 'name': '나', 'is_active': True},
        {'id': 3, 'name': '동명', 'is_active': True},
        {'id': 4, 'name': '동명', 'is_active': True},
        {'id': 5, 'name': '라', 'is_active': True},
        {'id': 6, 'name': '라', 'is_active': False},
    ]

    def build(self, histories, actual=(1, 5), excluded=(2,)):
        from attendance_workflow import build_attendance_group_cards
        return build_attendance_group_cards(histories, self.members, actual, excluded)

    def test_cards_carry_names_facilitators_pre_absent_and_issues(self):
        cards, ids = self.build([{'groups': [['가', '나'], ['동명', '없음', '라']],
                                  'facilitators': [' 가 '],
                                  'group_editor_state': {'group_names': ['토론A']}}])
        self.assertEqual([c['title'] for c in cards], ['토론A', '2조'])
        self.assertEqual([c['index'] for c in cards], [1, 2])
        first = cards[0]['members']
        self.assertEqual(first[0], {'name': '가', 'member_id': 1, 'student_id': '202600001', 'department': '국문',
                                    'is_facilitator': True, 'pre_absent': False, 'attended': True, 'issue': None})
        self.assertEqual((first[1]['pre_absent'], first[1]['attended'], first[1]['is_facilitator']), (True, False, False))
        second = cards[1]['members']
        self.assertEqual([(m['name'], m['member_id'], m['issue']) for m in second],
                         [('동명', None, '동명이인'), ('없음', None, '회원 명단에 없음'), ('라', 5, None)])
        self.assertEqual(ids, {1, 2, 5})  # active-first match for 라, homonyms never guessed

    def test_each_member_appears_once_across_rows_and_groups(self):
        cards, ids = self.build([{'groups': [['가', '나']]}, {'groups': [['가'], ['나', '라']]},
                                 {'groups': []}, {'groups': None}])
        rendered = [m['member_id'] for c in cards for m in c['members'] if m['member_id']]
        self.assertEqual(sorted(rendered), sorted(set(rendered)))
        self.assertEqual(ids, {1, 2, 5})
        self.assertEqual([c['title'] for c in cards], ['1조', '2조'])

    def test_no_saved_groups_returns_empty(self):
        self.assertEqual(self.build([]), ([], set()))
        self.assertEqual(self.build([{'groups': None, 'present': ['가']}]), ([], set()))


if __name__ == '__main__':
    unittest.main()
