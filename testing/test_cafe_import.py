import json
import shutil
import subprocess
import tempfile
import unittest
from datetime import date
from pathlib import Path

from infra.cafe_import import import_cafe as cafe


class CafeImportRuleTests(unittest.TestCase):
    names = ['장현준', '서효명']

    def test_review_title_keeps_only_the_book(self):
        self.assertEqual(cafe.review_title('[타인의 고통] 심리학과 21학번 장현준', self.names)[0], '타인의 고통')
        self.assertEqual(cafe.review_title('[변신] 외 5편 컴퓨터학부 22학번 장현준', self.names)[0], '변신 외 5편')
        self.assertEqual(cafe.review_title('『페스트』 의학과 22학번 서효명', self.names)[0], '페스트')
        self.assertEqual(cafe.review_title('불안 22학번 치의학과 장현준', self.names)[0], '불안')

    def test_redact_removes_names_and_student_years(self):
        self.assertEqual(cafe.redact('경제통상학부 24학번 서효명입니다', self.names), '경제통상학부 ○○○입니다')

    def test_cohort_line_never_contains_a_name(self):
        self.assertEqual(cafe.cohort('6기 장현준'), '6기 회원')
        self.assertEqual(cafe.cohort('5기김민지'), '5기 회원')
        self.assertEqual(cafe.cohort('북극곰11'), '기수 미상 회원')
        self.assertEqual(cafe.cohort('26기 배민주'), '기수 미상 회원')

    def test_session_date_from_titles(self):
        posted = date(2026, 1, 3)
        self.assertEqual(cafe.session_date('25.12.29 변신 외 6개 단편 발제문', posted), date(2025, 12, 29))
        self.assertEqual(cafe.session_date('1229 세미나-변신', posted), date(2025, 12, 29))
        self.assertEqual(cafe.session_date('1001_나는 소망한다_일지', date(2026, 10, 6)), date(2026, 10, 1))
        self.assertEqual(cafe.session_date('20260119 세미나', posted), date(2026, 1, 19))
        self.assertIsNone(cafe.session_date('[2026-9] 온기', posted))

    def test_history_match_prefers_date_then_book(self):
        history = [{'id': 'a', 'date': date(2026, 5, 4), 'key': cafe.norm('소유냐 존재냐')},
                   {'id': 'b', 'date': date(2026, 5, 7), 'key': cafe.norm('소유냐 존재냐')},
                   {'id': 'c', 'date': date(2026, 5, 11), 'key': cafe.norm('우리가 빛의 속도로 갈 수 없다면')}]
        self.assertEqual(cafe.match_history(history, date(2026, 5, 7), '', date(2026, 5, 7)), 'b')
        self.assertEqual(cafe.match_history(history, None, '소유냐 존재냐', date(2026, 5, 10)), 'b')
        self.assertIsNone(cafe.match_history(history, date(2026, 5, 9), '합동 세미나', date(2026, 5, 26)))
        self.assertIsNone(cafe.match_history(history, None, '불멸', date(2026, 5, 13)))

    def test_body_drops_cafe_chrome_and_comments(self):
        raw = '후기\n[\n\n제목\n6\n\n기 홍길동\n\n구독 1:1 채팅\n\n2025.11.29. 00:13\n\n조회 14\n\n댓글 0 URL 복사\n\n본문 한 줄\n클린봇\n\n댓글알림\n5기 누군가\n댓글 내용'
        self.assertEqual(cafe.clean_body(raw, []), '본문 한 줄')

    def test_wrapped_korean_lines_join_without_breaking_words(self):
        self.assertFalse(cafe.wrapped_at_space('생각해 본 적', '은 있었지만'))
        self.assertTrue(cafe.wrapped_at_space('과연 우리는', '타인의 고통을'))


class CafeImportPlanTests(unittest.TestCase):
    def test_skipped_boards_never_reach_the_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows = ['menuid,board,articleid,title,date,author,comments,attachments,status',
                    '13,회계장부,1,장부,2025.01.01. 10:00,1기 홍길동,0,,ok',
                    '23,총회 회의록,2,회의록,2025.01.01. 10:00,1기 홍길동,0,,ok']
            (root / 'index.csv').write_text('\n'.join(rows), encoding='utf-8')
            plan, skipped = cafe.build_plan(root, [], 'hold')
            self.assertEqual(plan, [])
            self.assertEqual(sum(skipped.values()), 2)


if __name__ == '__main__':
    unittest.main()


class CafeImportApplyTests(unittest.TestCase):
    def test_apply_is_resumable_attaches_held_images_later_and_rolls_back(self):
        import io
        import os
        from types import SimpleNamespace
        from unittest.mock import patch
        from PIL import Image
        from testing._fake_supabase import FakeSupabase

        class Bucket:
            def __init__(self):
                self.files = {}

            def upload(self, path, content, options):
                self.files[path] = content

            def remove(self, paths):
                for path in paths:
                    self.files.pop(path, None)

        db = FakeSupabase({
            'boards': [{'id': 'free-id', 'slug': 'free'}],
            'members': [{'id': 99, 'social_id': cafe.SYSTEM_SOCIAL_ID}],
            'posts': [], 'post_attachments': []})
        bucket = Bucket()
        db.storage = SimpleNamespace(from_=lambda name: bucket)
        insert = db.table

        def table(name):
            query = insert(name)
            original = query.insert

            def add_id(payload):
                payload = dict(payload, id=f'{name}-{len(db.rows[name]) + 1}')
                return original(payload)
            query.insert = add_id
            return query
        db.table = table
        with tempfile.TemporaryDirectory() as tmp:
            image = Path(tmp) / 'a.png'
            buffer = io.BytesIO()
            Image.new('RGB', (8, 8)).save(buffer, format='PNG')
            image.write_bytes(buffer.getvalue())
            state = Path(tmp) / 'state.json'
            held = {'source': '16/1', 'board': 'free', 'title': 't', 'content': '사진은 나중에', 'created_at': '2025-01-01T00:00:00+09:00',
                    'history_id': None, 'images': []}
            env = {'SUPABASE_URL': 'http://fake', 'SUPABASE_SERVICE_KEY': 'fake'}
            with patch.dict(os.environ, env), patch('supabase.create_client', return_value=db):
                cafe.apply([held], state)
                cafe.apply([held], state)
                self.assertEqual(len(db.rows['posts']), 1)
                cafe.apply([dict(held, content='본문', images=[str(image)])], state)
                self.assertEqual(db.rows['posts'][0]['content'], '본문')
                self.assertEqual(len(db.rows['post_attachments']), 1)
                self.assertEqual(len(bucket.files), 1)
                self.assertEqual(db.rows['posts'][0]['author_id'], 99)
                cafe.rollback(state)
            self.assertEqual(db.rows['posts'], [])
            self.assertEqual(bucket.files, {})
