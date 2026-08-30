import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]


class GroupGenerationStreamTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (ROOT / 'app.py').read_text(encoding='utf-8')
        cls.template = (ROOT / 'templates' / 'bookclub_index.html').read_text(
            encoding='utf-8'
        )

    def test_sse_generator_keeps_the_request_context(self):
        self.assertIn('stream_with_context', self.source)
        self.assertIn(
            'stream_with_context(generate_events(manual_entry_url))',
            self.source,
        )

    def test_client_can_cancel_retry_and_times_out_without_auto_reconnect(self):
        for control_id in ('generation-cancel', 'generation-retry', 'generation-close'):
            self.assertIn(f'id="{control_id}"', self.template)
        self.assertIn('if (activeGeneration) return;', self.template)
        self.assertIn('generateBtn.disabled = true;', self.template)
        self.assertIn('state.source.close();', self.template)
        self.assertIn("window.addEventListener('pagehide'", self.template)
        self.assertIn('new EventSource(', self.template)
        self.assertIn('}, 110000);', self.template)
        self.assertNotIn('new EventSource(event.target.url)', self.template)

    def test_server_propagates_disconnect_to_the_solver(self):
        stream = self.source[
            self.source.index('def start_group_generation'):
            self.source.index('def run_cp_grouping')
        ]
        solver = self.source[
            self.source.index('def run_cp_grouping'):
            self.source.index("@app.route('/manual_entry'")
        ]
        self.assertIn('cancel_event = threading.Event()', stream)
        self.assertIn('progress_queue.get(timeout=5)', stream)
        self.assertIn('except GeneratorExit:', stream)
        self.assertGreaterEqual(stream.count('cancel_event.set()'), 2)
        self.assertIn('cancel_event=None', solver)
        self.assertGreaterEqual(solver.count('cancel_event.is_set()'), 2)
        self.assertIn('solver.parameters.max_time_in_seconds = 1.5', solver)


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
