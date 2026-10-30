import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class GuidesAndRecordEditingTest(unittest.TestCase):
    def read(self, relative_path):
        return (ROOT / relative_path).read_text(encoding="utf-8")

    def test_member_guide_leads_with_current_required_flow_and_links(self):
        guide = self.read("templates/help_member.html")
        self.assertIn("참여 전 확인할 3가지", guide)
        self.assertIn("해당 회차의 카카오톡 투표와 공지에 따라", guide)
        self.assertIn("추가 세미나는 개설된 회차만", guide)
        self.assertIn("회차에 맞는 발제문 제출", guide)
        self.assertIn("url_for('seminars')", guide)
        self.assertIn("url_for('my_page')", guide)
        self.assertNotIn("월/목 회차별로", guide)

    def test_admin_guide_covers_recurring_and_periodic_work(self):
        guide = self.read("templates/help_admin.html")
        for section_id in ("weekly", "term-start", "term-end", "yearly", "records"):
            self.assertIn(f'id="{section_id}"', guide)
        self.assertIn("날짜·도서 편집", guide)
        self.assertIn("무단 불참자는", guide)

    def test_seminar_records_use_one_edit_dialog(self):
        template = self.read("templates/records_seminars.html")
        self.assertIn('id="seminarEditDialog"', template)
        self.assertIn('id="editBookTitle"', template)
        self.assertIn('id="editGroupDetail"', template)
        self.assertNotIn('id="editFacilitators"', template)
        self.assertNotIn('id="editGroups"', template)
        self.assertIn("변경사항 저장", template)
        self.assertNotIn("onblur=\"updateMeta", template)

    def test_history_title_updates_linked_week_and_sessions(self):
        source = self.read("app.py")
        route = source[source.index("def update_history_meta"):source.index("def records_history_delete")]
        self.assertIn("seminar_weeks').update", route)
        self.assertIn("seminar_sessions').update", route)
        self.assertIn("topic_events').update", route)
        self.assertIn("linked_session_ids", route)

    def test_member_status_is_an_explicit_three_button_control(self):
        template = self.read("templates/records_members.html")
        self.assertIn("버튼을 누르면 즉시 저장", template)
        self.assertIn('class="status-control"', template)
        self.assertEqual(template.count('class="status-choice" data-member-id='), 3)
        self.assertNotIn("status-select", template)


if __name__ == "__main__":
    unittest.main()
