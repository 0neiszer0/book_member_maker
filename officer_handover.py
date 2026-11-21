"""No-login officer handover wiki survey and staff management routes."""
from collections import defaultdict
from datetime import datetime, timezone
from hashlib import sha256
import hmac
import os
import threading
import time
import uuid

from flask import abort, g, jsonify, make_response, render_template, request, session
from db_read import all_rows
from engagement_utils import clean_text
from local_auth import KNU_EMAIL_RE
from member_notifications import check_csrf
from security_utils import trusted_client_address

OFFICER_HANDOVER_ROLES = (
    "회장",
    "부회장",
    "총무",
    "기획부장",
    "홍보부장",
    "학술지원부장",
    "기획부원",
    "홍보부원",
    "학술지원부원",
)

SIGNED_CSRF_MAX_AGE = 12 * 3600
RATE_WINDOW_SECONDS = 600
RATE_MAX_SUBMISSIONS = 20
_RATE_LOCK = threading.Lock()
_RATE_BUCKETS = defaultdict(list)


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _public_base():
    configured = os.environ.get("PUBLIC_BASE_URL", "").strip().rstrip("/")
    return configured or request.url_root.rstrip("/")


def _handover_csrf_mac(secret_key, share_token, issued):
    key = str(secret_key or "").encode("utf-8")
    msg = f"csrf|handover|{share_token}|{issued}".encode("utf-8")
    return hmac.new(key, msg, sha256).hexdigest()


def _issue_handover_csrf(secret_key, share_token):
    issued = str(int(time.time()))
    return f"h1.{issued}.{_handover_csrf_mac(secret_key, share_token, issued)}"


def _verify_handover_csrf(secret_key, share_token, supplied):
    if not secret_key or not isinstance(supplied, str):
        return False
    try:
        version, issued, mac = supplied.split(".")
        age = time.time() - int(issued)
    except ValueError:
        return False
    if version != "h1" or not (0 <= age <= SIGNED_CSRF_MAX_AGE):
        return False
    expected = _handover_csrf_mac(secret_key, share_token, issued)
    return hmac.compare_digest(mac, expected)


def _rate_limited(client_ip, share_token):
    now = time.monotonic()
    cutoff = now - RATE_WINDOW_SECONDS
    key = (client_ip or "unknown", str(share_token))
    with _RATE_LOCK:
        if len(_RATE_BUCKETS) > 1024:
            stale_keys = [
                k for k, stamps in _RATE_BUCKETS.items()
                if not stamps or stamps[-1] < cutoff
            ]
            for k in stale_keys:
                del _RATE_BUCKETS[k]
        recent = [ts for ts in _RATE_BUCKETS[key] if ts >= cutoff]
        if len(recent) >= RATE_MAX_SUBMISSIONS:
            _RATE_BUCKETS[key] = recent
            return True
        recent.append(now)
        _RATE_BUCKETS[key] = recent
    return False


def _group_responses_by_role(responses):
    buckets = {role: [] for role in OFFICER_HANDOVER_ROLES}
    extras = {}
    for row in responses:
        role = row.get("role_name") or ""
        if role in buckets:
            buckets[role].append(row)
        else:
            extras.setdefault(role, []).append(row)
    grouped = [(role, buckets[role]) for role in OFFICER_HANDOVER_ROLES if buckets[role]]
    for role, rows in extras.items():
        grouped.append((role or "기타", rows))
    return grouped


def build_handover_wiki_draft(form, responses):
    """Build an openNamu/Markdown-friendly wiki draft grouped by officer role."""
    title = form.get("title") or "임원진 인수인계"
    term_label = (form.get("term_label") or "").strip()
    heading = f"{title} ({term_label})" if term_label else title
    lines = [
        f"= {heading} =",
        f"총 {len(responses)}건의 인수인계 응답이 정리되어 있습니다.",
        "",
    ]
    grouped = _group_responses_by_role(responses)
    if not grouped:
        lines.append("아직 접수된 인수인계 응답이 없습니다.")
        return "\n".join(lines)

    field_labels = (
        ("core_tasks", "핵심 업무 3가지 (시기 포함)"),
        ("hardships_and_tips", "처음 맡았을 때 헤맸던 점 · 미리 알았으면 좋았을 점"),
        ("assets_and_links", "차기 임원에게 넘길 파일·링크·디자인 원본·양식 위치"),
        ("common_issues", "자주 생기는 트러블과 해결 요령"),
        ("next_officer_note", "다음 기수 임원에게 남기는 한 줄 팁"),
    )
    for role, rows in grouped:
        lines.append(f"== {role} ==")
        for idx, row in enumerate(rows, start=1):
            author = (row.get("author_name") or "").strip() or f"익명 {idx}"
            cohort = (row.get("term_cohort") or "").strip()
            subhead = f"{author} ({cohort})" if cohort else author
            lines.append(f"=== {subhead} ===")
            for key, label in field_labels:
                value = (row.get(key) or "").strip()
                if not value:
                    continue
                lines.append(f" * '''{label}'''")
                for line in value.splitlines():
                    lines.append(f"   {line}" if line.strip() else "")
            lines.append("")
    return "\n".join(lines).rstrip()


