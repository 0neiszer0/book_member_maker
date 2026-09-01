import unittest
from pathlib import Path

from member_identity import (
    duplicate_student_id_values,
    member_student_id_conflicts,
    normalize_member_student_id,
    valid_member_student_id,
)


ROOT = Path(__file__).resolve().parents[1]


class MemberIdentityTests(unittest.TestCase):
    def test_student_id_normalization_and_validation(self):
        self.assertEqual(normalize_member_student_id(" 2026 000001 "), "2026000001")
        self.assertTrue(valid_member_student_id("2026000001"))
        self.assertTrue(valid_member_student_id(""))
        self.assertFalse(valid_member_student_id("2026-A"))
        self.assertFalse(valid_member_student_id("123"))

    def test_duplicate_values_ignore_blank_ids(self):
        members = [
            {"id": 1, "student_id": "2026000001"},
            {"id": 2, "student_id": "2026 000001"},
            {"id": 3, "student_id": ""},
            {"id": 4, "student_id": None},
        ]
        self.assertEqual(duplicate_student_id_values(members), {"2026000001"})

    def test_conflict_allows_current_row_but_blocks_another_member(self):
        members = [
            {"id": 10, "student_id": "2026000001"},
            {"id": 20, "student_id": "2026000002"},
        ]
        self.assertFalse(member_student_id_conflicts(members, "2026000001", 10))
        self.assertTrue(member_student_id_conflicts(members, "2026000002", 10))

    def test_admin_page_surfaces_duplicates_without_encouraging_merge(self):
        template = (ROOT / "templates" / "records_members.html").read_text(
            encoding="utf-8"
        )
        source = (ROOT / "app.py").read_text(encoding="utf-8")
        self.assertIn("중복 학번만 보기", template)
        self.assertIn("학번만 같다는 이유로 합치면 안 됩니다.", template)
        self.assertIn('data-duplicate="', template)
        self.assertIn("_member_student_id_conflict", source)
        self.assertIn("이미 다른 회원에게 등록된 학번입니다.", source)


if __name__ == "__main__":
    unittest.main()
