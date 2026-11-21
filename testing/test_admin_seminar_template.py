import unittest
from pathlib import Path


class AdminSeminarTemplateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (Path(__file__).parents[1] / 'templates' / 'admin_seminars.html') \
            .read_text(encoding='utf-8')

    def test_topic_actions_do_not_stretch_to_card_height(self):
        self.assertIn('flex flex-wrap items-start justify-between', self.source)
        self.assertIn('flex items-center self-start gap-2 flex-wrap', self.source)
        css = (Path(__file__).parents[1] / 'static' / 'lms_operations.css').read_text(encoding='utf-8')
        self.assertRegex(css, r'\.lms-operations :is\(\.chip[^)]*\)\{display:inline-flex;flex:none;')

    def test_both_cards_use_attendance_lists(self):
        self.assertIn('for m in thu.attendees', self.source)
        self.assertIn('for m in mon.attendees', self.source)
        self.assertEqual(self.source.count('카카오톡 참석 명단 반영·출석 확정'), 2)
        self.assertNotIn('absence-picker', self.source)

    def test_no_show_picker_is_available_on_each_session(self):
        self.assertIn('macro no_show_panel(seminar_session)', self.source)
        self.assertIn('미연락 불참', self.source)
        self.assertIn('/no_shows', self.source)
        self.assertIn('{{ no_show_panel(thu) }}', self.source)
        self.assertIn('{{ no_show_panel(mon) }}', self.source)

    def test_review_management_is_rendered_inside_each_session(self):
        self.assertIn('macro review_panel(seminar_session)', self.source)
        self.assertIn('{{ review_panel(mon) }}', self.source)
        self.assertIn('{{ review_panel(thu) }}', self.source)
        self.assertNotIn('id="seminar-reviews"', self.source)


if __name__ == '__main__':
    unittest.main()
