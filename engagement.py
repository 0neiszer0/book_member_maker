import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from io import BytesIO

from flask import (
    abort, flash, jsonify, redirect, render_template, request, session, url_for,
)
from PIL import Image, ImageOps, UnidentifiedImageError
from engagement_utils import clean_text as _clean_text
from engagement_utils import form_is_open as _form_is_open
from engagement_utils import normalize_kyobo_url as _normalize_kyobo_url


FORM_TABLES = {
    "seminar": "seminar_review_forms",
    "brick-recruitment": "brick_recruitments",
    "brick-review": "brick_review_forms",
}


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _kst_datetime_input(value):
    if not value:
        return None
    naive = datetime.fromisoformat(value)
    return naive.replace(tzinfo=timezone(timedelta(hours=9))).astimezone(timezone.utc).isoformat()


def _public_base():
    configured = os.environ.get("PUBLIC_BASE_URL", "").strip().rstrip("/")
    return configured or request.url_root.rstrip("/")


def _social_meta(title, description, canonical=None, image=None, noindex=False):
    return {
        "title": title,
        "description": description,
        "canonical": canonical or request.base_url,
        "image": image or f"{_public_base()}/static/og/club-preview.png",
        "noindex": noindex,
    }


def init_engagement_routes(app, supabase, login_required, voting_window_for=None):
    def current_member(allow_remembered=True):
        member_id = session.get("user_id")
        if not member_id and allow_remembered:
            member_id = session.get("participation_member_id")
        if not member_id:
            return None
        rows = (
            supabase.table("members")
            .select("id,name,student_id,department,is_active,role")
            .eq("id", member_id)
            .limit(1)
            .execute()
            .data
            or []
        )
        member = rows[0] if rows else None
        if not member or member.get("is_active") is False:
            session.pop("participation_member_id", None)
            return None
        return member

    def resolve_member(form):
        logged_in = current_member(allow_remembered=False)
        if logged_in:
            return logged_in
        student_id = re.sub(r"\s+", "", form.get("student_id", ""))
        name = re.sub(r"\s+", "", form.get("member_name", ""))
        if not student_id or not name:
            remembered = current_member()
            if remembered:
                return remembered
            raise ValueError("학번과 이름을 입력해주세요.")
        rows = (
            supabase.table("members")
            .select("id,name,student_id,department,is_active,role")
            .eq("student_id", student_id)
            .eq("name", name)
            .eq("is_active", True)
            .limit(2)
            .execute()
            .data
            or []
        )
        if len(rows) != 1:
            raise ValueError("활성 회원 명단에서 학번과 이름이 일치하는 회원을 찾지 못했습니다.")
        session["participation_member_id"] = rows[0]["id"]
        session.permanent = True
        return rows[0]

    def upload_optional_image(file, folder, bucket="engagement-photos"):
        if not file or not file.filename:
            return None, None
        raw = file.read(5 * 1024 * 1024 + 1)
        if len(raw) > 5 * 1024 * 1024:
            raise ValueError("사진은 5MB 이하만 올릴 수 있습니다.")
        try:
            with Image.open(BytesIO(raw)) as source:
                image = ImageOps.exif_transpose(source).convert("RGB")
                image.thumbnail((1200, 1200), Image.Resampling.LANCZOS)
                output = BytesIO()
                image.save(output, "WEBP", quality=82, method=6)
                payload = output.getvalue()
        except (UnidentifiedImageError, OSError):
            raise ValueError("JPG, PNG, WEBP 형식의 정상적인 사진만 올릴 수 있습니다.")
        if len(payload) > 1024 * 1024:
            raise ValueError("사진을 압축한 뒤에도 1MB를 넘습니다. 더 작은 사진을 골라주세요.")
        path = f"{folder}/{uuid.uuid4()}.webp"
        supabase.storage.from_(bucket).upload(
            path, payload, {"content-type": "image/webp", "upsert": "false"}
        )
        return path, "image/webp"

    def image_url(path):
        if not path:
            return None
        return f"{os.environ.get('SUPABASE_URL', '').rstrip('/')}/storage/v1/object/public/book-covers/{path}"

    def save_revision(kind, row):
        payload = {
            key: value for key, value in row.items()
            if key not in {"id", "created_at", "updated_at", "deleted_at"}
        }
        supabase.table("submission_revisions").insert({
            "submission_type": kind,
            "submission_id": row["id"],
            "member_id": row["member_id"],
            "payload": payload,
            "actor_kind": "staff" if session.get("user_role") in ("admin", "officer") else "member",
        }).execute()

    @app.context_processor
    def engagement_navigation_context():
        return {
            "engagement_image_url": image_url,
            "default_social_image_url": f"{_public_base()}/static/og/club-preview.png",
        }

    @app.post("/participate/forget")
    def forget_participation_identity():
        session.pop("participation_member_id", None)
        flash("이 브라우저에 기억한 회원 정보를 지웠습니다.", "success")
        return redirect(request.referrer or url_for("engagement_now"))

    @app.get("/now")
    def engagement_now():
        cards = []
        if voting_window_for:
            terms = (
                supabase.table("seminar_terms")
                .select("id,name,share_token")
                .eq("is_active", True)
                .execute().data or []
            )
            term_map = {row["id"]: row for row in terms}
            if term_map:
                monday_sessions = (
                    supabase.table("seminar_sessions")
                    .select("id,term_id,meeting_date,book_title,capacity,day_type,participation_mode,vote_open_at,vote_close_at")
                    .in_("term_id", list(term_map))
                    .eq("is_active", True)
                    .eq("day_type", "mon")
                    .eq("participation_mode", "opt_in")
                    .order("meeting_date")
                    .execute().data or []
                )
                now_kst = datetime.now(timezone(timedelta(hours=9)))
                for row in monday_sessions:
                    open_at, close_at = voting_window_for(row)
                    if not (open_at <= now_kst <= close_at):
                        continue
                    term = term_map[row["term_id"]]
                    seats = (
                        supabase.table("seminar_votes").select("id", count="exact")
                        .eq("session_id", row["id"]).eq("attending", True).execute().count or 0
                    )
                    capacity = row.get("capacity") or 10
                    cards.append({
                        "kind": "추가 세미나 신청",
                        "title": f"{row['meeting_date']} 월요일",
                        "description": f"{row.get('book_title') or '도서 미정'} · {seats}/{capacity}명 신청 · 남은 자리 {max(0, capacity-seats)}석",
                        "url": url_for("seminar_vote", token=term["share_token"]),
                        "close_at": close_at.astimezone(timezone.utc).isoformat(),
                    })
        topic_rows = (
            supabase.table("topic_events")
            .select("id,meeting_date,book_title,book_author,share_token,created_at")
            .eq("is_active", True)
            .order("meeting_date")
            .execute()
            .data
            or []
        )
        for row in topic_rows:
            cards.append({
                "kind": "발제문",
                "title": row.get("book_title") or "이번 세미나 발제문",
                "description": f"{row.get('meeting_date')} 세미나 · 먼저 제출된 발제문을 확인하고 중복을 피할 수 있어요.",
                "url": url_for("view_shared_topics", token=row["share_token"]),
                "close_at": None,
            })

        seminar_forms = (
            supabase.table("seminar_review_forms")
            .select("*")
            .eq("status", "open")
            .order("close_at")
            .execute()
            .data
            or []
        )
        for form in seminar_forms:
            if not _form_is_open(form):
                continue
            seminar = (
                supabase.table("seminar_sessions")
                .select("meeting_date,book_title,book_author")
                .eq("id", form["seminar_session_id"])
                .single()
                .execute()
                .data
            )
            cards.append({
                "kind": "세미나 후기",
                "title": (seminar or {}).get("book_title") or "세미나 후기",
                "description": f"{(seminar or {}).get('meeting_date', '')} 세미나에서 기억에 남은 내용을 남겨주세요.",
                "url": url_for("seminar_review_form", token=form["share_token"]),
                "close_at": form.get("close_at"),
            })

        recruitments = (
            supabase.table("brick_recruitments")
            .select("*")
            .eq("status", "open")
            .order("close_at")
            .execute()
            .data
            or []
        )
        for form in recruitments:
            if not _form_is_open(form):
                continue
            project = (
                supabase.table("brick_projects")
                .select("title,description")
                .eq("id", form["project_id"])
                .single()
                .execute()
                .data
            )
            cards.append({
                "kind": "벽돌책 모집",
                "title": (project or {}).get("title") or "벽돌책 모집",
                "description": _clean_text((project or {}).get("description"), 120),
                "url": url_for("brick_application_form", token=form["share_token"]),
                "close_at": form.get("close_at"),
            })

        review_forms = (
            supabase.table("brick_review_forms")
            .select("*")
            .eq("status", "open")
            .order("close_at")
            .execute()
            .data
            or []
        )
        for form in review_forms:
            if not _form_is_open(form):
                continue
            project = (
                supabase.table("brick_projects")
                .select("title")
                .eq("id", form["project_id"])
                .single()
                .execute()
                .data
            )
            cards.append({
                "kind": "벽돌책 후기",
                "title": (project or {}).get("title") or "벽돌책 후기",
                "description": "완독 경험과 기억에 남은 내용을 기록해주세요.",
                "url": url_for("brick_review_form", token=form["share_token"]),
                "close_at": form.get("close_at"),
            })
        cards.sort(key=lambda row: row.get("close_at") or "9999")
        return render_template(
            "engagement_now.html",
            cards=cards,
            remembered_member=current_member(),
            social_meta=_social_meta(
                "지금 참여하기 · 책 먹는 호반우",
                "현재 열려 있는 발제문, 세미나 후기, 벽돌책 모집과 책 추천을 한곳에서 확인하세요.",
                f"{_public_base()}/now",
            ),
        )

    @app.route("/books/suggest", methods=["GET", "POST"])
    def book_suggest():
        member = current_member()
        if request.method == "POST":
            try:
                member = resolve_member(request.form)
                title = _clean_text(request.form.get("title"), 200)
                author = _clean_text(request.form.get("author"), 120)
                note = _clean_text(request.form.get("note"), 3000)
                kyobo_url = _normalize_kyobo_url(request.form.get("kyobo_url"))
                targets = [item for item in request.form.getlist("targets") if item in ("curriculum", "brick_book")]
                if not title or not author or not note or not targets:
                    raise ValueError("도서명, 저자, 추천 이유와 추천 분야를 모두 입력해주세요.")
                existing = (
                    supabase.table("book_catalog")
                    .select("*")
                    .eq("kyobo_url", kyobo_url)
                    .limit(1)
                    .execute()
                    .data
                    or []
                )
                cover_path, cover_type = upload_optional_image(
                    request.files.get("cover"), "covers", bucket="book-covers"
                )
                if existing:
                    book = existing[0]
                    if cover_path and not book.get("cover_path"):
                        supabase.table("book_catalog").update({
                            "cover_path": cover_path,
                            "cover_mime_type": cover_type,
                            "updated_at": _now_iso(),
                        }).eq("id", book["id"]).execute()
                else:
                    book = supabase.table("book_catalog").insert({
                        "title": title,
                        "author": author,
                        "kyobo_url": kyobo_url,
                        "cover_path": cover_path,
                        "cover_mime_type": cover_type,
                        "created_by": member["id"],
                    }).execute().data[0]
                active = (
                    supabase.table("book_suggestions")
                    .select("*")
                    .eq("book_id", book["id"])
                    .neq("status", "archived")
                    .limit(1)
                    .execute()
                    .data
                    or []
                )
                if active:
                    suggestion = active[0]
                    supabase.table("book_suggestion_targets").upsert([
                        {"suggestion_id": suggestion["id"], "target_type": item} for item in targets
                    ], on_conflict="suggestion_id,target_type").execute()
                    supabase.table("book_suggestion_supporters").upsert({
                        "suggestion_id": suggestion["id"],
                        "member_id": member["id"],
                        "reason": note[:500],
                        "withdrawn_at": None,
                        "created_at": _now_iso(),
                    }, on_conflict="suggestion_id,member_id").execute()
                    if suggestion["created_by"] != member["id"]:
                        supabase.table("book_suggestion_comments").insert({
                            "suggestion_id": suggestion["id"],
                            "member_id": member["id"],
                            "content": note[:2000],
                        }).execute()
                    flash("이미 추천된 책이라 기존 추천에 관심과 의견을 합쳤습니다.", "success")
                    return redirect(url_for("book_suggestion_detail", suggestion_id=suggestion["id"]))
                suggestion = supabase.table("book_suggestions").insert({
                    "book_id": book["id"],
                    "created_by": member["id"],
                    "note": note,
                }).execute().data[0]
                supabase.table("book_suggestion_targets").insert([
                    {"suggestion_id": suggestion["id"], "target_type": item} for item in targets
                ]).execute()
                supabase.table("book_suggestion_supporters").insert({
                    "suggestion_id": suggestion["id"],
                    "member_id": member["id"],
                    "reason": note[:500],
                }).execute()
                flash("책 추천을 등록했습니다.", "success")
                return redirect(url_for("book_suggestion_detail", suggestion_id=suggestion["id"]))
            except ValueError as exc:
                flash(str(exc), "danger")
            except Exception as exc:
                app.logger.error("book suggestion failed: %s", exc, exc_info=True)
                flash("추천을 저장하지 못했습니다. 잠시 후 다시 시도해주세요.", "danger")
        return render_template(
            "book_suggest.html",
            member=member,
            social_meta=_social_meta(
                "책 추천하기 · 책 먹는 호반우",
                "커리큘럼이나 벽돌책으로 함께 읽고 싶은 책을 추천해주세요.",
                f"{_public_base()}/books/suggest",
                noindex=True,
            ),
        )

    @app.get("/books/suggestions")
    def book_suggestions():
        rows = (
            supabase.table("book_suggestions")
            .select("*")
            .neq("status", "archived")
            .order("created_at", desc=True)
            .execute()
            .data
            or []
        )
        books = {}
        if rows:
            ids = list({row["book_id"] for row in rows})
            books = {row["id"]: row for row in supabase.table("book_catalog").select("*").in_("id", ids).execute().data or []}
        suggestions = []
        for row in rows:
            supporters = (
                supabase.table("book_suggestion_supporters")
                .select("member_id", count="exact")
                .eq("suggestion_id", row["id"])
                .is_("withdrawn_at", "null")
                .execute()
            )
            targets = (
                supabase.table("book_suggestion_targets")
                .select("target_type")
                .eq("suggestion_id", row["id"])
                .execute()
                .data
                or []
            )
            suggestions.append({
                **row,
                "book": books.get(row["book_id"], {}),
                "support_count": supporters.count or 0,
                "targets": [item["target_type"] for item in targets],
            })
        return render_template(
            "book_suggestions.html",
            suggestions=suggestions,
            social_meta=_social_meta(
                "함께 읽을 책 · 책 먹는 호반우",
                "회원들이 추천한 커리큘럼·벽돌책을 보고 관심을 표시해보세요.",
                f"{_public_base()}/books/suggestions",
            ),
        )

    @app.get("/books/suggestions/<uuid:suggestion_id>")
    def book_suggestion_detail(suggestion_id):
        suggestion = (
            supabase.table("book_suggestions").select("*")
            .eq("id", str(suggestion_id)).single().execute().data
        )
        if not suggestion or suggestion.get("status") == "archived":
            abort(404)
        book = supabase.table("book_catalog").select("*").eq("id", suggestion["book_id"]).single().execute().data
        supporter_rows = (
            supabase.table("book_suggestion_supporters")
            .select("member_id,reason,created_at")
            .eq("suggestion_id", str(suggestion_id))
            .is_("withdrawn_at", "null")
            .execute().data or []
        )
        comments = (
            supabase.table("book_suggestion_comments")
            .select("*")
            .eq("suggestion_id", str(suggestion_id))
            .is_("deleted_at", "null")
            .order("created_at")
            .execute().data or []
        )
        for row in comments:
            row["member"] = {"name": "회원"}
        member = current_member()
        supported = bool(member and any(row["member_id"] == member["id"] for row in supporter_rows))
        return render_template(
            "book_suggestion_detail.html",
            suggestion=suggestion,
            book=book,
            comments=comments,
            supporter_rows=supporter_rows,
            member=member,
            supported=supported,
            social_meta=_social_meta(
                f"{book['title']} · 함께 읽을 책",
                _clean_text(suggestion.get("note"), 140),
                f"{_public_base()}/books/suggestions/{suggestion_id}",
            ),
        )

    @app.post("/books/suggestions/<uuid:suggestion_id>/support")
    def support_book_suggestion(suggestion_id):
        try:
            member = resolve_member(request.form)
            existing = (
                supabase.table("book_suggestion_supporters")
                .select("member_id,withdrawn_at")
                .eq("suggestion_id", str(suggestion_id))
                .eq("member_id", member["id"])
                .limit(1).execute().data or []
            )
            if existing and not existing[0].get("withdrawn_at"):
                supabase.table("book_suggestion_supporters").update({
                    "withdrawn_at": _now_iso(),
                }).eq("suggestion_id", str(suggestion_id)).eq("member_id", member["id"]).execute()
                flash("관심 표시를 취소했습니다.", "success")
            elif existing:
                supabase.table("book_suggestion_supporters").update({
                    "withdrawn_at": None,
                    "reason": _clean_text(request.form.get("reason"), 500) or None,
                    "created_at": _now_iso(),
                }).eq("suggestion_id", str(suggestion_id)).eq("member_id", member["id"]).execute()
                flash("같이 읽고 싶다고 표시했습니다.", "success")
            else:
                supabase.table("book_suggestion_supporters").insert({
                    "suggestion_id": str(suggestion_id),
                    "member_id": member["id"],
                    "reason": _clean_text(request.form.get("reason"), 500) or None,
                }).execute()
                flash("같이 읽고 싶다고 표시했습니다.", "success")
        except ValueError as exc:
            flash(str(exc), "danger")
        return redirect(url_for("book_suggestion_detail", suggestion_id=suggestion_id))

    @app.post("/books/suggestions/<uuid:suggestion_id>/comments")
    def comment_book_suggestion(suggestion_id):
        try:
            member = resolve_member(request.form)
            content = _clean_text(request.form.get("content"), 2000)
            if not content:
                raise ValueError("댓글 내용을 입력해주세요.")
            supabase.table("book_suggestion_comments").insert({
                "suggestion_id": str(suggestion_id),
                "member_id": member["id"],
                "content": content,
            }).execute()
            flash("댓글을 남겼습니다.", "success")
        except ValueError as exc:
            flash(str(exc), "danger")
        return redirect(url_for("book_suggestion_detail", suggestion_id=suggestion_id))

    @app.route("/review/seminar/<uuid:token>", methods=["GET", "POST"])
    def seminar_review_form(token):
        forms = supabase.table("seminar_review_forms").select("*").eq("share_token", str(token)).limit(1).execute().data or []
        if not forms:
            abort(404)
        form = forms[0]
        seminar = supabase.table("seminar_sessions").select("*").eq("id", form["seminar_session_id"]).single().execute().data
        member = current_member()
        existing = None
        if member:
            rows = supabase.table("seminar_reviews").select("*").eq("form_id", form["id"]).eq("member_id", member["id"]).limit(1).execute().data or []
            existing = rows[0] if rows else None
            if existing:
                existing["review_content"] = "\n\n".join(filter(None, [
                    existing.get("memorable_point"),
                    existing.get("discussion_point"),
                    existing.get("free_text"),
                ]))
        if request.method == "POST":
            try:
                if not _form_is_open(form):
                    raise ValueError("후기 입력이 마감되었습니다.")
                member = resolve_member(request.form)
                rows = supabase.table("seminar_reviews").select("*").eq("form_id", form["id"]).eq("member_id", member["id"]).limit(1).execute().data or []
                existing = rows[0] if rows else None
                review_content = _clean_text(request.form.get("review_content"), 5000)
                if not review_content:
                    raise ValueError("세미나 후기를 입력해주세요.")
                payload = {
                    "form_id": form["id"],
                    "seminar_session_id": form["seminar_session_id"],
                    "member_id": member["id"],
                    "memorable_point": review_content,
                    "discussion_point": None,
                    "free_text": None,
                    "updated_at": _now_iso(),
                    "deleted_at": None,
                }
                if existing:
                    save_revision("seminar_review", existing)
                    supabase.table("seminar_reviews").update(payload).eq("id", existing["id"]).execute()
                else:
                    supabase.table("seminar_reviews").insert(payload).execute()
                flash("세미나 후기를 저장했습니다.", "success")
                return redirect(url_for("seminar_review_form", token=token))
            except ValueError as exc:
                flash(str(exc), "danger")
        return render_template(
            "engagement_form.html",
            form_kind="seminar_review",
            form_row=form,
            context_row=seminar,
            member=member,
            existing=existing,
            is_open=_form_is_open(form),
            social_meta=_social_meta(
                f"{seminar.get('book_title') or '세미나'} 후기",
                f"{seminar.get('meeting_date')} 세미나 후기를 남겨주세요.",
                request.base_url,
                noindex=True,
            ),
        )

    @app.route("/brick/apply/<uuid:token>", methods=["GET", "POST"])
    def brick_application_form(token):
        forms = supabase.table("brick_recruitments").select("*").eq("share_token", str(token)).limit(1).execute().data or []
        if not forms:
            abort(404)
        form = forms[0]
        project = supabase.table("brick_projects").select("*").eq("id", form["project_id"]).single().execute().data
        book = supabase.table("book_catalog").select("*").eq("id", project["book_id"]).single().execute().data
        member = current_member()
        existing = None
        if member:
            rows = supabase.table("brick_applications").select("*").eq("recruitment_id", form["id"]).eq("member_id", member["id"]).limit(1).execute().data or []
            existing = rows[0] if rows else None
        if request.method == "POST":
            try:
                if not _form_is_open(form):
                    raise ValueError("벽돌책 모집이 마감되었습니다.")
                member = resolve_member(request.form)
                rows = supabase.table("brick_applications").select("*").eq("recruitment_id", form["id"]).eq("member_id", member["id"]).limit(1).execute().data or []
                existing = rows[0] if rows else None
                motivation = _clean_text(request.form.get("motivation"), 5000)
                if not motivation:
                    raise ValueError("지원 동기를 입력해주세요.")
                payload = {
                    "recruitment_id": form["id"],
                    "project_id": form["project_id"],
                    "member_id": member["id"],
                    "motivation": motivation,
                    "availability": _clean_text(request.form.get("availability"), 2000) or None,
                    "note": _clean_text(request.form.get("note"), 2000) or None,
                    "status": "pending",
                    "updated_at": _now_iso(),
                }
                if existing:
                    save_revision("brick_application", existing)
                    supabase.table("brick_applications").update(payload).eq("id", existing["id"]).execute()
                else:
                    supabase.table("brick_applications").insert(payload).execute()
                flash("벽돌책 지원을 저장했습니다.", "success")
                return redirect(url_for("brick_application_form", token=token))
            except ValueError as exc:
                flash(str(exc), "danger")
        return render_template(
            "engagement_form.html",
            form_kind="brick_application",
            form_row=form,
            context_row=project,
            book=book,
            member=member,
            existing=existing,
            is_open=_form_is_open(form),
            social_meta=_social_meta(
                f"{project['title']} · 벽돌책 모집",
                _clean_text(project.get("description"), 140),
                request.base_url,
                noindex=True,
            ),
        )

    @app.route("/brick/review/<uuid:token>", methods=["GET", "POST"])
    def brick_review_form(token):
        forms = supabase.table("brick_review_forms").select("*").eq("share_token", str(token)).limit(1).execute().data or []
        if not forms:
            abort(404)
        form = forms[0]
        project = supabase.table("brick_projects").select("*").eq("id", form["project_id"]).single().execute().data
        book = supabase.table("book_catalog").select("*").eq("id", project["book_id"]).single().execute().data
        member = current_member()
        existing = None
        if member:
            rows = supabase.table("brick_reviews").select("*").eq("form_id", form["id"]).eq("member_id", member["id"]).limit(1).execute().data or []
            existing = rows[0] if rows else None
        if request.method == "POST":
            try:
                if not _form_is_open(form):
                    raise ValueError("벽돌책 후기 입력이 마감되었습니다.")
                member = resolve_member(request.form)
                rows = supabase.table("brick_reviews").select("*").eq("form_id", form["id"]).eq("member_id", member["id"]).limit(1).execute().data or []
                existing = rows[0] if rows else None
                memorable = _clean_text(request.form.get("memorable_point"), 5000)
                if not memorable:
                    raise ValueError("기억에 남은 내용을 입력해주세요.")
                image_path, image_type = upload_optional_image(request.files.get("photo"), "brick-reviews")
                payload = {
                    "form_id": form["id"],
                    "project_id": form["project_id"],
                    "member_id": member["id"],
                    "memorable_point": memorable,
                    "free_text": _clean_text(request.form.get("free_text"), 10000) or None,
                    "updated_at": _now_iso(),
                    "deleted_at": None,
                }
                if image_path:
                    payload.update(image_path=image_path, image_mime_type=image_type)
                if existing:
                    save_revision("brick_review", existing)
                    supabase.table("brick_reviews").update(payload).eq("id", existing["id"]).execute()
                else:
                    supabase.table("brick_reviews").insert(payload).execute()
                flash("벽돌책 후기를 저장했습니다.", "success")
                return redirect(url_for("brick_review_form", token=token))
            except ValueError as exc:
                flash(str(exc), "danger")
        return render_template(
            "engagement_form.html",
            form_kind="brick_review",
            form_row=form,
            context_row=project,
            book=book,
            member=member,
            existing=existing,
            is_open=_form_is_open(form),
            social_meta=_social_meta(
                f"{project['title']} · 벽돌책 후기",
                "완독 경험과 기억에 남은 내용을 기록해주세요.",
                request.base_url,
                noindex=True,
            ),
        )

    @app.get("/admin/engagement")
    @login_required(role="admin")
    def admin_engagement():
        seminar_forms = supabase.table("seminar_review_forms").select("*").order("created_at", desc=True).execute().data or []
        sessions = supabase.table("seminar_sessions").select("id,meeting_date,book_title,day_type").order("meeting_date", desc=True).limit(30).execute().data or []
        session_map = {row["id"]: row for row in sessions}
        for row in seminar_forms:
            row["seminar"] = session_map.get(row["seminar_session_id"], {})
            row["share_url"] = f"{_public_base()}/review/seminar/{row['share_token']}"
            row["submission_count"] = supabase.table("seminar_reviews").select("id", count="exact").eq("form_id", row["id"]).is_("deleted_at", "null").execute().count or 0
        suggestions = supabase.table("book_suggestions").select("*").in_(
            "status", ["suggested", "considering"]
        ).order("created_at", desc=True).execute().data or []
        books = {row["id"]: row for row in supabase.table("book_catalog").select("*").execute().data or []}
        for row in suggestions:
            row["book"] = books.get(row["book_id"], {})
        projects = supabase.table("brick_projects").select("*").order("created_at", desc=True).execute().data or []
        recruitments = {row["project_id"]: row for row in supabase.table("brick_recruitments").select("*").execute().data or []}
        reviews = {row["project_id"]: row for row in supabase.table("brick_review_forms").select("*").execute().data or []}
        project_ids = [row["id"] for row in projects]
        applications = []
        if project_ids:
            applications = supabase.table("brick_applications").select("*").in_("project_id", project_ids).order("created_at").execute().data or []
        applicant_ids = list({row["member_id"] for row in applications})
        applicant_map = {}
        if applicant_ids:
            applicant_map = {
                row["id"]: row for row in
                supabase.table("members").select("id,name,student_id,department").in_("id", applicant_ids).execute().data or []
            }
        applications_by_project = {}
        for application in applications:
            application["member"] = applicant_map.get(application["member_id"], {"name": "회원"})
            applications_by_project.setdefault(application["project_id"], []).append(application)
        for row in projects:
            row["book"] = books.get(row["book_id"], {})
            row["recruitment"] = recruitments.get(row["id"])
            row["review_form"] = reviews.get(row["id"])
            row["applications"] = applications_by_project.get(row["id"], [])
            if row["recruitment"]:
                row["recruitment"]["share_url"] = f"{_public_base()}/brick/apply/{row['recruitment']['share_token']}"
                row["application_count"] = supabase.table("brick_applications").select("id", count="exact").eq("project_id", row["id"]).execute().count or 0
            if row["review_form"]:
                row["review_form"]["share_url"] = f"{_public_base()}/brick/review/{row['review_form']['share_token']}"
        return render_template(
            "admin_engagement.html",
            sessions=sessions,
            seminar_forms=seminar_forms,
            suggestions=suggestions,
            projects=projects,
        )

    @app.post("/api/admin/seminar_sessions/<uuid:session_id>/review-form")
    @login_required(role="admin")
    def create_seminar_review_form(session_id):
        existing = supabase.table("seminar_review_forms").select("*").eq("seminar_session_id", str(session_id)).limit(1).execute().data or []
        if existing:
            form = existing[0]
            supabase.table("seminar_review_forms").update({
                "status": "open",
                "updated_at": _now_iso(),
            }).eq("id", form["id"]).execute()
        else:
            form = supabase.table("seminar_review_forms").insert({
                "seminar_session_id": str(session_id),
                "instructions": _clean_text(request.form.get("instructions"), 2000) or None,
                "status": "open",
                "close_at": _kst_datetime_input(request.form.get("close_at")),
                "created_by": session.get("user_id"),
            }).execute().data[0]
        return jsonify(ok=True, url=f"{_public_base()}/review/seminar/{form['share_token']}")

    @app.post("/api/admin/brick-projects")
    @login_required(role="admin")
    def create_brick_project():
        suggestion_id = request.form.get("suggestion_id")
        suggestion = supabase.table("book_suggestions").select("*").eq("id", suggestion_id).single().execute().data
        if not suggestion:
            return jsonify(ok=False, error="추천을 찾을 수 없습니다."), 404
        title = _clean_text(request.form.get("title"), 200)
        description = _clean_text(request.form.get("description"), 5000)
        if not title or not description:
            return jsonify(ok=False, error="모집 제목과 설명을 입력해주세요."), 400
        try:
            capacity = int(request.form.get("capacity") or 10)
        except (TypeError, ValueError):
            return jsonify(ok=False, error="정원은 숫자로 입력해주세요."), 400
        if capacity < 1 or capacity > 100:
            return jsonify(ok=False, error="정원은 1명부터 100명 사이여야 합니다."), 400
        project = supabase.table("brick_projects").insert({
            "book_id": suggestion["book_id"],
            "source_suggestion_id": suggestion_id,
            "title": title,
            "description": description,
            "coordinator_id": session.get("user_id"),
            "capacity": capacity,
            "planned_start_date": request.form.get("planned_start_date") or None,
            "planned_end_date": request.form.get("planned_end_date") or None,
            "status": "recruiting",
        }).execute().data[0]
        recruitment = supabase.table("brick_recruitments").insert({
            "project_id": project["id"],
            "instructions": _clean_text(request.form.get("instructions"), 3000) or None,
            "status": "open",
            "close_at": _kst_datetime_input(request.form.get("close_at")),
            "created_by": session.get("user_id"),
        }).execute().data[0]
        supabase.table("book_suggestions").update({"status": "selected", "updated_at": _now_iso()}).eq("id", suggestion_id).execute()
        return jsonify(ok=True, url=f"{_public_base()}/brick/apply/{recruitment['share_token']}")

    @app.post("/api/admin/engagement/forms/<kind>/<uuid:form_id>/status")
    @login_required(role="admin")
    def update_engagement_form_status(kind, form_id):
        table = FORM_TABLES.get(kind)
        status = request.form.get("status")
        allowed = {"seminar": {"draft", "open", "closed"}, "brick-recruitment": {"draft", "open", "closed", "finalized"}, "brick-review": {"draft", "open", "closed"}}
        if not table or status not in allowed[kind]:
            return jsonify(ok=False, error="올바르지 않은 상태입니다."), 400
        supabase.table(table).update({"status": status, "updated_at": _now_iso()}).eq("id", str(form_id)).execute()
        return jsonify(ok=True)

    @app.post("/api/admin/brick-projects/<uuid:project_id>/status")
    @login_required(role="admin")
    def update_brick_project_status(project_id):
        status = request.form.get("status")
        if status not in {"draft", "recruiting", "active", "completed", "archived"}:
            return jsonify(ok=False, error="올바르지 않은 상태입니다."), 400
        current = supabase.table("brick_projects").select("status").eq("id", str(project_id)).single().execute().data
        update = {"status": status, "updated_at": _now_iso()}
        if status == "active":
            update["actual_start_date"] = datetime.now().date().isoformat()
        if status == "completed":
            update["actual_end_date"] = datetime.now().date().isoformat()
        supabase.table("brick_projects").update(update).eq("id", str(project_id)).execute()
        if status == "active":
            supabase.table("brick_recruitments").update({
                "status": "finalized", "updated_at": _now_iso()
            }).eq("project_id", str(project_id)).execute()
        if status == "completed":
            supabase.table("brick_project_members").update({
                "status": "completed"
            }).eq("project_id", str(project_id)).eq("status", "active").execute()
            project = supabase.table("brick_projects").select("source_suggestion_id").eq("id", str(project_id)).single().execute().data
            if project and project.get("source_suggestion_id"):
                supabase.table("book_suggestions").update({
                    "status": "completed", "updated_at": _now_iso()
                }).eq("id", project["source_suggestion_id"]).execute()
        supabase.table("brick_project_status_history").insert({
            "project_id": str(project_id),
            "from_status": current.get("status") if current else None,
            "to_status": status,
            "changed_by": session.get("user_id"),
        }).execute()
        if status == "completed":
            existing = supabase.table("brick_review_forms").select("*").eq("project_id", str(project_id)).limit(1).execute().data or []
            if existing:
                supabase.table("brick_review_forms").update({"status": "open", "updated_at": _now_iso()}).eq("id", existing[0]["id"]).execute()
            else:
                supabase.table("brick_review_forms").insert({
                    "project_id": str(project_id),
                    "status": "open",
                    "created_by": session.get("user_id"),
                }).execute()
        return jsonify(ok=True)

    @app.post("/api/admin/brick-applications/<uuid:application_id>/status")
    @login_required(role="admin")
    def update_brick_application_status(application_id):
        status = request.form.get("status")
        if status == "accepted":
            try:
                supabase.rpc("accept_brick_application", {"p_application_id": str(application_id)}).execute()
            except Exception as exc:
                app.logger.error("accept application failed: %s", exc, exc_info=True)
                return jsonify(ok=False, error="정원이 찼거나 지원서를 처리할 수 없습니다."), 409
        elif status in {"pending", "rejected", "withdrawn"}:
            application = supabase.table("brick_applications").select("project_id,member_id").eq("id", str(application_id)).single().execute().data
            supabase.table("brick_applications").update({
                "status": status, "updated_at": _now_iso()
            }).eq("id", str(application_id)).execute()
            if application:
                supabase.table("brick_project_members").update({
                    "status": "withdrawn", "left_at": _now_iso()
                }).eq("project_id", application["project_id"]).eq("member_id", application["member_id"]).execute()
        else:
            return jsonify(ok=False, error="올바르지 않은 상태입니다."), 400
        return jsonify(ok=True)
