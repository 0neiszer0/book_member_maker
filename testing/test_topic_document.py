import unittest
from pathlib import Path
from zipfile import ZipFile
from xml.etree import ElementTree as ET

from topic_document import admission_year_short, number_topic_submissions, topic_submitter_identity


ROOT = Path(__file__).resolve().parents[1]


class TopicDocumentIdentityTests(unittest.TestCase):
    def test_includes_department_short_year_and_name(self):
        identity = topic_submitter_identity({
            'department': '전자공학부',
            'admission_year': '2022',
            'author_name': '박민서',
        })
        self.assertEqual(identity['department_and_year'], '전자공학부 22')
        self.assertEqual(identity['full_label'], '전자공학부 22 박민서')

    def test_derives_year_from_student_id_for_legacy_submission(self):
        submission = {'student_id': '2022123456'}
        self.assertEqual(admission_year_short(submission), '22')

    def test_numbers_topics_across_submitters_without_resetting(self):
        submissions = [
            {'author_name': '가람', 'topics': [{'topic': '질문 A'}, {'topic': '질문 B'}]},
            {'author_name': '나래', 'topics': [{'topic': '질문 C'}, {'topic': '질문 D'}]},
        ]

        numbered = number_topic_submissions(submissions)

        self.assertEqual(
            [[topic['number'] for topic in sub['topics']] for sub in numbered],
            [[1, 2], [3, 4]],
        )
        self.assertNotIn('number', submissions[0]['topics'][0])

    def test_word_template_uses_global_topic_number(self):
        with ZipFile(ROOT / 'templates' / 'template.docx') as archive:
            root = ET.fromstring(archive.read('word/document.xml'))
        namespace = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
        paragraphs = [
            ''.join(node.text or '' for node in paragraph.findall('.//w:t', namespace))
            for paragraph in root.findall('.//w:p', namespace)
        ]
        self.assertTrue(any('{{ topic.number }}.' in text for text in paragraphs))
        self.assertFalse(any('{{ loop.index }}.' in text for text in paragraphs))


class TopicLimitContractTests(unittest.TestCase):
    def test_default_limit_is_two_in_app_template_and_migration(self):
        app_source = (ROOT / 'app.py').read_text(encoding='utf-8')
        template_source = (ROOT / 'templates' / 'topic_submit.html').read_text(encoding='utf-8')
        migration_source = (ROOT / 'migrations' / '029_default_two_topics.sql').read_text(encoding='utf-8')

        self.assertIn("get('topic_limit') or 2", app_source)
        self.assertIn('let topicLimit = 2;', template_source)
        self.assertIn('ALTER COLUMN topic_limit SET DEFAULT 2', migration_source)
        self.assertIn('submission.topic_limit = 1', migration_source)
        self.assertIn("CURRENT_DATE - INTERVAL '7 days'", migration_source)


if __name__ == '__main__':
    unittest.main()
