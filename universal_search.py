"""Role-scoped search over published snapshots and the club's activity records."""
import logging
import sqlite3
from collections import Counter
from contextlib import closing
from pathlib import Path
from time import monotonic

from flask import current_app, jsonify, request, session, url_for

from boards import ROLE_LEVEL
from db_read import all_rows
from minipc_security import session_login_current
from public_archive_routes import PUBLIC_ARCHIVE_PATH, PRE_SEMINAR_PATH, _book_matches_query, _load_json_snapshot
from wiki_access import can_read_title, is_officer_title, wiki_access

log = logging.getLogger(__name__)


def _text_values(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from _text_values(item)
    elif isinstance(value, dict):
        for key, item in value.items():
            if key != "url":
                yield from _text_values(item)


def _books(q, member):
    for path, group, endpoint in [
        (PUBLIC_ARCHIVE_PATH, "아카이브", "public_archive_book"),
        (PRE_SEMINAR_PATH, "세미나 전 자료", "member_pre_seminar_book"),
    ]:
        if path == PRE_SEMINAR_PATH and not member:
            continue
        for book in _load_json_snapshot(path).get("books", []):
            match = _book_matches_query(book, q) if path == PUBLIC_ARCHIVE_PATH else any(
                q in value.lower() for value in _text_values(book)
            )
            if match:
                yield book["title"], url_for(endpoint, slug=book["slug"]), group, " · ".join(
                    filter(None, [book.get("author"), book.get("semester_label")])
                )


def _rows(query):
    try:
        return all_rows(query.order("id"))
    except Exception:
        log.warning("Search table unavailable", exc_info=True)
        return []


def _boards(db, q, role):
    # All post detail routes currently require login. Unknown read roles fail closed.
    boards = {row["id"]: row for row in _rows(db.table("boards").select(
        "id,name,slug,read_role").eq("is_active", True))
        if ROLE_LEVEL.get(role, -1) >= ROLE_LEVEL.get(row.get("read_role"), 99)}
    if boards:
        posts = db.table("posts").select("id,board_id,title").in_("board_id", list(boards)).is_("deleted_at", "null")
        for post in _rows(posts):
            title = post.get("title") or ""
            if q in title.lower():
                board = boards[post["board_id"]]
                yield title, url_for("board_post_link", slug=board["slug"], post_id=post["id"]), "게시판", board["name"]


def _seminars(db, q, staff):
    weeks = _rows(db.table("seminar_weeks").select("id,term_id,book_title,week_start"))
    week_titles = {row["id"]: row.get("book_title") for row in weeks}
    sessions = _rows(db.table("seminar_sessions").select("id,term_id,seminar_week_id,book_title,meeting_date"))
    terms = {row["id"]: row.get("term_id") for row in sessions}
    history = _rows(db.table("history").select("id,seminar_session_id,book_title,date"))
    for rows, date_field in [(history, "date"), (sessions, "meeting_date"), (weeks, "week_start")]:
        for row in rows:
            date = row.get(date_field) or ""
            title = row.get("book_title") or week_titles.get(row.get("seminar_week_id")) or ""
            if q not in (title + " " + date).lower():
                continue
            term = row.get("term_id") or terms.get(row.get("seminar_session_id"))
            url = (url_for("records_seminar_detail", history_id=row["id"]) if staff and rows is history
                   else url_for("seminars", term_id=term))
            yield title or "세미나", url, "세미나", date


def _wiki(db, q, staff):
    if not current_app.config["WIKI_ENABLED"]:
        return
    access = wiki_access(db, session)
    if not access or not current_app.config["WIKI_DATABASE"]:
        return
    # Read only document names. Bound both the lock wait and the query runtime.
    uri = Path(current_app.config["WIKI_DATABASE"]).resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True, timeout=0.2)) as conn:
        deadline = monotonic() + 0.3
        conn.set_progress_handler(lambda: monotonic() > deadline, 1000)
        for (title,) in conn.execute("select title from data where instr(lower(title), ?) > 0", (q,)):
            if can_read_title(access, title) and (staff or not is_officer_title(title)):
                yield title, url_for("wiki.document", title=title), "위키", "위키 문서"


def _members(db, q):
    rows = _rows(db.table("members").select("id,name,department,student_id,member_status"))
    for row in rows:
        if any(q in str(row.get(key) or "").lower() for key in ("name", "department", "student_id")):
            yield row["name"], url_for("records_member_profile", member_id=row["id"]), "회원", " · ".join(
                filter(None, [row.get("department"), row.get("member_status")])
            )


def _role(db):
    role = session.get("user_role")
    if not session.get("user_id") or not role:
        return None
    try:
        rows = db.table("members").select(
            "role,is_active,member_status,account_status,auth_provider,auth_session_version"
        ).eq("id", session["user_id"]).limit(1).execute().data or []
        if rows:
            member = rows[0]
            if (member.get("account_status") == "active" and member.get("member_status") not in
                    ("inactive", "blocked", "pending") and session_login_current(member, session)):
                if session.get("member_preview") or member.get("is_active") is False:
                    return "member"
                return min((role, member.get("role") or "member"), key=lambda r: ROLE_LEVEL.get(r, -1))
    except Exception:
        log.warning("Search role lookup failed", exc_info=True)
    return None


def init_universal_search(app, get_db):
    @app.get("/api/search")
    def universal_search():
        query = request.args.get("q", "").strip()[:100]
        limit = max(1, min(50, request.args.get("limit", 20, type=int)))
        authenticated = bool(session.get("user_id") and session.get("user_role"))
        results = []
        if query:
            db = get_db()
            role = _role(db) if authenticated and request.args.get("scope") != "public" else None
            staff = role in ("officer", "admin")
            q = query.lower()
            sources = [_books(q, role)]
            if role in ROLE_LEVEL:
                sources.extend([_boards(db, q, role), _seminars(db, q, staff), _wiki(db, q, staff)])
            if staff:
                sources.append(_members(db, q))
            hits = []
            for source in sources:
                try:
                    hits.extend(source)
                except Exception:
                    log.warning("Search source unavailable", exc_info=True)
            hits.sort(key=lambda hit: (hit[0].lower() != q, not hit[0].lower().startswith(q),
                                       q not in hit[0].lower(), q not in hit[3].lower()))
            counts = Counter()
            for title, url, group, description in dict.fromkeys(hits):
                if counts[group] < 6:
                    results.append(dict(title=title, url=url, group=group, description=description))
                    counts[group] += 1
                if len(results) == limit:
                    break
        response = jsonify(query=query, results=results)
        response.headers["Cache-Control"] = "private, no-store, max-age=0" if authenticated else "public, max-age=30"
        response.vary.add("Cookie")
        return response
