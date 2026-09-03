import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class GroupingHistoryUiContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app_source = (ROOT / 'app.py').read_text(encoding='utf-8')
        cls.index_source = (ROOT / 'templates' / 'bookclub_index.html').read_text(encoding='utf-8')
        cls.results_source = (ROOT / 'templates' / 'bookclub_ga_results.html').read_text(encoding='utf-8')
        cls.record_source = (ROOT / 'templates' / 'records_seminar_detail.html').read_text(encoding='utf-8')
        cls.editor_source = (ROOT / 'static' / 'group_editor.js').read_text(encoding='utf-8')
        cls.editor_css = (ROOT / 'static' / 'group_editor.css').read_text(encoding='utf-8')

    def test_no_shows_are_removed_from_meeting_statistics(self):
        self.assertIn('def _effective_group_history_rows():', self.app_source)
        self.assertIn("'excluded_names': sorted", self.app_source)
        self.assertIn("_rebuild_matrix_for_session(session_id)", self.app_source)
        self.assertIn('_meeting_details_from_history(effective_history_rows, before_date=meeting_date)', self.app_source)
        self.assertIn("row.get('attendance_confirmed_at')", self.app_source)
        self.assertIn("linked['actual_member_ids']", self.app_source)

    def test_results_show_plain_single_line_names_and_counts(self):
        self.assertIn('white-space:nowrap', self.editor_source)
        self.assertIn('class="ge-count"', self.editor_source)
        self.assertIn('class="result-total-count">{{ present|length }}</span>명', self.results_source)
        self.assertIn('grid-template-columns:1fr;gap:12px', self.editor_source)
        self.assertIn(".join(', ')", self.editor_source)

    def test_grouping_page_previews_selected_count_and_moves_history_action(self):
        header_start = self.index_source.index('<section class="work-header">')
        form_start = self.index_source.index('<form id="group-form"')
        button_at = self.index_source.index('id="manage-history-btn"')
        self.assertTrue(header_start < button_at < form_start)
        self.assertIn('id="group-size-preview"', self.index_source)
        self.assertIn('현재 ${selectedCount}명 · 예상 ${groupCount}개 조', self.index_source)

    def test_shared_editor_updates_all_meeting_dates_without_a_toggle(self):
        self.assertIn("container.addEventListener('drop'", self.editor_source)
        self.assertIn('function historyHtml(group)', self.editor_source)
        self.assertIn('entry.dates', self.editor_source)
        self.assertIn('이전 만남은 즉시 갱신됩니다', self.editor_source)
        self.assertNotIn('show-history-btn', self.results_source)
        self.assertIn("card.querySelector('.result-total-count').textContent = state.groups.flat().length", self.results_source)
        self.assertIn('GroupEditor.mount', self.record_source)

    def test_grouping_names_have_accessible_gender_colors_and_labels(self):
        self.assertIn('student_id, department, gender', self.app_source)
        self.assertIn("member['gender_code'] = normalize_gender", self.app_source)
        self.assertIn('class="gender-legend"', self.index_source)
        self.assertIn('gender-tag gender-female', self.index_source)
        self.assertIn('gender-tag gender-male', self.index_source)
        self.assertIn('function chip(name, removable)', self.editor_source)
        self.assertIn('.ge-chip.ge-male', self.editor_css)
        self.assertIn('.ge-chip.ge-female', self.editor_css)

    def test_gender_member_cards_stay_inside_one_aligned_table_column(self):
        self.assertIn('.member-list { display:grid; grid-template-columns:minmax(0,1fr)', self.index_source)
        self.assertIn('.member-row { width:100%; max-width:100%; box-sizing:border-box;', self.index_source)
        self.assertIn('.member-row > span { min-width:0; overflow-wrap:anywhere; }', self.index_source)
        self.assertNotIn('grid-template-columns:repeat(2,minmax(0,1fr))', self.index_source)

    def test_saved_record_can_recreate_group_capture(self):
        self.assertIn('html2canvas/1.4.1/html2canvas.min.js', self.record_source)
        self.assertIn('PNG 다시 만들기', self.record_source)
        self.assertIn('async function captureSavedGroups()', self.record_source)
        self.assertIn("canvas.toDataURL('image/png')", self.editor_source)
        self.assertIn('id="record-image-download"', self.record_source)
        self.assertIn("'genders': member_genders", self.record_source)
        self.assertIn('GroupEditor.validate(payload.groups)', self.record_source)


if __name__ == '__main__':
    unittest.main()
