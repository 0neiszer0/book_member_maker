import unittest
from unittest.mock import patch
from flask import Flask
from boards import init_board_routes
from testing._fake_supabase import FakeSupabase


class ClassroomBoardFilterTests(unittest.TestCase):
    def test_history_filter_is_limited_to_review_boards_and_preserved_in_context(self):
        db = FakeSupabase({'boards': [
            {'id': 'review', 'slug': 'reviews', 'board_type': 'seminar_review', 'is_active': True, 'read_role': 'member', 'write_role': 'member'},
            {'id': 'general', 'slug': 'general', 'board_type': 'general', 'is_active': True, 'read_role': 'member', 'write_role': 'member'}],
            'posts': [
                {'id': 'one', 'board_id': 'review', 'history_id': 'h1', 'author_id': None},
                {'id': 'two', 'board_id': 'review', 'history_id': 'h2', 'author_id': None},
                {'id': 'three', 'board_id': 'general', 'history_id': 'h2', 'author_id': None}]})
        app = Flask(__name__)
        app.config.update(TESTING=True, SECRET_KEY='test-only')
        init_board_routes(app, db, lambda *args, **kwargs: lambda view: view)
        client = app.test_client()
        with client.session_transaction() as state:
            state['user_role'] = 'member'
        with patch('boards.render_template', return_value='ok') as render:
            self.assertEqual(client.get('/board/reviews?history_id=h1').status_code, 200)
            self.assertEqual([p['id'] for p in render.call_args.kwargs['posts']], ['one'])
            self.assertEqual(render.call_args.kwargs['history_id'], 'h1')
            self.assertEqual(client.get('/board/general?history_id=h1').status_code, 200)
            self.assertEqual([p['id'] for p in render.call_args.kwargs['posts']], ['three'])
            self.assertEqual(render.call_args.kwargs['history_id'], '')
