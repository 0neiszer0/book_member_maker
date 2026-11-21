"""Ribbon editor page and the JSON live-preview endpoint (runs under unittest or pytest)."""
import pathlib
import unittest
from unittest.mock import patch

from bs4 import BeautifulSoup

import testing.test_wiki_integration as integration
from wiki_engine import EngineUnavailable


class EditorToolbarTests(unittest.TestCase):
    # Reuse the integration fixture without re-running its inherited tests.
    setUpClass = classmethod(integration.RouteTests.setUpClass.__func__)
    setUp = integration.RouteTests.setUp
    login = integration.RouteTests.login

    def post(self, content='초안', token='token', title='대문', **kwargs):
        return self.client.post('/wiki/api/preview/' + title,
                                data={'wiki_csrf': token, 'content': content}, **kwargs)

    def test_editor_renders_ribbon_table_tools_and_classic_actions(self):
        self.login()
        response = self.client.get('/wiki/edit/대문')
        self.assertEqual(response.status_code, 200)
        html = BeautifulSoup(response.data, 'html.parser')
        self.assertTrue(html.select_one('link[href*="wiki_editor.css"]'))
        self.assertTrue(html.select_one('script[src*="wiki_editor.js"]'))
        form = html.select_one('form.wiki-editor')
        self.assertEqual(form['data-preview-url'], '/wiki/api/preview/%EB%8C%80%EB%AC%B8')
        for selector in ['#wiki-ribbon', '#wiki-style', '#wiki-color', '#wiki-workspace #wiki-content',
                         '#wiki-live .wiki-prose', '[data-command=split]', '[data-command=refresh]',
                         '#wiki-context [data-command=editTable]', 'dialog#wiki-picker .picker-grid',
                         'dialog#wiki-link', 'dialog#wiki-table #wiki-grid', '#table-width', '#cell-align',
                         '#cell-bg', '[data-command=equal]', '[data-command=header]', '[data-command=apply]',
                         '[data-command=mergeRight]', '[data-command=mergeDown]', '[data-command=unmerge]',
                         'input[name=wiki_csrf]', 'input[name=version]',
                         '[name=action][value=save]', '[name=action][value=preview]']:
            self.assertIsNotNone(html.select_one(selector), selector)
        for command in ['undo', 'redo', 'bold', 'italic', 'underline', 'strike', 'large', 'small', 'bullets',
                        'numbers', 'quote', 'fold', 'rule', 'break', 'toc', 'link', 'note', 'table']:
            self.assertIsNotNone(html.select_one('#wiki-ribbon [data-command=%s]' % command), command)
        self.assertEqual(html.select_one('#wiki-content').text.lstrip('\n'), 'sample')

    def test_direct_resize_hooks_in_template_js_and_css(self):
        self.login()
        html = BeautifulSoup(self.client.get('/wiki/edit/대문').data, 'html.parser')
        tip = html.select_one('#wiki-live header .wiki-live-tip')
        self.assertIsNotNone(tip)
        self.assertIn('미리보기 표의 세로선·오른쪽 끝을 드래그해 너비를 바로 조절할 수 있어요.', tip.text)
        self.assertTrue(tip.has_attr('hidden'))
        root = pathlib.Path(__file__).resolve().parent.parent / 'static'
        js = (root / 'wiki_editor.js').read_text(encoding='utf-8')
        css = (root / 'wiki_editor.css').read_text(encoding='utf-8')
        for token in ['findAllTables', 'setTableWidth', 'matchTables', 'decorateTables', "matchMedia('(min-width: 960px)')",
                      'wiki-col-handle', 'wiki-table-edge', 'wiki-table-bar', '표 편집', '균등', '표 너비 ', 'pointerup']:
            self.assertIn(token, js, token)
        for token in ['.wiki-col-handle', '.wiki-table-edge', '.wiki-resize-badge', 'col-resize', 'ew-resize', '#d20f17']:
            self.assertIn(token, css, token)

    def test_classic_preview_submit_still_works_without_js(self):
        self.login()
        response = self.client.post('/wiki/edit/대문', data=dict(action='preview', wiki_csrf='token',
                                                               content='초안', version='1'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(BeautifulSoup(response.data, 'html.parser').select_one('.wiki-preview article').text,
                         'sample')

    def test_preview_rechecks_login_permission_csrf_and_origin(self):
        with patch.object(self.engine, 'render') as render:
            response = self.post()
            self.assertEqual(response.status_code, 401)
            self.assertFalse(response.json['ok'])
            self.login()
            self.assertEqual(self.post(title='운영진:회의').status_code, 404)
            for kwargs in [dict(token=''), dict(token='틀림'), dict(headers={'Origin': 'https://else.example'}),
                           dict(headers={'Sec-Fetch-Site': 'cross-site'})]:
                response = self.post(**kwargs)
                # Cross-origin requests may be stopped earlier by the app-wide guard (HTML 403).
                self.assertEqual(response.status_code, 403, kwargs)
                self.assertFalse(response.is_json and response.json['ok'])
            self.db.rows['seminar_term_members'][0]['status'] = 'paused'
            self.assertEqual(self.post().status_code, 403)
            render.assert_not_called()

    def test_preview_strips_officer_includes_and_sanitizes(self):
        self.login()
        with patch.object(self.engine, 'render', return_value='<p onclick="bad()">문서</p><script>x()</script>') as render:
            response = self.post(content='[include(운영진:회의)]\r\n[include(안내)]\n[목차]',
                                 headers={'Origin': 'http://localhost', 'Sec-Fetch-Site': 'same-origin'})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json, {'ok': True, 'html': '<p>문서</p>'})
            source = render.call_args.args[-1]
            self.assertNotIn('운영진:회의', source)
            self.assertIn('[include(안내)]\n[목차]', source)
            self.assertIn('no-store', response.headers['Cache-Control'])

    def test_preview_byte_limit_missing_content_and_outage(self):
        self.login()
        text = '한' * 170_666 + 'ab'  # exactly 512,000 UTF-8 bytes
        self.assertEqual(self.post(content=text, content_type='multipart/form-data').status_code, 200)
        # Classic urlencoded submits triple Korean bytes; the full limit still fits.
        self.assertEqual(self.post(content=text).status_code, 200)
        classic = self.client.post('/wiki/edit/대문', data=dict(action='preview', wiki_csrf='token',
                                                              content=text, version='1'))
        self.assertEqual(classic.status_code, 200)
        with patch.object(self.engine, 'render', side_effect=EngineUnavailable('offline')) as render:
            for content in [text + 'x', 'a' * 600_000]:
                response = self.post(content=content, content_type='multipart/form-data')
                self.assertEqual(response.status_code, 400)
                self.assertFalse(response.json['ok'])
            response = self.client.post('/wiki/api/preview/대문', data={'wiki_csrf': 'token'})
            self.assertEqual(response.status_code, 400)
            render.assert_not_called()
            response = self.post()
            self.assertEqual(response.status_code, 503)
            self.assertFalse(response.json['ok'])


class OfficerPreviewTests(unittest.TestCase):
    setUpClass = classmethod(integration.RouteTests.setUpClass.__func__)
    login = integration.RouteTests.login
    OFFICER_DOC = integration.OfficerRouteTests.OFFICER_DOC

    def setUp(self):
        integration.RouteTests.setUp(self)
        self.db.rows['members'].append(dict(id=3, name='운영진 예시', social_id='9003', role='member',
                                            is_active=True, account_status='active', member_status='active'))
        self.db.rows['seminar_terms'][0]['operations_initialized_at'] = '2026-09-01'
        self.db.rows['operation_roles'] = [dict(id='academic_head', is_active=True)]
        self.db.rows['term_officers'] = [dict(term_id='current', member_id=3, role_id='academic_head')]
        self.rendered = []
        self.engine.render = lambda client, title, source: self.rendered.append(source) or '<p>ok</p>'

    def test_officer_previews_officer_doc_with_includes_member_cannot(self):
        data = {'wiki_csrf': 'token', 'content': '[include(운영진:대문)]'}
        self.login(1)
        self.assertEqual(self.client.post('/wiki/api/preview/' + self.OFFICER_DOC, data=data).status_code, 404)
        self.assertEqual(self.rendered, [])
        self.login(3)
        response = self.client.post('/wiki/api/preview/' + self.OFFICER_DOC, data=data)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json['ok'])
        self.assertEqual(self.rendered, ['[include(운영진:대문)]'])


if __name__ == '__main__':
    unittest.main()