def _match_handover_emails(db, responses):
    with_email = [response for response in responses if response.get("knu_email")]
    if not with_email:
        return []

    members = all_rows(
        db.table("members").select("id,name,role,knu_email,social_id,member_status")
        .eq("is_active", True).eq("account_status", "active").order("name").order("id")
    )
    active_members = [
        member for member in members
        if member.get("member_status") not in ("inactive", "blocked")
        and not str(member.get("social_id") or "").startswith("system:")
    ]
    linked_emails = {member["knu_email"] for member in active_members if member.get("knu_email")}
    names = defaultdict(list)
    for member in active_members:
        names[member.get("name")].append(member)

    actor_id = session.get("user_id")
    is_admin = session.get("user_role") == "admin"

    def can_link(member):
        return member.get("knu_email") is None and (
            is_admin or member["id"] == actor_id or member.get("role") == "member"
        )

    for response in with_email:
        response["email_linked"] = response["knu_email"] in linked_emails
        author_name = response.get("author_name")
        matches = names.get(author_name, []) if author_name else []
        response["email_matches"] = [member for member in matches if can_link(member)]
        response["email_preselect"] = matches[0]["id"] if len(matches) == 1 and can_link(matches[0]) else None

    return [member for member in active_members if member.get("role") in ("admin", "officer")
            and can_link(member)]


