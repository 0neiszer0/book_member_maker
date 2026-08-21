import importlib.util
import sys
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


if importlib.util.find_spec('requests') is None:
    requests_stub = types.ModuleType('requests')
    requests_stub.Session = object
    requests_stub.RequestException = Exception
    sys.modules['requests'] = requests_stub

if importlib.util.find_spec('bs4') is None:
    bs4_stub = types.ModuleType('bs4')
    bs4_stub.BeautifulSoup = object
    sys.modules['bs4'] = bs4_stub

from seminar_rooms import (  # noqa: E402
    crawl,
    extract_club_name,
    get_room_from_title,
    is_seminar_post,
    parse_dates_from_title,
)


ROOT = Path(__file__).resolve().parents[1]


class SeminarRoomTitleParsingTests(unittest.TestCase):
    def assert_dates(self, title, expected, fallback_year=2026):
        actual = parse_dates_from_title(title, fallback_year)
        self.assertEqual([item.isoformat() for item in actual], expected)

    def test_repeated_month_can_be_omitted(self):
        self.assert_dates(
            '[책 먹는 호반우] 2026년 8월 26일(수), 27일(목), 28일(금) '
            '세미나실(통일) 대여 신청',
            ['2026-08-26', '2026-08-27', '2026-08-28'],
        )

    def test_common_real_world_variants(self):
        cases = {
            '[크누모빌리티] 2026년 8월 29일(토), 30일(일), 31일(월) '
            '세미나실(통일) 대여 신청':
                ['2026-08-29', '2026-08-30', '2026-08-31'],
            '[현시연]2026 7월 3,4일 (금,토) 세미나실(백호) 대여 신청':
                ['2026-07-03', '2026-07-04'],
            '[모임] 2026년 7월 3, 4, 5일 세미나실(백호) 대여 신청':
                ['2026-07-03', '2026-07-04', '2026-07-05'],
            '[신망애] 7월 4일, 5일, 6일 세미나실(민주) 대여 신청':
                ['2026-07-04', '2026-07-05', '2026-07-06'],
            '[뜨람] 2026년 6월 1일(월), 2일(화), 4일(목) '
            '세미나실 백호 대여 신청':
                ['2026-06-01', '2026-06-02', '2026-06-04'],
            '[팔레트] 2026년 9월 9일(수), 9월 10일(목) '
            '세미나실(민주) 대여 신청':
                ['2026-09-09', '2026-09-10'],
        }
        for title, expected in cases.items():
            with self.subTest(title=title):
                self.assert_dates(title, expected)

    def test_ranges_expand_to_every_day(self):
        cases = {
            '[사우회] 2026년 9월 11일(금)~13일(일) 세미나실(민주) 대여 신청':
                ['2026-09-11', '2026-09-12', '2026-09-13'],
            '[KOMO] 2026년 09월 11일 (금) ~ 9월 13 (일) '
            '세미나실 (통일) 대여신청':
                ['2026-09-11', '2026-09-12', '2026-09-13'],
            '[코스모스]9/13~9/14 백호관 세미나실(백호) 대여 신청':
                ['2026-09-13', '2026-09-14'],
            '[연말모임] 12월 30일~1월 2일 세미나실(통일) 대여 신청':
                ['2026-12-30', '2026-12-31', '2027-01-01', '2027-01-02'],
        }
        for title, expected in cases.items():
            with self.subTest(title=title):
                self.assert_dates(title, expected)

    def test_numeric_and_invalid_dates(self):
        self.assert_dates(
            '[모임] 2026.8.26 / 8.27 / 8.28 세미나실: 민주 대여 신청',
            ['2026-08-26', '2026-08-27', '2026-08-28'],
        )
        self.assert_dates('[모임] 2월 30일 세미나실(민주) 대여 신청', [])

    def test_room_prefers_value_next_to_seminar_room(self):
        title = '[코스모스] 9/14(월) 백호관 세미나실(통일) 대여 신청'
        self.assertEqual(get_room_from_title(title), '통일')
        self.assertEqual(get_room_from_title('[모임] 8/26 세미나실 : 민주 신청'), '민주')
        self.assertEqual(get_room_from_title('[모임] 8/26 백호 세미나실 신청'), '백호')

    def test_club_bracket_variants_and_post_detection(self):
        title = ' 【 책 먹는 호반우 】 8월 26일 세미나실(통일) 신청'
        self.assertEqual(extract_club_name(title), '책 먹는 호반우')
        self.assertTrue(is_seminar_post(title))
        self.assertFalse(is_seminar_post('공용공간 백호관 세미나실 안내'))


class SeminarRoomNavigationTests(unittest.TestCase):
    def test_sidebar_has_dedicated_reservation_tab(self):
        sidebar = (ROOT / 'templates' / '_admin_sidebar.html').read_text(encoding='utf-8')
        self.assertIn("url_for('admin_seminar_rooms')", sidebar)
        self.assertIn('>세미나실 예약</a>', sidebar)
        self.assertIn("endpoint == 'admin_seminar_rooms'", sidebar)

    def test_admin_overview_has_reservation_shortcut(self):
        overview = (ROOT / 'templates' / 'admin_overview.html').read_text(encoding='utf-8')
        self.assertIn("url_for('admin_seminar_rooms')", overview)
        self.assertIn('세미나실 예약 현황', overview)

    def test_admin_view_reparses_old_cached_titles(self):
        app_source = (ROOT / 'app.py').read_text(encoding='utf-8')
        self.assertIn("reparsed_dates = parse_dates_from_title", app_source)
        self.assertIn("post['dates'] = [item.isoformat()", app_source)


class SeminarRoomCacheRepairTests(unittest.TestCase):
    def test_terminal_cache_is_reparsed_without_detail_fetch(self):
        title = (
            '[책 먹는 호반우] 2026년 8월 26일(수), 27일(목), 28일(금) '
            '세미나실(통일) 대여 신청'
        )

        class FakeSupabase:
            def __init__(self):
                self.upserts = []

            def table(self, _name):
                parent = self

                class Query:
                    mode = None

                    def select(self, _columns):
                        self.mode = 'select'
                        return self

                    def upsert(self, rows, on_conflict=None):
                        self.mode = 'upsert'
                        parent.upserts.extend(rows)
                        return self

                    def execute(self):
                        if self.mode == 'select':
                            return SimpleNamespace(data=[{
                                'wr_id': 3630,
                                'title': title,
                                'club_name': '책 먹는 호반우',
                                'room': '통일',
                                'dates': ['2026-08-26'],
                                'status': 'approved',
                                'post_url': 'https://example.test/3630',
                            }])
                        return SimpleNamespace(data=[])

                return Query()

        fake_db = FakeSupabase()
        listing_response = SimpleNamespace(
            text='<html></html>', status_code=200, url='https://example.test/list'
        )
        listing = [(3630, title, 'https://example.test/3630')]

        with patch('seminar_rooms.make_session', return_value=object()), \
                patch('seminar_rooms.fetch_with_challenge', return_value=listing_response), \
                patch('seminar_rooms.parse_listing', return_value=listing):
            result = crawl(fake_db, max_pages=1)

        self.assertEqual(result['reparsed_terminal'], 1)
        self.assertEqual(len(fake_db.upserts), 1)
        self.assertEqual(
            fake_db.upserts[0]['dates'],
            ['2026-08-26', '2026-08-27', '2026-08-28'],
        )


if __name__ == '__main__':
    unittest.main()
