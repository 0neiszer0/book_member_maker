import unittest
from unittest.mock import patch

from testing import test_wiki_integration as base
from wiki_routes import diff_rows

SOURCES = {1: '== 개요 ==\n제1조 목적\n제2조 명칭', 2: '== 개요 ==\n제1조 목적 (개정)\n제2조 명칭\n제3조 신설'}


class DiffRowTests(unittest.TestCase):
    def test_added_removed_and_inline_marks(self):
        rows = diff_rows(SOURCES[1], SOURCES[2])
        kinds = [r['kind'] for r in rows]
        self.assertEqual(kinds.count('add'), 2)
        self.assertEqual(kinds.count('del'), 1)
        self.assertIn('<ins> (개정)</ins>', str(next(r for r in rows if r['kind'] == 'add')['text']))

    def test_markup_in_source_is_escaped(self):
        rows = diff_rows('a', '<script>x</script>')
        self.assertTrue(all('<script>' not in str(r['text']) for r in rows))


class DiffRouteTests(base.RouteTests):
    def setUp(self):
        super().setUp()
        self.engine.revision_source = lambda client, title, number: SOURCES.get(number)
        self.engine.history = lambda *a: [['2', '', '2026-10-31', 'a', '개정'], ['1', '', '2026-10-30', 'a', '제정']]

    def test_member_sees_highlighted_diff_and_history_links(self):
        self.login()
        html = self.client.get('/wiki/diff/회칙/전문?old=1&new=2').get_data(as_text=True)
        self.assertIn('r1 ↔ r2 비교', html)
        self.assertIn('<tr class="add">', html)
        self.assertIn('<tr class="del">', html)
        self.assertIn('+2', html)
        history = self.client.get('/wiki/history/회칙/전문').get_data(as_text=True)
        self.assertIn('/wiki/diff/', history)
        self.assertIn('old=1&amp;new=2', history)
        self.assertIn('선택한 버전 비교', history)

    def test_reversed_and_bad_input(self):
        self.login()
        self.assertEqual(self.client.get('/wiki/diff/회칙/전문?old=2&new=1').status_code, 200)
        for query in ['old=1&new=1', 'old=x&new=2', 'old=1', 'old=-1&new=2']:
            self.assertEqual(self.client.get('/wiki/diff/회칙/전문?' + query).status_code, 400, query)
        self.assertEqual(self.client.get('/wiki/diff/회칙/전문?old=1&new=9').status_code, 404)

    def test_logged_out_redirects(self):
        result = self.client.get('/wiki/diff/회칙/전문?old=1&new=2')
        self.assertEqual(result.status_code, 302)


class OfficerDiffTests(base.OfficerRouteTests):
    def test_member_cannot_diff_officer_page(self):
        self.login(1)
        called = []
        self.engine.revision_source = lambda *a: called.append(a) or 'x'
        result = self.client.get('/wiki/diff/' + self.OFFICER_DOC + '?old=1&new=2')
        self.assertEqual(result.status_code, 404)
        self.assertEqual(called, [])

    def test_officer_can_diff_officer_page(self):
        self.login(3)
        self.engine.revision_source = lambda client, title, number: SOURCES.get(number)
        self.assertEqual(self.client.get('/wiki/diff/' + self.OFFICER_DOC + '?old=1&new=2').status_code, 200)
