import importlib
import os
from datetime import date, timedelta
import unittest
from unittest.mock import patch

import pandas as pd

from testing._fake_supabase import FakeSupabase

os.environ.setdefault('PYTHON_DOTENV_DISABLED', '1')
os.environ.setdefault('FLASK_SECRET_KEY', 'cp-grouping-test')
os.environ.setdefault('SUPABASE_URL', 'http://127.0.0.1:9')
os.environ.setdefault('SUPABASE_SERVICE_KEY', 'cp-grouping-test')


def _members_df(names):
    return pd.DataFrame({'name': list(names), 'gender': ['M'] * len(names)})


class CpGroupingFixTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = importlib.import_module('app')
        cls.module.app.config['TESTING'] = True

    def test_three_attendees_produce_a_single_group(self):
        names = ['가', '나', '다']
        result = self.module.run_cp_grouping(
            _members_df(names), {}, names, [], optimize_for='gender', top_n=10,
        )
        self.assertGreaterEqual(len(result), 1)
        groups = result[0]['groups']
        self.assertEqual(len(groups), 1)
        self.assertEqual(set(groups[0]), set(names))

    def test_two_attendees_return_empty(self):
        names = ['가', '나']
        result = self.module.run_cp_grouping(
            _members_df(names), {}, names, [], optimize_for='gender', top_n=10,
        )
        self.assertEqual(result, [])

    def test_restricted_pair_infeasible_breaks_immediately(self):
        names = ['가', '나', '다', '라']
        solver_cls = self.module.cp_model.CpSolver
        original_solve = solver_cls.Solve
        calls = [0]

        def counting_solve(solver, model):
            calls[0] += 1
            return original_solve(solver, model)

        with patch.object(solver_cls, 'Solve', counting_solve):
            result = self.module.run_cp_grouping(
                _members_df(names), {}, names, [], optimize_for='gender', top_n=10,
                group_count_override=1, restricted_pairs={('가', '나')},
            )
        self.assertEqual(result, [])
        self.assertEqual(calls[0], 1)


class MakingTeamDayDefaultTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = importlib.import_module('app')
        cls.module.app.config['TESTING'] = True

    def setUp(self):
        # 결정적인 요일·날짜 조합: 목요일과 그 다음 월요일.
        thu = date(2026, 8, 13)
        thu += timedelta(days=(3 - thu.weekday()) % 7)
        mon = thu + timedelta(days=4)

        self.fake = FakeSupabase({
            'members': [
                {'id': 1, 'name': '운영', 'role': 'admin', 'is_active': True,
                 'account_status': 'active', 'member_status': 'active',
                 'student_id': '202600001', 'department': None, 'gender': 'M'},
            ],
            'seminar_terms': [{'id': 't1', 'name': '학기', 'start_date': '2026-08-01',
                               'end_date': '2026-08-31', 'is_active': True}],
            'seminar_sessions': [
                {'id': 'thu', 'term_id': 't1', 'meeting_date': thu.isoformat(), 'day_type': 'thu',
                 'is_active': True, 'planned_member_ids': None, 'participation_mode': 'legacy_explicit'},
                {'id': 'mon', 'term_id': 't1', 'meeting_date': mon.isoformat(), 'day_type': 'mon',
                 'is_active': True, 'planned_member_ids': None, 'participation_mode': 'legacy_explicit'},
            ],
            'group_pair_restrictions': [],
        })
        self.db = patch.object(self.module, 'supabase', self.fake)
        self.db.start()
        self.dates = patch.object(self.module, 'get_next_seminar_dates', return_value=[thu, mon])
        self.dates.start()
        self.client = self.module.app.test_client()
        with self.client.session_transaction() as state:
            state.update(user_id=1, user_role='admin', user_name='운영')

    def tearDown(self):
        patch.stopall()

    def test_defaults_to_thu_when_nearest_active_session_is_thursday(self):
        response = self.client.get('/making_team')
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('<a href="?day=thu" class="groups-fill lms-button">', html)

    def test_explicit_mon_day_is_respected(self):
        response = self.client.get('/making_team?day=mon')
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('<a href="?day=mon" class="groups-fill lms-button">', html)

    def test_unmigrated_future_thursday_uses_votes_and_past_thursday_keeps_legacy_defaults(self):
        target = self.fake.rows['seminar_sessions'][0]
        target['participation_mode'] = 'absence_only'
        for meeting_date, checked in [('2099-08-13', False), ('2000-08-13', True)]:
            target['meeting_date'] = meeting_date
            with patch.object(self.module, 'get_next_seminar_dates', return_value=[date.fromisoformat(meeting_date)]):
                for query in ('?session_id=thu', '?day=thu'):
                    with self.subTest(meeting_date=meeting_date, query=query):
                        page = self.client.get('/making_team' + query).get_data(as_text=True)
                        self.assertIn(f'id="cnt-voted">{int(checked)}</strong>', page)
        target['meeting_date'] = '2099-08-13'
        self.fake.rows['seminar_votes'] = [{'session_id': 'thu', 'member_id': 1, 'attending': True}]
        page = self.client.get('/making_team?session_id=thu').get_data(as_text=True)
        self.assertIn('id="cnt-voted">1</strong>', page)


if __name__ == '__main__':
    unittest.main()
