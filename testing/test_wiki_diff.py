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

    def test_large_input_skips_inline_marks(self):
        big_old, big_new = 'A' * 60_000, 'B' * 60_000
        rows = diff_rows('header\n' + big_old, 'header\n' + big_new)
        changed = [r for r in rows if r['kind'] in ('del', 'add')]
        self.assertTrue(changed)
        self.assertTrue(all('<ins>' not in str(r['text']) and '<del>' not in str(r['text']) for r in changed))
        self.assertIn(big_new, [str(r['text']) for r in rows if r['kind'] == 'add'])

    def test_long_line_skips_inline_marks(self):
        rows = diff_rows('short old', 'X' * 5_000)
        added = [r for r in rows if r['kind'] == 'add']
        self.assertEqual(str(added[0]['text']), 'X' * 5_000)
        self.assertNotIn('<ins>', str(added[0]['text']))


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

    def test_fallback_to_line_text_still_escapes_markup(self):
        self.login()
        long_line = '<script>alert(1)</script>' + 'x' * 5000
        self.engine.revision_source = lambda client, title, number: {1: 'old', 2: long_line}.get(number)
        html = self.client.get('/wiki/diff/회칙/전문?old=1&new=2').get_data(as_text=True)
        self.assertNotIn('<script>alert(1)</script>', html)
        self.assertIn('&lt;script&gt;alert(1)&lt;/script&gt;', html)


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
