import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]


class GroupGenerationStreamTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (ROOT / 'app.py').read_text(encoding='utf-8')

    def test_sse_generator_keeps_the_request_context(self):
        self.assertIn('stream_with_context', self.source)
        self.assertIn(
            'stream_with_context(generate_events(manual_entry_url))',
            self.source,
        )


class AdminNavigationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (ROOT / 'templates' / '_admin_sidebar.html').read_text(
            encoding='utf-8'
        )

    def test_compact_navigation_stays_visible_and_scrollable(self):
        self.assertIn('@media (max-width:1279px)', self.source)
        self.assertIn('overflow-x:auto', self.source)
        self.assertIn('wd-admin-scroll-left', self.source)
        self.assertIn('wd-admin-scroll-right', self.source)

    def test_active_item_is_brought_into_view(self):
        self.assertIn("nav.querySelector('a.active')", self.source)
        self.assertIn("inline: 'center'", self.source)


if __name__ == '__main__':
    unittest.main()
