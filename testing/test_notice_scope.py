import unittest
from unittest.mock import patch
from flask import Flask
from boards import init_board_routes
from testing.test_lms_improvements import WriteDB
from testing.test_lms_boards import Storage


class NoticeScopeTests(unittest.TestCase):
    def setUp(self):
        self.db = WriteDB({'boards':[dict(id='b',name='공지사항',slug='notices',board_type='general',read_role='member',write_role='officer',is_active=True)],
                          'seminar_terms':[dict(id='spring',name='봄학기'),dict(id='fall',name='가을학기')],
                          'members':[dict(id=1,name='운영진')],
                          'posts':[dict(id=key,board_id='b',term_id=term,title=key+' 공지',content='본문',author_id=1,created_at='2026-01-01',deleted_at=None)
                                   for key,term in [('global',None),('spring','spring'),('fall','fall')]]})
        self.db.storage = Storage()
        self.app = Flask(__name__); self.app.config.update(TESTING=True,SECRET_KEY='fixture')
        init_board_routes(self.app,self.db,lambda *a,**k:lambda f:f)
        self.client = self.app.test_client()
        with self.client.session_transaction() as state: state.update(user_id=1,user_role='officer')

    def get_posts(self, url):
        with patch('boards.render_template',return_value='view') as render:
            self.assertEqual(self.client.get(url).status_code,200)
            return [p['id'] for p in render.call_args.kwargs['posts']]

    def test_global_and_scoped_search_and_staff_all(self):
        self.assertEqual(self.get_posts('/board/notices'),['global'])
        self.assertEqual(set(self.get_posts('/board/notices?term_id=fall')),{'global','fall'})
        self.assertEqual(self.get_posts('/board/notices?term_id=fall&q=spring'),[])
        self.assertEqual(self.get_posts('/board/notices?term_id=fall&q=global'),['global'])
        self.assertEqual(set(self.get_posts('/board/notices?all_terms=1')),{'global','spring','fall'})
        with self.client.session_transaction() as state: state['user_role']='member'
        self.assertEqual(self.client.get('/board/notices?all_terms=1').status_code,403)

    def test_invalid_scope_never_inserts_and_valid_scope_redirects_to_matching_term(self):
        with patch('boards.render_template',return_value='form'):
            self.client.post('/board/notices/write?term_id=fall',data={'title':'새 공지','content':'본문','notice_term_id':'unknown'})
        self.assertEqual(len(self.db.rows['posts']),3)
        response = self.client.post('/board/notices/write?term_id=fall',data={'title':'새 공지','content':'본문','notice_term_id':'spring'})
        self.assertEqual(response.status_code,302)
        self.assertIn('term_id=spring',response.location)
        self.assertEqual(self.db.rows['posts'][-1]['term_id'],'spring')

    def test_edit_without_scope_preserves_it_and_explicit_global_change_is_allowed(self):
        response = self.client.post('/board/notices/fall/edit',data={'title':'수정','content':'본문'})
        self.assertEqual(response.status_code,302)
        self.assertEqual(self.db.rows['posts'][2]['term_id'],'fall')
        response = self.client.post('/board/notices/fall/edit?term_id=fall',data={'title':'전체로 변경','content':'본문','notice_term_id':''})
        self.assertEqual(response.status_code,302)
        self.assertNotIn('term_id=',response.location)
        self.assertIsNone(self.db.rows['posts'][2]['term_id'])

    def test_cross_term_link_is_rejected_and_demoted_author_cannot_edit_notice(self):
        self.assertEqual(self.client.get('/board/notices/spring?term_id=fall').status_code,404)
        with patch('boards.render_template',return_value='post') as render:
            self.assertEqual(self.client.get('/board/notices/spring').status_code,200)
            self.assertEqual(render.call_args.kwargs['notice_term_names']['spring'],'봄학기')
        with self.client.session_transaction() as state: state['user_role']='member'
        self.assertEqual(self.client.post('/board/notices/spring/edit',data={'title':'확대','content':'내용','notice_term_id':''}).status_code,403)


if __name__ == '__main__': unittest.main()
