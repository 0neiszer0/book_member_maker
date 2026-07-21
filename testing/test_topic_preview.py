import unittest

from topic_preview import anonymous_topic_previews


class AnonymousTopicPreviewTests(unittest.TestCase):
    def test_removes_all_identity_fields(self):
        rows = [{
            'author_name': '홍길동',
            'department': '전자공학부',
            'student_id': '2022123456',
            'pin_code': '1234',
            'topics': [{'topic': '같은 선택을 반복한 이유는?', 'page': 'p.10', 'reference': '인용문'}],
        }]

        result = anonymous_topic_previews(rows)

        self.assertEqual(result, [{
            'topic': '같은 선택을 반복한 이유는?',
            'page': 'p.10',
            'reference': '인용문',
        }])
        rendered = repr(result)
        for private_value in ('홍길동', '전자공학부', '2022123456', '1234'):
            self.assertNotIn(private_value, rendered)

    def test_skips_invalid_or_empty_topics_and_limits_results(self):
        rows = [
            {'topics': None},
            {'topics': ['invalid', {'topic': '  '}, {'topic': '첫 번째'}]},
            {'topics': [{'topic': '두 번째'}]},
        ]

        self.assertEqual(
            anonymous_topic_previews(rows, limit=1),
            [{'topic': '첫 번째', 'page': '', 'reference': ''}],
        )


if __name__ == '__main__':
    unittest.main()
