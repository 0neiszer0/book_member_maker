import unittest

from topic_document import admission_year_short, topic_submitter_identity


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


if __name__ == '__main__':
    unittest.main()
