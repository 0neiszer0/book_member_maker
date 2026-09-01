import json
import re
import tomllib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CANONICAL = ROOT / "supabase" / "migrations"
LEGACY = ROOT / "migrations"


REMOTE_MIGRATION_FILES = {
    "20260508013131_005_special_events.sql": "005_special_events.sql",
    "20260511013544_seminar_voting_window.sql": "006_seminar_voting_window.sql",
    "20260511093654_topic_admission_year.sql": "007_topic_admission_year.sql",
    "20260720133337_topic_limit_and_student_id.sql": "010_topic_limit.sql",
    "20260720150337_enforce_topic_submission_identity.sql": "011_topic_submission_identity.sql",
    "20260720154532_integrated_workflow_boards.sql": "012_integrated_workflow_boards.sql",
    "20260721021907_board_foreign_key_indexes.sql": "013_board_foreign_key_indexes.sql",
    "20260721023027_secure_brick_book_review_target.sql": "014_secure_brick_book_review_target.sql",
    "20260721032138_weekly_seminar_absences.sql": "015_weekly_seminar_absences.sql",
    "20260721033935_seminar_workflow_indexes.sql": "016_seminar_workflow_indexes.sql",
    "20260721151404_thursday_first_seminar_cycles.sql": "017_thursday_first_seminar_cycles.sql",
    "20260723024542_bug_reports.sql": "018_bug_reports.sql",
    "20260723025940_server_only_rls.sql": "019_server_only_rls.sql",
    "20260723030121_revoke_public_schema_usage.sql": "020_revoke_public_schema_usage.sql",
    "20260724023229_engagement_workflow.sql": "021_engagement_workflow.sql",
    "20260724023752_split_engagement_image_buckets.sql": "022_split_engagement_image_buckets.sql",
    "20260724023817_retire_transitional_image_bucket.sql": "023_retire_transitional_image_bucket.sql",
    "20260724024125_engagement_foreign_key_indexes.sql": "024_engagement_foreign_key_indexes.sql",
    "20260724024320_merge_active_book_suggestions.sql": "025_merge_active_book_suggestions.sql",
    "20260724040758_add_seminar_no_shows.sql": "026_seminar_no_shows.sql",
    "20260806093535_group_pair_restrictions.sql": "027_group_pair_restrictions.sql",
    "20260813082022_recruitment_results.sql": "028_recruitment_results.sql",
    "20260814032145_default_two_topics.sql": "029_default_two_topics.sql",
}


class SupabaseMigrationBaselineTests(unittest.TestCase):
    def test_cli_is_pinned_and_local_config_matches_server_only_postgres_15(self):
        package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
        self.assertEqual(package["devDependencies"]["supabase"], "2.116.0")

        with (ROOT / "supabase" / "config.toml").open("rb") as config_file:
            config = tomllib.load(config_file)
        self.assertEqual(config["db"]["major_version"], 15)
        self.assertFalse(config["api"]["auto_expose_new_tables"])

    def test_canonical_timestamps_match_remote_history(self):
        actual = {path.name for path in CANONICAL.glob("*.sql")}
        expected = set(REMOTE_MIGRATION_FILES) | {
            "20260501000000_legacy_schema_baseline.sql",
            "20260508020003_005_special_events.sql",
            "20260901134512_secure_topic_edit_identity.sql",
        }
        self.assertEqual(actual, expected)
        self.assertTrue(all(re.fullmatch(r"[0-9]{14}_[a-z0-9_]+\.sql", name) for name in actual))

    def test_remote_migrations_are_exact_legacy_copies(self):
        for canonical_name, legacy_name in REMOTE_MIGRATION_FILES.items():
            with self.subTest(canonical=canonical_name):
                canonical = (CANONICAL / canonical_name).read_text(encoding="utf-8").strip()
                legacy = (LEGACY / legacy_name).read_text(encoding="utf-8").strip()
                self.assertEqual(canonical, legacy)

    def test_baseline_contains_schema_only_server_side_foundation(self):
        baseline = (CANONICAL / "20260501000000_legacy_schema_baseline.sql").read_text(
            encoding="utf-8"
        )
        for table in (
            "members",
            "history",
            "attendance",
            "topic_events",
            "topic_submissions",
            "seminar_room_posts",
            "seminar_room_settings",
        ):
            self.assertRegex(
                baseline.lower(),
                rf"create\s+table\s+(?:if\s+not\s+exists\s+)?public\.{table}\b",
            )

        for table in ("members", "history", "topic_submissions"):
            self.assertIn(f"alter table public.{table} enable row level security", baseline.lower())
            self.assertIn(f"revoke all on table public.{table} from public, anon, authenticated", baseline.lower())

        for sensitive_table in (
            "members",
            "history",
            "attendance",
            "topic_submissions",
            "recruitment_applicants",
        ):
            self.assertNotRegex(
                baseline.lower(),
                rf"insert\s+into\s+(?:public\.)?{sensitive_table}\b",
            )

        self.assertIn("security invoker", baseline.lower())
        self.assertIn("set search_path = ''", baseline.lower())
        self.assertIn("세미나 출석 투표 시스템", baseline)
        self.assertIn("책 먹는 호반우", baseline)
        self.assertNotIn("�", baseline)

    def test_duplicate_remote_special_event_entry_is_an_explicit_noop_marker(self):
        marker = (CANONICAL / "20260508020003_005_special_events.sql").read_text(
            encoding="utf-8"
        )
        self.assertIn("second migration", marker)
        self.assertNotIn("create table", marker.lower())


if __name__ == "__main__":
    unittest.main()
