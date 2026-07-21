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
        self.assertIn('.chip{display:inline-flex;flex:none;', self.source)

    def test_bulk_absence_picker_is_present(self):
        self.assertIn('여러 명 한 번에 선택', self.source)
        self.assertIn('class="absence-checkbox"', self.source)
        self.assertIn('member_ids:memberIds', self.source)


if __name__ == '__main__':
    unittest.main()
