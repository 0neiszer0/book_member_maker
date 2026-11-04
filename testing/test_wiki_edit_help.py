import unittest

from testing import test_wiki_integration as base
from wiki_routes import WikiStyle, clean_wiki_html


class WikiStyleTests(unittest.TestCase):
    def setUp(self):
        from flask import Flask
        self.app = Flask(__name__)
        self.app.add_url_rule('/wiki/w/<path:title>', 'wiki.document', lambda title: '')

    def clean(self, html):
        with self.app.test_request_context(base_url='https://knu-read.xyz'):
            return str(clean_wiki_html(html))

    def test_table_width_align_colors_survive(self):
        out = self.clean('<div class="table_safe" style="width:60%;"><table class="" style="width:60%;margin:auto;'
                         'background:#eeeeee;border:2px solid #999999;"><tr style=""><td colspan="1" rowspan="" '
                         'style="width:30%;text-align: center;">a</td><td style="text-align:right !important;'
                         'background:#ffeecc;color:red">b</td></tr></table></div>')
        self.assertIn('<table style="width:60%;margin:auto;background:#eeeeee;border:2px solid #999999">', out)
        self.assertIn('style="width:30%"', out)  # implicit 'text-align: center;' dropped
        self.assertIn('style="text-align:right;background:#ffeecc;color:red"', out)
        self.assertNotIn('class=', out)
        self.assertNotIn('style=""', out)

    def test_dangerous_css_and_attributes_are_dropped(self):
        out = self.clean('<div style="width:expression(alert(1));background:url(javascript:x);position:fixed;'
                         'color:red" onclick="x">a</div><span style="font-size:999%;color:#0000ff">b</span>'
                         '<a href="/w/x" style="color:red">c</a><img src=x onerror=alert(1)>')
        self.assertIn('<div style="color:red">a</div>', out)
        self.assertIn('<span style="color:#0000ff">b</span>', out)
        for bad in ('expression', 'url(', 'position', 'onclick', 'onerror', '<img', '999%'):
            self.assertNotIn(bad, out)
        self.assertNotIn('style', out.split('<a')[1].split('>')[0])

    def test_sanitizer_rules(self):
        s = WikiStyle()
        self.assertEqual(s.sanitize_css('padding:5px 10px; border:1px solid gray'), 'padding:5px 10px;border:1px solid gray')
        self.assertEqual(s.sanitize_css('margin-left: 20px;'), 'margin-left:20px')
        self.assertEqual(s.sanitize_css('width:100vw;height:-1px;color:rgb(1,2,3)'), 'color:rgb(1,2,3)')


class EditHelpPanelTests(base.RouteTests):
    def test_edit_page_has_collapsed_syntax_help_with_guide_link(self):
        self.login()
        html = self.client.get('/wiki/edit/대문').get_data(as_text=True)
        self.assertIn('<details class="wiki-syntax-help"', html)
        self.assertNotIn('<details class="wiki-syntax-help" open', html)
        self.assertIn('편집 문법 도움말', html)
        self.assertIn("{{{#red 빨강}}}", html)
        self.assertIn('/wiki/w/%EB%AC%B8%EC%84%9C%20%ED%8E%B8%EC%A7%91%20%EA%B0%80%EC%9D%B4%EB%93%9C', html)
        self.assertLess(html.index('wiki-syntax-help'), html.index('id="wiki-content"'))


for _name in [n for n in dir(base.RouteTests) if n.startswith('test_')]:
    setattr(EditHelpPanelTests, _name, None)
del _name
