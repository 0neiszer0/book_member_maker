import unittest
from pathlib import Path

from topic_credentials import (
    generate_topic_edit_token,
    legacy_pin_matches,
    topic_edit_token_digest,
    topic_edit_token_matches,
    topic_request_fingerprint,
)


class TopicCredentialTests(unittest.TestCase):
    def test_generated_token_has_high_entropy_and_only_digest_is_stable(self):
        first = generate_topic_edit_token()
        second = generate_topic_edit_token()
        self.assertNotEqual(first, second)
        self.assertGreaterEqual(len(first), 40)

        digest = topic_edit_token_digest(first, "pepper")
        self.assertEqual(len(digest), 64)
        self.assertNotIn(first, digest)
        self.assertTrue(topic_edit_token_matches(digest, first, "pepper"))
        self.assertFalse(topic_edit_token_matches(digest, first, "other-pepper"))
        self.assertFalse(topic_edit_token_matches(digest, second, "pepper"))

    def test_legacy_pin_compatibility_only_accepts_four_digits(self):
        self.assertTrue(legacy_pin_matches("1234", "1234"))
        self.assertFalse(legacy_pin_matches("1234", "0000"))
        self.assertFalse(legacy_pin_matches("MEMBER", "MEMBER"))
        self.assertFalse(legacy_pin_matches("12345", "12345"))

    def test_request_fingerprint_hides_address_and_is_event_scoped(self):
        first = topic_request_fingerprint("192.0.2.10", "event-1", "pepper")
        second = topic_request_fingerprint("192.0.2.10", "event-2", "pepper")
        self.assertEqual(len(first), 64)
        self.assertNotIn("192.0.2.10", first)
        self.assertNotEqual(first, second)


class TopicCredentialIntegrationContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).resolve().parents[1]

    def test_new_guest_credentials_are_hashed_and_legacy_pin_is_only_compatibility(self):
        source = (self.root / "app.py").read_text(encoding="utf-8")
        self.assertIn("topic_edit_token_digest", source)
        self.assertIn("topic_edit_token_matches", source)
        self.assertIn("legacy_pin_matches", source)
        self.assertNotIn("existing_record['pin_code'] !=", source)
        self.assertIn("'pin_code': 'TOKEN'", source)

    def test_public_form_stores_strong_code_locally_without_putting_it_in_url(self):
        template = (self.root / "templates" / "topic_submit.html").read_text(
            encoding="utf-8"
        )
        self.assertIn("edit_credential", template)
        self.assertIn("localStorage.setItem", template)
        self.assertIn("function readStoredCredential", template)
        self.assertIn("function storeCredential", template)
        self.assertIn('id="issuedCredential"', template)
        self.assertNotIn('pattern="[0-9]{4}"', template)
        self.assertNotIn("edit_token=", template)

    def test_additive_migration_keeps_legacy_pin_and_protects_attempt_log(self):
        migration = (
            self.root
            / "supabase"
            / "migrations"
            / "20260901134512_secure_topic_edit_identity.sql"
        ).read_text(encoding="utf-8").lower()
        self.assertIn("add column if not exists member_id", migration)
        self.assertIn("add column if not exists edit_token_hash", migration)
        self.assertIn("'legacy_pin'", migration)
        self.assertNotIn("drop column pin_code", migration)
        self.assertIn(
            "alter table public.topic_edit_attempts enable row level security",
            migration,
        )
        self.assertIn("from public, anon, authenticated", migration)


if __name__ == "__main__":
    unittest.main()