def init_officer_handover_routes(app, get_db, login_required):
    def _render_public(form, token, status_code=200, **extra):
        secret = app.secret_key or os.environ.get("FLASK_SECRET_KEY", "")
        ctx = {
            "form": form,
            "share_token": str(token),
            "roles": OFFICER_HANDOVER_ROLES,
            "is_open": form.get("status") == "open",
            "csrf_token": _issue_handover_csrf(secret, str(token)),
            "submitted": False,
            "error_message": None,
            "form_values": {},
        }
        ctx.update(extra)
        resp = make_response(render_template("officer_handover_form.html", **ctx), status_code)
        resp.headers["Cache-Control"] = "no-store"
        return resp

    @app.route("/handover/<uuid:token>", methods=["GET", "POST"])
    def handover_public_form(token):
        db = get_db()
        token_str = str(token)
        forms = (
            db.table("officer_handover_forms")
            .select("*")
            .eq("share_token", token_str)
            .limit(1)
            .execute()
            .data
            or []
        )
        if not forms:
            abort(404)
        form = forms[0]

        if request.method == "GET":
            return _render_public(form, token_str, status_code=200)

        secret = app.secret_key or os.environ.get("FLASK_SECRET_KEY", "")
        if not _verify_handover_csrf(secret, token_str, request.form.get("csrf_token", "")):
            abort(403)

        if (request.form.get("website") or "").strip():
            return _render_public(
                form,
                token_str,
                status_code=400,
                error_message="요청을 처리할 수 없습니다.",
            )

        if form.get("status") != "open":
            return _render_public(
                form,
                token_str,
                status_code=400,
                is_open=False,
                error_message="이 설문은 현재 마감되어 응답을 제출할 수 없습니다.",
            )

        client_ip = trusted_client_address(
            request.headers,
            request.remote_addr,
            bool(getattr(g, "trusted_app_proxy", False)),
        )
        if _rate_limited(client_ip, token_str):
            return _render_public(
                form,
                token_str,
                status_code=429,
                error_message="잠시 후 다시 시도해주세요. 짧은 시간에 너무 많은 요청이 접수되었습니다.",
                form_values=request.form,
            )

        role_name = (request.form.get("role_name") or "").strip()
        core_tasks = clean_text(request.form.get("core_tasks"), 3000)
        raw_email = request.form.get("knu_email", "").strip()
        knu_email = raw_email.lower()
        if raw_email and (len(raw_email) > 254 or not raw_email.isascii() or not KNU_EMAIL_RE.fullmatch(knu_email)):
            return _render_public(
                form,
                token_str,
                status_code=400,
                error_message="경북대 학교 메일(@knu.ac.kr) 형식으로 입력해주세요.",
                form_values=request.form,
            )
        if role_name not in OFFICER_HANDOVER_ROLES:
            return _render_public(
                form,
                token_str,
                status_code=400,
                error_message="맡았던 임원 직책을 선택해주세요.",
                form_values=request.form,
            )
        if not core_tasks:
            return _render_public(
                form,
                token_str,
                status_code=400,
                error_message="한 학기 동안 맡은 핵심 업무 3가지를 입력해주세요.",
                form_values=request.form,
            )

        payload = {
            "id": str(uuid.uuid4()),
            "form_id": form["id"],
            "role_name": role_name,
            "author_name": clean_text(request.form.get("author_name"), 40) or None,
            "term_cohort": clean_text(request.form.get("term_cohort"), 40) or None,
            "knu_email": knu_email or None,
            "core_tasks": core_tasks,
            "hardships_and_tips": clean_text(request.form.get("hardships_and_tips"), 3000) or None,
            "assets_and_links": clean_text(request.form.get("assets_and_links"), 2000) or None,
            "common_issues": clean_text(request.form.get("common_issues"), 2000) or None,
            "next_officer_note": clean_text(request.form.get("next_officer_note"), 1500) or None,
            "created_at": _now_iso(),
        }
        db.table("officer_handover_responses").insert(payload).execute()
        return _render_public(
            form,
            token_str,
            status_code=200,
            submitted=True,
            submitted_role=role_name,
        )

    @app.get("/admin/handover")
    @login_required(role="admin")
    def admin_handover_surveys():
        db = get_db()
        forms = (
            db.table("officer_handover_forms")
            .select("*")
            .order("created_at", desc=True)
            .execute()
            .data
            or []
        )
        responses = (
            db.table("officer_handover_responses")
            .select("*")
            .order("created_at")
            .execute()
            .data
            or []
        )
        unlinked_staff = _match_handover_emails(db, responses)
        by_form = {}
        for row in responses:
            by_form.setdefault(row.get("form_id"), []).append(row)

        base = _public_base()
        for form in forms:
            form_responses = by_form.get(form["id"], [])
            form["share_url"] = f"{base}/handover/{form['share_token']}"
            form["response_count"] = len(form_responses)
            form["grouped_responses"] = _group_responses_by_role(form_responses)
            form["wiki_draft"] = build_handover_wiki_draft(form, form_responses)

        response = make_response(render_template(
            "admin_handover_surveys.html",
            forms=forms,
            roles=OFFICER_HANDOVER_ROLES,
            unlinked_staff=unlinked_staff,
        ))
        response.cache_control.no_store = True
        return response

    @app.post("/api/admin/handover/create")
    @login_required(role="admin")
    def admin_handover_create():
        check_csrf()
        data = request.get_json(silent=True) if request.is_json else None
        source = data if isinstance(data, dict) else request.form
        title = clean_text(source.get("title"), 120)
        if not title:
            return jsonify(ok=False, error="설문 제목을 입력해주세요."), 400
        term_label = clean_text(source.get("term_label"), 60) or None

        now_iso = _now_iso()
        row = {
            "id": str(uuid.uuid4()),
            "share_token": str(uuid.uuid4()),
            "title": title,
            "term_label": term_label,
            "status": "open",
            "created_by": session.get("user_id"),
            "created_at": now_iso,
            "updated_at": now_iso,
        }
        inserted = get_db().table("officer_handover_forms").insert(row).execute().data or [row]
        form = inserted[0]
        share_url = f"{_public_base()}/handover/{form['share_token']}"
        return jsonify(ok=True, form=form, share_url=share_url)

    @app.post("/api/admin/handover/<form_id>/status")
    @login_required(role="admin")
    def admin_handover_status(form_id):
        check_csrf()
        db = get_db()
        existing = (
            db.table("officer_handover_forms")
            .select("*")
            .eq("id", str(form_id))
            .limit(1)
            .execute()
            .data
            or []
        )
        if not existing:
            return jsonify(ok=False, error="인수인계 설문을 찾을 수 없습니다."), 404
        form = existing[0]

        data = request.get_json(silent=True) if request.is_json else None
        source = data if isinstance(data, dict) else request.form
        requested = (source.get("status") or "").strip()
        if not requested:
            new_status = "closed" if form.get("status") == "open" else "open"
        elif requested in ("open", "closed"):
            new_status = requested
        else:
            return jsonify(ok=False, error="올바르지 않은 상태입니다."), 400

        updated = (
            db.table("officer_handover_forms")
            .update({"status": new_status, "updated_at": _now_iso()})
            .eq("id", str(form_id))
            .execute()
            .data
            or [dict(form, status=new_status)]
        )
        return jsonify(ok=True, status=new_status, form=updated[0])

    @app.post("/api/admin/handover/responses/<response_id>/delete")
    @login_required(role="admin")
    def admin_handover_response_delete(response_id):
        check_csrf()
        deleted = (
            get_db()
            .table("officer_handover_responses")
            .delete()
            .eq("id", str(response_id))
            .execute()
            .data
            or []
        )
        if not deleted:
            return jsonify(ok=False, error="응답을 찾을 수 없습니다."), 404
        return jsonify(ok=True)
