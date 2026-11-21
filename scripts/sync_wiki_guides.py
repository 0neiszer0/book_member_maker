#!/usr/bin/env python3
"""Idempotently push the member/officer wiki guides into the openNamu wiki.

Reads the NamuMark sources under ``content/wiki_guides`` and writes them through
``wiki_engine.OpenNamu`` (configured from ``WIKI_UPSTREAM``, ``WIKI_DATABASE``
and ``WIKI_IDENTITY_SECRET``). Each page is skipped when its content already
matches, and the officer home page is only touched when the guide link is
missing — so re-running the script is always safe.

Usage:
    python scripts/sync_wiki_guides.py --dry-run
    python scripts/sync_wiki_guides.py --apply --actor-member-id 7
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
GUIDES_DIR = REPO_ROOT / "content" / "wiki_guides"

MEMBER_TITLE = "사이트 이용 안내"
MEMBER_SOURCE = GUIDES_DIR / "member_guide.namu"

OFFICER_TITLE = "운영진:운영 안내"
OFFICER_SOURCE = GUIDES_DIR / "officer_guide.namu"

OFFICER_HOME_TITLE = "운영진:대문"
OFFICER_HOME_SECTION = "업무별 문서"
OFFICER_HOME_LINK = "[[운영진:운영 안내|사이트 운영 매뉴얼 (바로가기 포함)]]"

MEMBER_SUMMARY = "사이트 이용 안내를 위키 가이드로 갱신"
OFFICER_SUMMARY = "운영진 운영 안내를 위키 가이드로 갱신"
OFFICER_HOME_SUMMARY = "운영 안내 바로가기 추가"


def normalize(text: str) -> str:
    """Normalize line endings so comparison is insensitive to CRLF/LF."""
    return (text or "").replace("\r\n", "\n").replace("\r", "\n")


def read_source(path: Path) -> str:
    return normalize(path.read_text(encoding="utf-8"))


def content_equal(left: str, right: str) -> bool:
    """Compare stored vs. file content, ignoring trailing newline noise."""
    return normalize(left).rstrip("\n") == normalize(right).rstrip("\n")


def build_engine(env=None):
    """Build an OpenNamu client from environment configuration."""
    from wiki_engine import OpenNamu
    env = env if env is not None else os.environ
    return OpenNamu(env["WIKI_UPSTREAM"], env["WIKI_DATABASE"], env["WIKI_IDENTITY_SECRET"])


def ensure_officer_home_link(source: str) -> tuple[str, bool]:
    """Return ``(updated_source, changed)``.

    Inserts the guide link under the ``업무별 문서`` section when the page does
    not already link to ``운영진:운영 안내``. Never duplicates an existing link.
    """
    if "[[운영진:운영 안내" in source:
        return source, False

    lines = normalize(source).split("\n")
    heading = f"== {OFFICER_HOME_SECTION} =="
    for index, line in enumerate(lines):
        if line.strip() == heading:
            insert_at = index + 1
            while insert_at < len(lines) and not lines[insert_at].strip():
                insert_at += 1
            lines.insert(insert_at, OFFICER_HOME_LINK)
            return "\n".join(lines), True

    # No matching section: append the link at the end, preceded by a blank line.
    if lines and lines[-1].strip():
        lines.append("")
    lines.append(OFFICER_HOME_LINK)
    return "\n".join(lines), True


def sync(engine, actor_member_id: int, dry_run: bool = False) -> list[dict]:
    """Synchronize both guide pages and the officer-home link.

    Every page is read before writing, so a repeated run is a no-op whenever the
    stored content already matches. Returns a list of action descriptions.
    """
    actions: list[dict] = []
    with engine.user(actor_member_id) as client:
        member_source = read_source(MEMBER_SOURCE)
        doc = engine.document(client, MEMBER_TITLE)
        if not content_equal(doc.get("source", ""), member_source):
            action = "update" if doc.get("exists") else "create"
            actions.append({"title": MEMBER_TITLE, "action": action})
            if not dry_run:
                engine.save(client, MEMBER_TITLE, member_source, MEMBER_SUMMARY, doc.get("version", "0"))

        officer_source = read_source(OFFICER_SOURCE)
        doc = engine.document(client, OFFICER_TITLE)
        if not content_equal(doc.get("source", ""), officer_source):
            action = "update" if doc.get("exists") else "create"
            actions.append({"title": OFFICER_TITLE, "action": action})
            if not dry_run:
                engine.save(client, OFFICER_TITLE, officer_source, OFFICER_SUMMARY, doc.get("version", "0"))

        doc = engine.document(client, OFFICER_HOME_TITLE)
        if not doc.get("exists"):
            actions.append({"title": OFFICER_HOME_TITLE, "action": "skip", "reason": "운영진:대문 문서가 없음"})
        else:
            updated, changed = ensure_officer_home_link(doc.get("source", ""))
            if changed:
                actions.append({"title": OFFICER_HOME_TITLE, "action": "update"})
                if not dry_run:
                    engine.save(client, OFFICER_HOME_TITLE, updated, OFFICER_HOME_SUMMARY, doc.get("version", "0"))
    return actions


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Push member/officer wiki guides idempotently.")
    parser.add_argument("--dry-run", action="store_true", help="read and report without writing")
    parser.add_argument("--apply", action="store_true", help="write changes to the wiki")
    parser.add_argument("--actor-member-id", type=int, default=7,
                        help="bridge member id used for wiki edits (default: 7)")
    args = parser.parse_args(argv)

    if args.dry_run and args.apply:
        parser.error("--dry-run and --apply are mutually exclusive")
    if not args.dry_run and not args.apply:
        parser.error("choose --dry-run or --apply")

    engine = build_engine()
    actions = sync(engine, args.actor_member_id, dry_run=args.dry_run)
    if not actions:
        print("위키 가이드가 이미 최신 상태입니다.")
        return 0
    for action in actions:
        if action["action"] == "skip":
            print(f"[skip] {action['title']} ({action.get('reason', '')})")
        else:
            label = "dry-run" if args.dry_run else action["action"]
            print(f"[{label}] {action['title']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
