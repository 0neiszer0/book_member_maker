"""Public club archive (/archive) and member-only pre-seminar materials (/pre-seminar)."""

from __future__ import annotations

import json
import re
import unicodedata
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from flask import abort, jsonify, make_response, redirect, render_template, request, session, url_for
from member_notifications import check_csrf

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



_INLINE = re.compile(r"\[([^]\n]+)\]\(([^)\s]+)\)|https?://[^\s<>]+|\*\*([^*\n]+)\*\*|\*([^*\n]+)\*|`([^`\n]+)`", re.I)


def _parse_md_inline(text):
    runs = []
    cursor = 0
    for match in _INLINE.finditer(text):
        if match.start() > cursor:
            runs.append({"text": text[cursor:match.start()]})
        token = match.group(0)
        label, href, bold, italic, code = match.groups()
        if label is not None:
            runs.append({"text": label, "href": href} if re.match(r"^https?://", href, re.I) else {"text": token})
        elif token.lower().startswith(("http://", "https://")):
            url = token.rstrip(".,;:!?")
            runs.append({"text": url, "href": url})
            if len(url) < len(token):
                runs.append({"text": token[len(url):]})
        else:
            value, style = (bold, "strong") if bold is not None else ((italic, "em") if italic is not None else (code, "code"))
            runs.append({"text": value, style: True})
        cursor = match.end()
    if cursor < len(text):
        runs.append({"text": text[cursor:]})
    return runs


def parse_pre_seminar_markdown(markdown_text: str) -> dict:
    sections, references, seen = [], [], set()
    current = None
    paragraph = []
    def section():
        nonlocal current
        if current is None:
            current = {"heading": "개요", "level": 2, "items": []}
            sections.append(current)
        return current
    def runs(text):
        result = _parse_md_inline(text)
        for run in result:
            url = run.get("href")
            if url and url not in seen:
                seen.add(url)
                references.append({"title": run["text"], "url": url})
        return result
    def flush():
        if paragraph:
            section()["items"].append({"type": "p", "runs": runs(" ".join(paragraph))})
            paragraph.clear()
    for raw in (markdown_text or "").splitlines():
        line = raw.strip()
        heading = re.match(r"^(#{1,3})\s+(.+?)\s*#*\s*$", line)
        item = re.match(r"^(?:[-*]\s+|\d+\.\s+)(.*)$", line)
        quote = re.match(r"^>\s?(.*)$", line)
        if not line:
            flush()
        elif heading:
            flush()
            current = {"heading": heading.group(2), "level": 3 if len(heading.group(1)) == 3 else 2, "items": []}
            sections.append(current)
        elif item or quote:
            flush()
            section()["items"].append({"type": "li" if item else "quote", "runs": runs((item or quote).group(1))})
        elif line.startswith("|") and line.endswith("|"):
            flush()
            cells = [cell.strip() for cell in line[1:-1].split("|")]
            if all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells):
                continue
            items = section()["items"]
            if not items or items[-1]["type"] != "table":
                items.append({"type": "table", "rows": []})
            items[-1]["rows"].append(cells)
        else:
            paragraph.append(line)
    flush()
    return {"sections": sections, "references": references}


def _slugify_material(title: str, custom_slug: str = "") -> str:
    source = custom_slug or title
    if custom_slug and (".." in custom_slug or "/" in custom_slug or "\\" in custom_slug):
        raise ValueError("Invalid slug")
    source = unicodedata.normalize("NFKC", source).lower()
    slug = re.sub(r"[^\w?-?]+", "-", source, flags=re.UNICODE).strip("-_")[:80].rstrip("-_")
    return slug or uuid.uuid4().hex[:12]


def _load_db_pre_seminar_materials(get_db, include_drafts=False):
    if get_db is None:
        return []
    try:
        query = get_db().table("pre_seminar_materials").select("*")
        if not include_drafts:
            query = query.eq("is_published", True)
        rows = query.order("seminar_date", desc=True).order("created_at", desc=True).execute().data or []
        books = []
        for row in rows:
            parsed = parse_pre_seminar_markdown(row.get("markdown_body") or "")
            books.append({"id": row["id"], "slug": row["slug"], "title": row["title"],
                "author": row.get("author") or "", "semester": row.get("semester") or "custom",
                "semester_label": row.get("semester_label") or row.get("semester") or "최신 세미나",
                "date": row.get("seminar_date") or "", "edition_note": row.get("edition_note") or "",
                **parsed, "source": "db", "is_published": bool(row.get("is_published", True)),
                "markdown_body": row.get("markdown_body") or ""})
        return books
    except Exception:
        return []


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


