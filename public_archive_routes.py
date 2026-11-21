"""Public club archive (/archive) and member-only pre-seminar materials (/pre-seminar)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from flask import abort, make_response, render_template, request

CONTENT_DIR = Path(__file__).resolve().parent / "content"
PUBLIC_ARCHIVE_PATH = CONTENT_DIR / "public_archive.json"
PRE_SEMINAR_PATH = CONTENT_DIR / "member_pre_seminar_materials.json"

_JSON_CACHE: dict[Path, tuple[tuple[int, int], dict[str, Any]]] = {}


def _load_json_snapshot(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    st = path.stat()
    sig = (st.st_mtime_ns, st.st_size)
    cached = _JSON_CACHE.get(path)
    if cached and cached[0] == sig:
        return cached[1]
    data = json.loads(path.read_text(encoding="utf-8"))
    _JSON_CACHE[path] = (sig, data)
    return data


def _book_matches_query(book: dict[str, Any], needle: str) -> bool:
    if not needle:
        return True
    haystacks = [
        book.get("title", ""),
        book.get("author", ""),
        book.get("genre", ""),
        book.get("semester", ""),
        book.get("semester_label", ""),
        book.get("date", ""),
        book.get("status_note", ""),
    ]
    for grp in book.get("prompts", []):
        for q in grp.get("questions", []):
            haystacks.append(q.get("question", ""))
            haystacks.append(q.get("reference", ""))
    for sec in book.get("discussion_sections", []):
        for turn in sec.get("turns", []):
            haystacks.append(turn.get("text", ""))
    joined = "\n".join(haystacks).lower()
    return needle.lower() in joined


def render_public_landing():
    archive = _load_json_snapshot(PUBLIC_ARCHIVE_PATH)
    books = archive.get("books", [])
    return render_template(
        "public_landing.html",
        semester_count=len(archive.get("semesters", [])),
        book_count=len(books),
        recent_books=sorted(books, key=lambda b: b.get("date") or "", reverse=True)[:6],
        programs=archive.get("special_programs", []),
    )


def init_public_archive_routes(app, login_required):
    @app.get("/archive")
    def public_archive():
        archive = _load_json_snapshot(PUBLIC_ARCHIVE_PATH)
        all_books = archive.get("books", [])
        raw_semesters = archive.get("semesters", [])

        selected_semester = (request.args.get("semester") or "").strip()
        query = (request.args.get("q") or "").strip()

        counts_by_sem: dict[str, int] = {}
        for book in all_books:
            sid = book.get("semester", "")
            counts_by_sem[sid] = counts_by_sem.get(sid, 0) + 1

        semesters = [
            {
                **sem,
                "count": counts_by_sem.get(sem.get("id", ""), 0),
            }
            for sem in raw_semesters
        ]

        filtered = [
            book
            for book in all_books
            if (not selected_semester or book.get("semester") == selected_semester)
            and _book_matches_query(book, query)
        ]

        return render_template(
            "public_archive.html",
            club_name=archive.get("club_name", "경북대학교 중앙 독서동아리 책 먹는 호반우"),
            semesters=semesters,
            selected_semester=selected_semester,
            query=query,
            books=filtered,
            total_books=len(all_books),
            special_programs=archive.get("special_programs", []),
        )

    @app.get("/archive/<slug>")
    def public_archive_book(slug: str):
        archive = _load_json_snapshot(PUBLIC_ARCHIVE_PATH)
        all_books = archive.get("books", [])

        idx = next((i for i, b in enumerate(all_books) if b.get("slug") == slug), None)
        if idx is None:
            abort(404)

        book = all_books[idx]
        prev_book = all_books[idx - 1] if idx > 0 else None
        next_book = all_books[idx + 1] if idx + 1 < len(all_books) else None

        return render_template(
            "public_archive_book.html",
            book=book,
            prev_book=prev_book,
            next_book=next_book,
        )

    def _render_pre_seminar(selected_slug: str | None = None):
        payload = _load_json_snapshot(PRE_SEMINAR_PATH)
        all_books = payload.get("books", [])
        semesters = payload.get("semesters", [])

        if selected_slug is not None:
            active_book = next((b for b in all_books if b.get("slug") == selected_slug), None)
            if active_book is None:
                abort(404)
        else:
            req_slug = (request.args.get("book") or "").strip()
            if req_slug:
                active_book = next((b for b in all_books if b.get("slug") == req_slug), None)
                if active_book is None:
                    abort(404)
            else:
                active_book = all_books[0] if all_books else None

        selected_semester = (request.args.get("semester") or "").strip()
        grouped: list[dict[str, Any]] = []
        for sem in semesters:
            sid = sem.get("id", "")
            if selected_semester and sid != selected_semester:
                continue
            sem_books = [b for b in all_books if b.get("semester") == sid]
            if sem_books:
                grouped.append({**sem, "books": sem_books})

        resp = make_response(
            render_template(
                "member_pre_seminar.html",
                description=payload.get("description", ""),
                semesters=semesters,
                selected_semester=selected_semester,
                grouped_books=grouped,
                all_books=all_books,
                active_book=active_book,
            )
        )
        resp.headers["Cache-Control"] = "private, no-store"
        return resp

    @app.get("/pre-seminar")
    @login_required(role="ANY")
    def member_pre_seminar():
        return _render_pre_seminar(None)

    @app.get("/pre-seminar/<slug>")
    @login_required(role="ANY")
    def member_pre_seminar_book(slug: str):
        return _render_pre_seminar(slug)
