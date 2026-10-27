import unittest
from datetime import date
from functools import wraps
from unittest.mock import patch
from pathlib import Path
from jinja2 import Environment, FileSystemLoader

from flask import Flask, jsonify, session
from integrated_calendar import init_calendar_routes, seminar_calendar_events


class CalendarTests(unittest.TestCase):
    def test_calendar_uses_isolated_shell_and_real_controls(self):
        env = Environment(loader=FileSystemLoader(Path(__file__).resolve().parents[1] / 'templates'))
        env.globals.update(url_for=lambda endpoint, **values: '/' + values.get('filename', endpoint),
                           get_flashed_messages=lambda **kwargs: [])
        html = env.get_template('integrated_calendar.html').render(
            request={'endpoint': 'lms_calendar'}, session={}, calendar_today='2026-10-27', calendar_member=False, calendar_term='')
        self.assertIn('data-lms-page="calendar"', html)
        self.assertIn('lms_calendar.css', html)
        self.assertNotIn('theme.css', html)
        self.assertNotIn('tailwind', html)
        self.assertEqual(html.count('data-calendar-view='), 3)
        self.assertEqual(html.count('data-filter='), 4)
        self.assertIn('role="tabpanel"', html)

    def context(self):
        return dict(term={'id': 't'}, sessions=[dict(id='s', meeting_date='2026-10-29', seminar_week_id='w', day_type='thu')],
                    weeks={'w': {'book_title': '<책>'}}, topics={'w': dict(id='e', seminar_week_id='w', session_dates=['2026-10-29', '2026-11-02'], share_token='safe', open=True, status_label='제출 완료')})

    def test_deadline_uses_last_session_and_original_links(self):
        result = seminar_calendar_events(self.context())
        self.assertEqual(result[1]['start'], '2026-11-03T00:00:00+09:00')
        self.assertEqual(result[1]['url'], '/shared_topics?token=safe')
        self.assertIn('week_id=w', result[0]['url'])
        self.assertIn('session_id=s', result[0]['url'])
        self.assertEqual(result[1]['status'], '제출 완료')
        self.assertNotIn('share_token', result[1])

    def test_missing_share_token_links_to_original_week(self):
        context = self.context()
        context['topics']['w'].pop('share_token')
        self.assertTrue(seminar_calendar_events(context)[1]['url'].startswith('/seminars?'))

    def test_closed_deadline_and_null_book_use_curriculum_fallback(self):
        context = self.context()
        context['topics']['w']['open'] = False
        context['weeks']['w']['book_title'] = None
        event = seminar_calendar_events(context)[1]
        self.assertEqual(event['title'], '발제문 마감 · 도서 미정')
        self.assertTrue(event['url'].endswith('#topic-w'))
        self.assertNotIn('/shared_topics', event['url'])

    def app(self):
        app = Flask(__name__); app.secret_key = 'calendar-test'
        def login_required(role):
            def decorator(fn):
                @wraps(fn)
                def checked():
                    return fn() if session.get('user_id') else (jsonify(error='login'), 401)
                return checked
            return decorator
        init_calendar_routes(app, lambda: object(), login_required)
        return app

    def test_seminar_api_requires_login_and_no_store(self):
        response = self.app().test_client().get('/api/calendar/seminars')
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.headers['Cache-Control'], 'no-store')

    def test_lookup_failure_is_not_empty_success(self):
        client = self.app().test_client()
        with client.session_transaction() as state: state['user_id'] = 1
        with patch('integrated_calendar.load_seminar_context', side_effect=RuntimeError('offline')):
            response = client.get('/api/calendar/seminars')
        self.assertEqual(response.status_code, 503)
        self.assertIn('error', response.json)
        self.assertNotIn('events', response.json)


if __name__ == '__main__': unittest.main()