def init_public_archive_routes(app, login_required, get_db=None):
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
        db_books = _load_db_pre_seminar_materials(get_db)
        db_slugs = {b["slug"] for b in db_books}
        all_books = db_books + [b for b in payload.get("books", []) if b.get("slug") not in db_slugs]
        semesters_by_id = {sem["id"]: dict(sem) for sem in payload.get("semesters", [])}
        for book in db_books:
            semesters_by_id[book["semester"]] = {"id": book["semester"], "label": book["semester_label"]}
        semesters = sorted(semesters_by_id.values(), key=lambda sem: sem["id"], reverse=True)

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
                has_archive_book=bool(active_book and any(b.get("slug") == active_book.get("slug") for b in _load_json_snapshot(PUBLIC_ARCHIVE_PATH).get("books", []))),
                is_staff=session.get("user_role") in ("admin", "officer"),
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

    def require_db():
        if get_db is None:
            abort(503)
        return get_db()

    @app.get("/admin/pre-seminar")
    @login_required(role="admin")
    def admin_pre_seminar():
        books = _load_db_pre_seminar_materials(get_db, include_drafts=True)
        edit = next((b for b in books if str(b["id"]) == request.args.get("edit")), None)
        if request.args.get("edit") and edit is None:
            abort(404)
        return render_template("admin_pre_seminar.html", books=books, edit=edit)

    @app.post("/admin/pre-seminar/save")
    @login_required(role="admin")
    def admin_pre_seminar_save():
        check_csrf()
        data = request.get_json(silent=True) if request.is_json else request.form
        data = data or {}
        title = str(data.get("title") or "").strip()
        body = str(data.get("markdown_body") or "").strip()
        if not title or not body or len(body) > 300000 or len(title) > 300000:
            return (jsonify(ok=False, error="제목과 본문을 확인해 주세요."), 400)
        db = require_db()
        material_id = str(data.get("material_id") or "").strip()
        table = "pre_seminar_materials"
        row = {key: str(data.get(key) or "").strip() for key in ("author", "semester", "semester_label", "seminar_date", "edition_note")}
        if not row["semester"]:
            row["semester"] = row["seminar_date"][:4] or str(datetime.now().year)
            row["semester"] += "-custom"
        row.update(title=title, markdown_body=body, is_published=data.get("is_published") in (True, "true", "on", "1"), updated_at=datetime.now(timezone.utc).isoformat())
        if material_id:
            found = db.table(table).select("id").eq("id", material_id).limit(1).execute().data or []
            if not found:
                abort(404)
            db.table(table).update(row).eq("id", material_id).execute()
        else:
            base = _slugify_material(title)
            slug = base
            n = 2
            while db.table(table).select("id").eq("slug", slug).limit(1).execute().data:
                suffix = f"-{n}"
                slug = base[:80-len(suffix)].rstrip("-") + suffix
                n += 1
            row.update(id=str(uuid.uuid4()), slug=slug, created_by=session.get("user_id"))
            db.table(table).insert(row).execute()
        return jsonify(ok=True) if request.is_json else redirect(url_for("admin_pre_seminar", saved=1), code=303)

    @app.post("/api/admin/pre-seminar/preview")
    @login_required(role="admin")
    def admin_pre_seminar_preview():
        check_csrf()
        data = request.get_json(silent=True) or request.form
        body = str(data.get("markdown_body") or "")
        if len(body) > 300000:
            abort(400)
        return jsonify(ok=True, **parse_pre_seminar_markdown(body))

    @app.post("/api/admin/pre-seminar/<material_id>/toggle")
    @login_required(role="admin")
    def admin_pre_seminar_toggle(material_id):
        check_csrf()
        db = require_db()
        rows = db.table("pre_seminar_materials").select("*").eq("id", material_id).limit(1).execute().data or []
        if not rows:
            abort(404)
        published = not rows[0].get("is_published", True)
        db.table("pre_seminar_materials").update({"is_published": published, "updated_at": datetime.now(timezone.utc).isoformat()}).eq("id", material_id).execute()
        return jsonify(ok=True, is_published=published)

    @app.post("/api/admin/pre-seminar/<material_id>/delete")
    @login_required(role="admin")
    def admin_pre_seminar_delete(material_id):
        check_csrf()
        db = require_db()
        rows = db.table("pre_seminar_materials").select("id").eq("id", material_id).limit(1).execute().data or []
        if not rows:
            abort(404)
        db.table("pre_seminar_materials").delete().eq("id", material_id).execute()
        return jsonify(ok=True)
