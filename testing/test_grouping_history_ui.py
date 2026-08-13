import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class GroupingHistoryUiContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app_source = (ROOT / 'app.py').read_text(encoding='utf-8')
        cls.index_source = (ROOT / 'templates' / 'bookclub_index.html').read_text(encoding='utf-8')
        cls.results_source = (ROOT / 'templates' / 'bookclub_ga_results.html').read_text(encoding='utf-8')

    def test_no_shows_are_removed_from_meeting_statistics(self):
        self.assertIn('def _effective_group_history_rows():', self.app_source)
        self.assertIn("'excluded_names': sorted", self.app_source)
        self.assertIn("_rebuild_matrix_for_session(session_id)", self.app_source)
        self.assertIn('_meeting_details_from_history(effective_history_rows)', self.app_source)

    def test_results_show_plain_single_line_names_and_counts(self):
        self.assertIn('white-space:nowrap', self.results_source)
        self.assertIn('class="group-count-badge"', self.results_source)
        self.assertIn('class="result-total-count">{{ present|length }}</span>명', self.results_source)
        self.assertIn('grid-template-columns:1fr;gap:12px', self.results_source)
        self.assertIn(".join(', ')", self.results_source)

    def test_grouping_page_previews_selected_count_and_moves_history_action(self):
        header_start = self.index_source.index('<section class="work-header">')
        form_start = self.index_source.index('<form id="group-form"')
        button_at = self.index_source.index('id="manage-history-btn"')
        self.assertTrue(header_start < button_at < form_start)
        self.assertIn('id="group-size-preview"', self.index_source)
        self.assertIn('현재 ${selectedCount}명 · 예상 ${groupCount}개 조', self.index_source)

    def test_inline_edit_updates_all_meeting_dates_live(self):
        self.assertIn("resultContainer.addEventListener('input'", self.results_source)
        self.assertIn('function renderMeetingHistory(group, detailsDiv, live = false)', self.results_source)
        self.assertIn("entry.dates", self.results_source)
        self.assertIn('수정 중 만남 기록', self.results_source)
        self.assertIn("card.querySelector('.result-total-count').textContent = total", self.results_source)


if __name__ == '__main__':
    unittest.main()
