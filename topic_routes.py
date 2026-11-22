"""발제문(토픽) 이벤트·제출/조회·검수·Word 문서 출력·회원 읽기 라우트를 별도 모듈로 관리한다.

기존 app.py 에 흩어져 있던 발제문 관련 라우트와 토픽 전용 헬퍼를 한데 모아
`init_topic_routes`로 등록한다. 다른 모듈(records_activity_routes 등)과 동일하게
`get_supabase` 콜백을 통해 테스트 패치가 항상 동작하도록 내부에서 `db()` 헬퍼로
Supabase 클라이언트를 얻는다.

시간 계산은 `get_datetime` 콜백으로 주입받아 app 모듈의 `datetime`을 참조한다.
이는 기존 테스트가 `app.datetime`을 패치해 "지금"을 고정하는 동작(공유 발제문의
화요일 23:59 마감 검증)을 그대로 유지하기 위함이다.

예외는 로그에만 남기고 클라이언트에는 원문 예외(str(e))를 절대 노출하지 않는다.
"""
import os
import secrets
import uuid
from io import BytesIO
from datetime import timezone, timedelta, date, time
from types import SimpleNamespace

from flask import (
    Response, abort, flash, g, jsonify, redirect, render_template, request,
    session, url_for,
)
from guest_email_verify import normalize_knu_email, is_valid_knu_email, request_guest_email_code, verify_guest_email_code, get_verified_guest_email
from home_overview import decorate_topic_submission_states
from security_utils import forwarded_client_address
from term_membership import scope_members
from topic_credentials import (
    generate_topic_edit_token,
    legacy_pin_matches,
    topic_edit_token_digest,
    topic_edit_token_matches,
    topic_request_fingerprint,
)
from topic_document import number_topic_submissions, topic_submitter_identity
from topic_lifecycle import (
    KST,
    late_until_end_of_day,
    topic_event_close_at,
    topic_event_deadline,
    topic_event_is_expired,
    topic_event_late_open,
    topic_event_late_until,
    topic_event_original_expired,
)
from topic_preview import anonymous_topic_previews


# JSON API 공통 오류 메시지: 원문 예외(str(e))를 클라이언트에 노출하지 않는다.
SAFE_API_ERROR = '요청을 처리하지 못했습니다. 잠시 후 다시 시도해주세요.'
# HTML 뷰 공통 오류 플래시: 원문 예외를 노출하지 않는다.
SAFE_VIEW_ERROR = '발제문 정보를 불러오는 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요.'
SAFE_DOC_ERROR = '문서 생성 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요.'

TOPIC_LATE_MAX_DAYS = 30
TOPIC_EDIT_FAILURE_LIMIT = 10
TOPIC_EDIT_FAILURE_WINDOW_MINUTES = 15


def init_topic_routes(app, get_supabase, login_required, get_datetime, public_base_url):
    def db():
        return get_supabase()

    def _auto_close_topic_events(events):
        """공유 발제문은 세미나 주 화요일 23:59(한국시간)에 마감한다."""
        rows = list(events or [])
        week_ids = list({row['seminar_week_id'] for row in rows if row.get('seminar_week_id')})
        session_ids = list({row['seminar_session_id'] for row in rows
                            if row.get('seminar_session_id') and not row.get('seminar_week_id')})
        related_sessions = []
        if week_ids:
            related_sessions.extend(db().table('seminar_sessions')
                .select('id, seminar_week_id, meeting_date').in_('seminar_week_id', week_ids).execute().data or [])
        if session_ids:
            related_sessions.extend(db().table('seminar_sessions')
                .select('id, seminar_week_id, meeting_date').in_('id', session_ids).execute().data or [])
        for row in rows:
            row['session_dates'] = sorted({str(item['meeting_date'])[:10] for item in related_sessions
                if item.get('meeting_date') and (
                    (row.get('seminar_week_id') and item.get('seminar_week_id') == row['seminar_week_id'])
                    or (not row.get('seminar_week_id') and item.get('id') == row.get('seminar_session_id'))
                )})
            deadline = topic_event_deadline(row)
            row['submission_deadline'] = deadline.isoformat() if deadline else None
        today_kst = get_datetime().now(timezone(timedelta(hours=9))).date()
        for row in rows:
            _annotate_topic_late_window(row, today_kst)
        expired = [row for row in rows if row.get('is_active') and topic_event_is_expired(row, today=today_kst)]
        expired_ids = [row.get('id') for row in expired if row.get('id')]
        if expired_ids:
            try:
                db().table('topic_events').update({'is_active': False}).in_('id', expired_ids).execute()
            except Exception as exc:
                app.logger.warning("topic event auto-close sync failed: %s", exc)
            for row in expired:
                row['is_active'] = False
                row['auto_closed'] = True
        return rows

    def _annotate_topic_late_window(row, today_kst):
        """화면용: 추가 제출 기간 정보(원래 마감은 submission_deadline 그대로)."""
        late = topic_event_late_until(row)
        row['late_until_date'] = late.astimezone(timezone(timedelta(hours=9))).date().isoformat() if late else None
        row['late_open'] = topic_event_late_open(row, today=today_kst)
        row['original_expired'] = topic_event_original_expired(row, today=today_kst)
        close_at = topic_event_close_at(row)
        row['close_at_iso'] = close_at.isoformat() if close_at else None

    def _topic_event_for_submission(event_rows, session_id=None):
        """회차 링크의 마감은 공유 이벤트 전체를 닫지 않고 별도로 검사한다."""
        events = _auto_close_topic_events(event_rows)
        if not events:
            return None
        event = dict(events[0])
        if session_id:
            seminar_session = next((item for item in _topic_event_sessions(event)
                                    if str(item['id']) == str(session_id)), None)
            if not seminar_session:
                raise ValueError('이 발제문에 연결되지 않은 세미나 회차입니다.')
            event['submission_session_id'] = seminar_session['id']
            event['submission_meeting_date'] = seminar_session['meeting_date']
            deadline = topic_event_deadline(event)
            event['submission_deadline'] = deadline.isoformat() if deadline else None
            today_kst = get_datetime().now(timezone(timedelta(hours=9))).date()
            _annotate_topic_late_window(event, today_kst)
            if topic_event_is_expired(event, today=today_kst):
                event['is_active'] = False
        return event

    def _topic_event_sessions(event):
        """다운로드 날짜·사회자를 선택할 때 이벤트 소속 회차만 허용한다."""
        query = db().table('seminar_sessions').select('*')
        if event.get('seminar_week_id'):
            query = query.eq('seminar_week_id', event['seminar_week_id'])
        elif event.get('seminar_session_id'):
            query = query.eq('id', event['seminar_session_id'])
        else:
            return []
        return query.order('meeting_date').execute().data or []

    # 1. 관리자: 발제문 이벤트 생성 API
    def _open_topic_event_for_session(session_id):
        seminar_session = db().table('seminar_sessions').select(
            'id, meeting_date, book_title, book_author, seminar_week_id'
        ).eq('id', session_id).single().execute().data
        if not seminar_session:
            raise ValueError('세미나 회차를 찾을 수 없습니다.')

        week_id = seminar_session.get('seminar_week_id')
        existing_query = db().table('topic_events').select('*')
        existing_query = (existing_query.eq('seminar_week_id', week_id) if week_id
                          else existing_query.eq('seminar_session_id', session_id))
        existing = existing_query.execute().data or []
        if existing:
            return _auto_close_topic_events(existing)[0], False

        week = None
        if week_id:
            rows = db().table('seminar_weeks').select('*').eq('id', week_id).execute().data or []
            week = rows[0] if rows else None
        book_title = ((week or {}).get('book_title') or seminar_session.get('book_title') or '').strip()
        book_author = ((week or {}).get('book_author') or seminar_session.get('book_author') or '').strip()
        if not book_title:
            raise ValueError('먼저 이번 회차 도서 제목을 입력해주세요.')

        payload = {
            'meeting_date': seminar_session['meeting_date'],
            'book_title': book_title,
            'book_author': book_author or None,
            'seminar_session_id': session_id,
            'seminar_week_id': week_id,
            'share_token': str(uuid.uuid4()),
            'is_active': True,
        }
        try:
            created = db().table('topic_events').insert(payload).execute().data or []
            return created[0], True
        except Exception:
            # 동시에 두 번 눌린 경우 unique index가 중복을 막는다.
            raced_query = db().table('topic_events').select('*')
            raced_query = (raced_query.eq('seminar_week_id', week_id) if week_id
                           else raced_query.eq('seminar_session_id', session_id))
            raced = raced_query.execute().data or []
            if raced:
                return raced[0], False
            raise

    @app.route('/api/admin/topic_events/create', methods=['POST'])
    @login_required(role="admin")
    def create_topic_event():
        try:
            data = request.json or {}
            if data.get('seminar_session_id'):
                event, created = _open_topic_event_for_session(data['seminar_session_id'])
                return jsonify({
                    "status": "success", "created": created, "event": event,
                    "share_url": f"{public_base_url}/shared_topics?token={event['share_token']}"
                })
            token = str(uuid.uuid4())
            db().table('topic_events').insert({
                'meeting_date': data.get('meeting_date'),
                'book_title': data.get('book_title'),
                'book_author': data.get('book_author'),
                'share_token': token
            }).execute()
            return jsonify({"status": "success", "message": "발제문 수집 링크가 생성되었습니다."})
        except Exception as e:
            app.logger.error("create_topic_event error: %s", e, exc_info=True)
            return jsonify({"error": SAFE_API_ERROR}), 500

    @app.route('/api/admin/seminar_sessions/<session_id>/open_topics', methods=['POST'])
    @login_required(role="admin")
    def seminar_session_open_topics(session_id):
        try:
            event, created = _open_topic_event_for_session(session_id)
            return jsonify({
                'status': 'success', 'created': created, 'event': event,
                'share_url': f"{public_base_url}/shared_topics?token={event['share_token']}"
            })
        except ValueError as e:
            return jsonify({'status': 'error', 'message': str(e)}), 400
        except Exception as e:
            app.logger.error("seminar_session_open_topics error: %s", e, exc_info=True)
            return jsonify({'status': 'error', 'message': SAFE_API_ERROR}), 500

    @app.route('/api/admin/seminar_weeks/<week_id>/open_topics', methods=['POST'])
    @login_required(role="admin")
    def seminar_week_open_topics(week_id):
        try:
            sessions = db().table('seminar_sessions').select('id') \
                .eq('seminar_week_id', week_id).order('meeting_date').execute().data or []
            if not sessions:
                return jsonify({'status': 'error', 'message': '이 주차의 세미나 회차가 없습니다.'}), 404
            event, created = _open_topic_event_for_session(sessions[0]['id'])
            return jsonify({
                'status': 'success', 'created': created, 'event': event,
                'share_url': f"{public_base_url}/shared_topics?token={event['share_token']}"
            })
        except ValueError as e:
            return jsonify({'status': 'error', 'message': str(e)}), 400
        except Exception as e:
            app.logger.error("seminar_week_open_topics error: %s", e, exc_info=True)
            return jsonify({'status': 'error', 'message': SAFE_API_ERROR}), 500

    # 1.5. 관리자: 발제문 이벤트 영구 삭제 API (제출 내역까지 포함)
    @app.route('/api/admin/topic_events/<event_id>/delete', methods=['POST'])
    @login_required(role="admin")
    def delete_topic_event(event_id):
        try:
            db().table('topic_submissions').delete().eq('event_id', event_id).execute()
            db().table('topic_events').delete().eq('id', event_id).execute()
            return jsonify({"status": "success", "message": "발제문 이벤트가 영구 삭제되었습니다."})
        except Exception as e:
            app.logger.error("delete_topic_event error: %s", e, exc_info=True)
            return jsonify({"error": "이벤트 삭제 중 서버 오류가 발생했습니다."}), 500

    # 1.6. 관리자: 발제문 이벤트 활성/숨김 토글 (soft delete)
    @app.route('/api/admin/topic_events/<event_id>/toggle_active', methods=['POST'])
    @login_required(role="admin")
    def toggle_topic_event(event_id):
        try:
            cur = db().table('topic_events').select('*').eq('id', event_id).single().execute().data
            if not cur:
                return jsonify({"error": "이벤트를 찾을 수 없습니다."}), 404
            cur = _auto_close_topic_events([cur])[0]
            new_state = not bool(cur.get('is_active'))
            today_kst = get_datetime().now(timezone(timedelta(hours=9))).date()
            if new_state and topic_event_is_expired(cur, today=today_kst):
                return jsonify({"error": "제출 마감(세미나 주 화요일 23:59)이 지났습니다. ‘추가 제출’ 버튼으로 며칠 더 열 수 있습니다."}), 400
            db().table('topic_events').update({'is_active': new_state}).eq('id', event_id).execute()
            return jsonify({"status": "success", "is_active": new_state})
        except Exception as e:
            app.logger.error("toggle_topic_event error: %s", e, exc_info=True)
            return jsonify({"error": "상태 변경 중 오류가 발생했습니다."}), 500

    @app.route('/api/admin/topic_events/<event_id>/late_window', methods=['POST'])
    @login_required(role="admin")
    def topic_event_late_window(event_id):
        """추가 제출 기간 열기/연장/끝내기. 원래 마감(화요일 23:59)은 바꾸지 않는다.

        body: {"days": 1~30} 원래 마감(또는 이미 지났으면 오늘)부터 N일 더,
              {"until": "YYYY-MM-DD"} 그 날 23:59(한국시간)까지,
              {"action": "close"} 추가 제출 기간을 없앤다(원래 마감이 지났으면 바로 마감).
        """
        try:
            rows = db().table('topic_events').select('*').eq('id', event_id).limit(1).execute().data or []
            if not rows:
                return jsonify({"error": "이벤트를 찾을 수 없습니다."}), 404
            cur = _auto_close_topic_events(rows)[0]
            data = request.get_json(silent=True) or {}
            today_kst = get_datetime().now(timezone(timedelta(hours=9))).date()
            deadline = topic_event_deadline(cur)
            if data.get('action') == 'close':
                update = {'late_until': None}
                if topic_event_original_expired(cur, today=today_kst):
                    update['is_active'] = False
                db().table('topic_events').update(update).eq('id', event_id).execute()
                return jsonify({"status": "success", "late_until": None, "is_active": update.get('is_active', cur.get('is_active'))})
            if 'until' in data:
                try:
                    until = date.fromisoformat(str(data.get('until') or '')[:10])
                except ValueError:
                    return jsonify({"error": "날짜를 YYYY-MM-DD로 골라주세요."}), 400
            else:
                try:
                    days = int(data.get('days'))
                except (TypeError, ValueError):
                    return jsonify({"error": "며칠 더 열지 골라주세요."}), 400
                if not 1 <= days <= TOPIC_LATE_MAX_DAYS:
                    return jsonify({"error": f"1~{TOPIC_LATE_MAX_DAYS}일 사이로 골라주세요."}), 400
                base = max(deadline or today_kst, today_kst)
                until = base + timedelta(days=days)
            if until < today_kst or (deadline and until <= deadline):
                return jsonify({"error": "추가 제출 마감은 원래 마감보다 늦고 오늘 이후여야 합니다."}), 400
            if until > today_kst + timedelta(days=TOPIC_LATE_MAX_DAYS):
                return jsonify({"error": f"추가 제출은 오늘부터 최대 {TOPIC_LATE_MAX_DAYS}일까지 열 수 있습니다."}), 400
            late_until = late_until_end_of_day(until)
            db().table('topic_events').update({'late_until': late_until.isoformat(), 'is_active': True}) \
                .eq('id', event_id).execute()
            app.logger.warning('Topic event %s late window until %s by member %s', event_id, until.isoformat(),
                               session.get('user_id'))
            return jsonify({"status": "success", "late_until": until.isoformat(), "is_active": True})
        except Exception as e:
            app.logger.error("topic_event_late_window error: %s", e, exc_info=True)
            return jsonify({"error": "추가 제출 기간을 바꾸는 중 오류가 발생했습니다."}), 500

    def _authenticated_topic_member(event_id=None):
        """Return the active member tied to the authenticated session.

        Topic submission links are public, so client-provided names and student IDs
        must never be treated as proof of membership.  Refresh the member from the
        database using the server-side session ID and fail closed when the account is
        missing or no longer active.
        """
        user_id = session.get('user_id')
        if not user_id:
            return None

        try:
            rows = db().table('members').select(
                'id, name, department, student_id, account_status, member_status, is_active'
            ).eq('id', user_id).limit(1).execute().data or []
        except Exception as exc:
            app.logger.error("Topic member authorization refresh failed: %s", exc)
            return None

        if not rows:
            return None

        member = rows[0]
        if (
            member.get('account_status') != 'active'
            or member.get('member_status') == 'inactive'
            or not (member.get('name') or '').strip()
        ):
            return None
        if event_id:
            try:
                events = db().table('topic_events').select('seminar_session_id,seminar_week_id').eq('id', event_id).limit(1).execute().data or []
                event = events[0] if events else {}
                related = []
                if event.get('seminar_week_id'):
                    related = db().table('seminar_sessions').select('term_id').eq('seminar_week_id', event['seminar_week_id']).limit(1).execute().data or []
                elif event.get('seminar_session_id'):
                    related = db().table('seminar_sessions').select('term_id').eq('id', event['seminar_session_id']).limit(1).execute().data or []
                if related and related[0].get('term_id'):
                    member = scope_members(db(), [member], term_id=related[0]['term_id'])[0]
            except Exception:
                app.logger.exception('Topic semester membership lookup failed')
                return None
        if member.get('is_active') is False:
            return None
        return member

    def _topic_edit_request_hash(event_id):
        address = forwarded_client_address(
            request.headers.get('X-App-Client-IP') if g.get('trusted_app_proxy') else None, request.remote_addr
        )
        return topic_request_fingerprint(address, event_id, app.secret_key)

    def _topic_edit_is_rate_limited(event_id):
        request_hash = _topic_edit_request_hash(event_id)
        rate_start = (
            get_datetime().now(timezone.utc) - timedelta(minutes=TOPIC_EDIT_FAILURE_WINDOW_MINUTES)
        ).isoformat()
        try:
            attempts = db().table('topic_edit_attempts').select('id', count='exact') \
                .eq('event_id', event_id).eq('request_hash', request_hash) \
                .eq('succeeded', False).gte('created_at', rate_start).execute()
            return (attempts.count or 0) >= TOPIC_EDIT_FAILURE_LIMIT
        except Exception as exc:
            app.logger.warning("topic edit rate-limit lookup failed: %s", exc)
            return False

    def _record_topic_edit_attempt(event_id, succeeded):
        try:
            db().table('topic_edit_attempts').insert({
                'event_id': event_id,
                'request_hash': _topic_edit_request_hash(event_id),
                'succeeded': bool(succeeded),
            }).execute()
        except Exception as exc:
            app.logger.warning("topic edit attempt audit failed: %s", exc)

    def _guest_topic_credential_matches(existing_record, credential):
        identity_kind = existing_record.get('identity_kind')
        if not identity_kind:
            identity_kind = (
                'legacy_member'
                if existing_record.get('pin_code') == 'MEMBER'
                else 'legacy_pin'
            )
        if identity_kind == 'guest':
            return topic_edit_token_matches(
                existing_record.get('edit_token_hash'), credential, app.secret_key
            )
        if identity_kind == 'legacy_pin':
            return legacy_pin_matches(existing_record.get('pin_code'), credential)
        return False

    def _email_owns_topic(row, email):
        if not email:
            return False
        if row.get('knu_email') == email:
            return True
        sid = row.get('student_id')
        if not sid:
            return False
        members = db().table('members').select('*').eq('student_id', sid).eq('knu_email', email).execute().data or []
        return any(m.get('account_status') == 'active' and m.get('member_status') not in ('inactive', 'blocked') and m.get('is_active') is not False for m in members)

    @app.post('/api/topics/edit-email/request')
    def topic_email_request():
        data = request.get_json(silent=True) or {}
        event_id = str(data.get('event_id') or '')
        if not event_id or not (db().table('topic_events').select('id').eq('id', event_id).limit(1).execute().data or []):
            return jsonify(ok=False, error='유효하지 않은 발제문 행사입니다.'), 400
        try:
            email = request_guest_email_code(app, db(), data.get('email'), 'topic_edit', '발제문 수정', event_id)
            return jsonify(ok=True, email=email)
        except ValueError as exc:
            return jsonify(ok=False, error=str(exc)), 429 if ('잦습니다' in str(exc) or '잠시' in str(exc)) else 400
        except Exception:
            app.logger.exception('Topic email delivery failed')
            return jsonify(ok=False, error='인증 메일을 보내지 못했습니다. 잠시 후 다시 시도해주세요.'), 503

    @app.post('/api/topics/edit-email/verify')
    def topic_email_verify():
        data = request.get_json(silent=True) or {}
        event_id = str(data.get('event_id') or '')
        if not verify_guest_email_code(app, db(), 'topic_edit', event_id, data.get('code')):
            return jsonify(ok=False, error='인증번호가 올바르지 않거나 만료되었습니다.'), 400
        email = get_verified_guest_email('topic_edit', event_id)
        rows = db().table('topic_submissions').select('*').eq('event_id', event_id).execute().data or []
        row = next ( (r for r in rows if _email_owns_topic(r, email)), None)
        submission = {k: row.get(k) for k in ('author_name', 'department', 'student_id', 'topics', 'topic_limit')} if row else None
        return jsonify(ok=True, email=email, found=bool(row), submission=submission)

    def _topic_edit_denial(existing_record, member, credential, event_id):
        """Account-owned posts use the session; link submissions keep their edit code.

        Roster registration is not a login requirement for public submission links.
        Logging in later must not bypass a link submission's edit code either.
        """
        if _email_owns_topic(existing_record, get_verified_guest_email('topic_edit', str(event_id))):
            return None
        owner_id = existing_record.get('member_id')
        if member and owner_id is not None:
            if str(owner_id) == str(member.get('id')):
                return None
            return jsonify({"error": "수정 권한을 확인할 수 없습니다."}), 403
        if member and existing_record.get('pin_code') == 'MEMBER':
            # Compatibility with account submissions made before member_id existed.
            return None
        if _topic_edit_is_rate_limited(event_id):
            return jsonify({"error": "수정 확인이 잠시 제한되었습니다. 15분 후 다시 시도해주세요."}), 429
        credential_ok = _guest_topic_credential_matches(existing_record, credential)
        _record_topic_edit_attempt(event_id, credential_ok)
        if not credential_ok:
            return jsonify({
                "error": "수정 권한을 확인할 수 없습니다. 로그인하거나 제출 시 입력한 학교 메일(@knu.ac.kr)로 6자리 인증 후 수정해주세요.",
                "code": "edit_credential_required",
            }), 403
        return None

    # 2. 사용자: 공유 링크를 통한 발제문 작성 페이지
    @app.route('/shared_topics')
    def view_shared_topics():
        token = request.args.get('token')
        if not token:
            flash("잘못된 접근입니다.", "danger")
            return redirect(url_for('main_index'))

        try:
            event_res = db().table('topic_events').select('*').eq('share_token', token).single().execute()
            event_data = event_res.data
            if event_data:
                event_data = _topic_event_for_submission([event_data], request.args.get('session_id'))
            if not event_data or not event_data.get('is_active'):
                flash("마감되었거나 유효하지 않은 링크입니다.", "warning")
                return redirect(url_for('main_index'))

            # 중복 방지용 공개 영역에는 발제 JSON만 조회한다. 작성자 정보는 서버에서부터 가져오지 않는다.
            preview_rows = db().table('topic_submissions').select('topics') \
                .eq('event_id', event_data['id']).order('created_at').execute().data or []
            existing_topic_previews = anonymous_topic_previews(preview_rows)

            member = _authenticated_topic_member(event_data['id'])
            user_name = member.get('name') if member else None
            user_department = member.get('department') if member else None
            user_student_id = member.get('student_id') if member else None
            classroom_term = None
            if member and event_data.get('seminar_week_id'):
                week_rows = db().table('seminar_weeks').select('term_id').eq('id', event_data['seminar_week_id']).limit(1).execute().data or []
                if week_rows:
                    term_rows = db().table('seminar_terms').select('id,name').eq('id', week_rows[0]['term_id']).limit(1).execute().data or []
                    classroom_term = term_rows[0] if term_rows else None
                decorate_topic_submission_states(db(), member['id'], [event_data])
            return render_template('topic_submit.html',
                                   event=event_data, classroom_term=classroom_term,
                                   user_name=user_name,
                                   user_department=user_department,
                                   user_student_id=user_student_id,
                                   existing_topic_previews=existing_topic_previews)
        except Exception as e:
            app.logger.error("view_shared_topics error: %s", e, exc_info=True)
            return "유효하지 않은 링크입니다.", 404

    # 3. 사용자: 발제문 제출/수정 API (PIN 검증 포함)
    @app.route('/api/topics/submit', methods=['POST'])
    def submit_topics():
        data = request.get_json(silent=True) or {}
        event_id = data.get('event_id')
        author_name = (data.get('author_name') or '').strip()
        department = (data.get('department') or '').strip()
        edit_credential = str(data.get('edit_credential') or data.get('pin_code') or '').strip()
        student_id = (data.get('student_id') or '').strip()
        topics = data.get('topics')  # JSON Array
        raw_email = data.get('knu_email') or ''
        knu_email = normalize_knu_email(raw_email)
        if raw_email and not is_valid_knu_email(raw_email, knu_email):
            return jsonify(error='경북대 학교 메일(@knu.ac.kr) 형식을 확인해주세요.'), 400

        # 회원 권한은 입력한 이름/학번이 아니라 서버 세션의 member id로만 확인한다.
        member = _authenticated_topic_member(event_id)
        is_logged_in_member = member is not None
        if member:
            author_name = (member.get('name') or '').strip()
            department = (member.get('department') or department).strip()
            student_id = str(member.get('student_id') or student_id).strip()

        if not all([event_id, author_name, department, topics]):
            return jsonify({"error": "필수 정보를 모두 입력해주세요."}), 400

        try:
            event_rows = db().table('topic_events').select('*') \
                .eq('id', event_id).limit(1).execute().data or []
            event_data = _topic_event_for_submission(event_rows, data.get('session_id'))
            if not event_data or not event_data.get('is_active'):
                return jsonify({"error": "발제문 제출 마감(세미나 주 화요일 23:59)이 지나 제출이 마감되었습니다."}), 400

            # 기존 제출 내역 확인 (학번 우선 매칭 — 학과 표기만 바꿔 여러 건 제출하는 것 방지)
            existing_record = _find_topic_submission(
                event_id,
                author_name,
                department,
                student_id,
                member_id=member.get('id') if member else None,
            )

            # 학번에서 입학년도 2자리 추출 (예: "2022123456" → "22")
            # student_id 가 4자 이상이면 3-4번째 문자 사용
            admission_year = ''
            sid = (student_id or '').strip()
            if len(sid) >= 4 and sid[2:4].isdigit():
                admission_year = sid[2:4]

            # 발제문 개수 제한: 1개는 필수, 기본 한도는 선택 제출 1개를 더한 2개.
            # 회장이 개별적으로 바꾼 기존 한도는 그대로 따른다.
            topic_limit = (existing_record or {}).get('topic_limit') or 2
            if len(topics) > topic_limit:
                return jsonify({"error": f"발제문은 {topic_limit}개까지 작성할 수 있습니다. 더 쓰고 싶다면 회장에게 문의해주세요."}), 400

            if existing_record:
                issued_edit_token = None
                denial = _topic_edit_denial(existing_record, member, edit_credential, event_id)
                if denial is not None:
                    return denial

                # 업데이트 실행
                update_payload = {'topics': topics, 'updated_at': 'now()', 'department': department}
                if knu_email and not is_logged_in_member and (not existing_record.get('knu_email') or existing_record.get('knu_email') == knu_email):
                    update_payload['knu_email'] = knu_email
                if admission_year:
                    update_payload['admission_year'] = admission_year
                if sid:
                    update_payload['student_id'] = sid
                if is_logged_in_member and (
                    existing_record.get('member_id') is not None
                    or existing_record.get('pin_code') == 'MEMBER'
                ):
                    update_payload.update({
                        'member_id': member.get('id'),
                        'identity_kind': 'member',
                        'credential_version': 2,
                        'pin_code': 'MEMBER',
                        'edit_token_hash': None,
                    })
                elif existing_record.get('identity_kind') in (None, 'legacy_pin'):
                    issued_edit_token = generate_topic_edit_token()
                    update_payload.update({
                        'identity_kind': 'guest',
                        'credential_version': 2,
                        'pin_code': 'TOKEN',
                        'edit_token_hash': topic_edit_token_digest(
                            issued_edit_token, app.secret_key
                        ),
                    })
                db().table('topic_submissions').update(update_payload) \
                    .eq('id', existing_record['id']).execute()
                response = {"status": "success", "message": "발제문이 성공적으로 수정되었습니다."}
                if issued_edit_token:
                    response['edit_token'] = issued_edit_token
                    response['message'] = "발제문이 수정되었고, 안전한 새 수정 코드가 발급되었습니다."
                return jsonify(response)
            else:
                # 명부 등록 여부와 관계없이 공개 링크에서 제출할 수 있다.
                # 비로그인 제출은 계정 소유권을 부여하지 않고 수정 코드로 보호한다.
                issued_edit_token = None
                insert_payload = {
                    'event_id': event_id,
                    'author_name': author_name,
                    'department': department,
                    'admission_year': admission_year or None,
                    'student_id': sid or None,
                    'topics': topics
                }
                if knu_email and not is_logged_in_member:
                    insert_payload['knu_email'] = knu_email
                if is_logged_in_member:
                    insert_payload.update({
                        'member_id': member.get('id'),
                        'identity_kind': 'member',
                        'credential_version': 2,
                        'pin_code': 'MEMBER',
                        'edit_token_hash': None,
                    })
                else:
                    issued_edit_token = generate_topic_edit_token()
                    insert_payload.update({
                        'member_id': None,
                        'identity_kind': 'guest',
                        'credential_version': 2,
                        'pin_code': 'TOKEN',
                        'edit_token_hash': topic_edit_token_digest(
                            issued_edit_token, app.secret_key
                        ),
                    })
                db().table('topic_submissions').insert(insert_payload).execute()
                response = {"status": "success", "message": "발제문이 성공적으로 제출되었습니다."}
                if issued_edit_token:
                    response['edit_token'] = issued_edit_token
                    response['message'] = "발제문이 제출되었습니다. 아래 수정 코드를 꼭 보관해주세요."
                return jsonify(response)

        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        except Exception as e:
            app.logger.error("submit_topics error: %s", e, exc_info=True)
            return jsonify({"error": "제출 중 서버 오류가 발생했습니다."}), 500

    def _find_topic_submission(event_id, author_name, department, student_id, member_id=None):
        """같은 이벤트에서 같은 사람의 기존 제출물을 찾는다.
        학번이 있으면 (event_id, student_id)로 우선 매칭하고,
        없거나 매칭 실패 시 과거 데이터 호환을 위해 (event_id, author_name, department)로 폴백한다."""
        if member_id is not None:
            member_res = db().table('topic_submissions').select('*') \
                .eq('event_id', event_id).eq('member_id', member_id).execute()
            if member_res.data:
                return member_res.data[0]

        sid = (student_id or '').strip()
        if sid:
            res = db().table('topic_submissions').select('*') \
                .eq('event_id', event_id).eq('student_id', sid).execute()
            if res.data:
                # Finding a record is not authorization. The caller checks its owner
                # or edit code, including when a link submitter logs in later.
                return res.data[0]
        res = db().table('topic_submissions').select('*') \
            .eq('event_id', event_id).eq('author_name', author_name).eq('department', department).execute()
        if not res.data:
            return None
        return res.data[0]

    # 3.5. 사용자: 발제문 불러오기 API
    @app.route('/api/topics/load', methods=['POST'])
    def load_topics():
        data = request.get_json(silent=True) or {}
        event_id = data.get('event_id')
        author_name = (data.get('author_name') or '').strip()
        department = (data.get('department') or '').strip()
        edit_credential = str(data.get('edit_credential') or data.get('pin_code') or '').strip()
        student_id = (data.get('student_id') or '').strip()

        # 회원 권한은 입력한 이름/학번이 아니라 서버 세션의 member id로만 확인한다.
        member = _authenticated_topic_member(event_id)
        if member:
            author_name = (member.get('name') or '').strip()
            department = (member.get('department') or department).strip()
            student_id = str(member.get('student_id') or student_id).strip()

        if not all([event_id, author_name, department]):
            return jsonify({"error": "이름과 소속을 모두 입력해주세요."}), 400

        try:
            event_rows = db().table('topic_events').select('*') \
                .eq('id', event_id).limit(1).execute().data or []
            event_data = _topic_event_for_submission(event_rows, data.get('session_id'))
            if not event_data or not event_data.get('is_active'):
                return jsonify({"error": "발제문 제출 마감(세미나 주 화요일 23:59)이 지나 제출이 마감되었습니다."}), 400

            existing_record = _find_topic_submission(
                event_id,
                author_name,
                department,
                student_id,
                member_id=member.get('id') if member else None,
            )

            if existing_record:
                denial = _topic_edit_denial(existing_record, member, edit_credential, event_id)
                if denial is not None:
                    return denial

                return jsonify({
                    "status": "success",
                    "topics": existing_record['topics'],
                    "topic_limit": existing_record.get('topic_limit') or 2,
                })
            else:
                return jsonify({"error": "작성된 발제문 내역이 없습니다. 처음 작성하는 것이 맞나요?"}), 404

        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        except Exception as e:
            app.logger.error("load_topics error: %s", e, exc_info=True)
            return jsonify({"error": "불러오기 중 서버 오류가 발생했습니다."}), 500

    # 3.7 관리자: 발제문 제출 내역 삭제/수정 API (다른 사람의 것도 관리 가능)
    @app.route('/api/admin/topic_submissions/<submission_id>/delete', methods=['POST'])
    @login_required(role="admin")
    def admin_delete_topic_submission(submission_id):
        try:
            db().table('topic_submissions').delete().eq('id', submission_id).execute()
            return jsonify({"status": "success", "message": "발제문이 삭제되었습니다."})
        except Exception as e:
            app.logger.error("admin_delete_topic_submission error: %s", e, exc_info=True)
            return jsonify({"error": "삭제 중 오류가 발생했습니다."}), 500

    @app.route('/api/admin/topic_submissions/<submission_id>/update', methods=['POST'])
    @login_required(role="admin")
    def admin_update_topic_submission(submission_id):
        try:
            data = request.json or {}
            topics = data.get('topics')
            if not topics or not isinstance(topics, list):
                return jsonify({"error": "발제문 내용이 비어있습니다."}), 400
            update_fields = {'topics': topics, 'updated_at': 'now()'}
            # 작성자/소속도 함께 수정할 수 있게 허용
            if data.get('author_name'):
                update_fields['author_name'] = data['author_name']
            if data.get('department'):
                update_fields['department'] = data['department']
            db().table('topic_submissions').update(update_fields).eq('id', submission_id).execute()
            return jsonify({"status": "success", "message": "발제문이 수정되었습니다."})
        except Exception as e:
            app.logger.error("admin_update_topic_submission error: %s", e, exc_info=True)
            return jsonify({"error": "수정 중 오류가 발생했습니다."}), 500

    @app.route('/api/admin/topic_submissions/<submission_id>/set_limit', methods=['POST'])
    @login_required(role="admin")
    def admin_set_topic_limit(submission_id):
        """회장이 특정 제출자의 발제문 한도를 개별적으로 조정합니다."""
        try:
            limit = int((request.json or {}).get('topic_limit', 2))
            if not (1 <= limit <= 10):
                return jsonify({"error": "한도는 1~10 사이여야 합니다."}), 400
            db().table('topic_submissions').update({'topic_limit': limit}).eq('id', submission_id).execute()
            return jsonify({"status": "success", "message": f"발제문 한도가 {limit}개로 변경되었습니다."})
        except (TypeError, ValueError):
            return jsonify({"error": "올바른 숫자를 입력해주세요."}), 400
        except Exception as e:
            app.logger.error("admin_set_topic_limit error: %s", e, exc_info=True)
            return jsonify({"error": "한도 변경 중 오류가 발생했습니다."}), 500

    # 3.8 관리자: 발제문 상세 보기 및 취합 페이지
    @app.route('/admin/topics/<event_id>/view')
    @login_required(role="admin")
    def view_admin_topics(event_id):
        try:
            event = db().table('topic_events').select('*').eq('id', event_id).single().execute().data
            if not event:
                abort(404)
            event = _auto_close_topic_events([event])[0]
            submissions = db().table('topic_submissions').select('*').eq('event_id', event_id).order(
                'created_at').execute().data
            submissions = number_topic_submissions(submissions)
            original_close = (get_datetime().combine(date.fromisoformat(event['submission_deadline']), time(23, 59, 59), KST)
                              if event.get('submission_deadline') else None)
            for sub in submissions or []:
                try:
                    created = get_datetime().fromisoformat(str(sub.get('created_at') or '').replace('Z', '+00:00'))
                    sub['late_submission'] = bool(original_close and created.tzinfo and created > original_close)
                except ValueError:
                    sub['late_submission'] = False

            return render_template('admin_topic_view.html', event=event, submissions=submissions,
                                   seminar_sessions=_topic_event_sessions(event))
        except Exception as e:
            app.logger.error("view_admin_topics error: %s", e, exc_info=True)
            flash(SAFE_VIEW_ERROR, "danger")
            return redirect(url_for('admin_dashboard'))

    def _moderator_name(value):
        name = ' '.join(str(value or '').split())
        if not name or len(name) > 100:
            raise ValueError('사회자 이름을 1~100자로 입력해주세요.')
        return name

    def _render_topic_document_setup(event, seminar_sessions, selected_session, download, error=None):
        members = db().table('members').select('id, name, department') \
            .eq('is_active', True).order('name').execute().data or []
        csrf_token = session.setdefault('topic_moderator_csrf', secrets.token_urlsafe(32))
        return render_template('topic_document_setup.html', event=event,
            seminar_sessions=seminar_sessions, selected_session=selected_session,
            moderator_name=(selected_session or event).get('moderator_name', ''),
            members=members, download=download, error=error, csrf_token=csrf_token)

    def _valid_topic_moderator_csrf():
        expected = session.get('topic_moderator_csrf') or ''
        supplied = request.form.get('csrf_token') or ''
        return bool(expected and supplied and secrets.compare_digest(expected, supplied))

    @app.route('/admin/seminar_sessions/<session_id>/moderator', methods=['GET', 'POST'])
    @login_required(role='admin')
    def seminar_session_moderator(session_id):
        rows = db().table('seminar_sessions').select('*').eq('id', session_id).limit(1).execute().data or []
        if not rows:
            abort(404)
        seminar_session = rows[0]
        if request.method == 'POST':
            if not _valid_topic_moderator_csrf():
                abort(403)
            try:
                name = _moderator_name(request.form.get('moderator_name'))
                updated = db().table('seminar_sessions').update({'moderator_name': name}) \
                    .eq('id', session_id).execute().data or []
                if not updated:
                    raise RuntimeError('회차가 변경되었거나 삭제되었습니다.')
            except ValueError as exc:
                return _render_topic_document_setup(seminar_session, [seminar_session],
                    seminar_session, False, error=str(exc)), 400
            except Exception as exc:
                app.logger.error('seminar moderator save failed: %s', exc, exc_info=True)
                return _render_topic_document_setup(seminar_session, [seminar_session],
                    seminar_session, False, error='사회자를 저장하지 못했습니다. 잠시 후 다시 시도해주세요.'), 503
            flash('이 회차의 사회자를 저장했습니다.', 'success')
            return redirect(url_for('admin_seminars', term_id=seminar_session.get('term_id')))
        return _render_topic_document_setup(seminar_session, [seminar_session], seminar_session, False)

    @app.route('/admin/topics/<event_id>/document_setup', methods=['GET', 'POST'])
    @login_required(role='admin')
    def topic_document_setup(event_id):
        rows = db().table('topic_events').select('*').eq('id', event_id).limit(1).execute().data or []
        if not rows:
            abort(404)
        event = rows[0]
        seminar_sessions = _topic_event_sessions(event)
        session_id = request.form.get('session_id') if request.method == 'POST' else request.args.get('session_id')
        selected = next((item for item in seminar_sessions if str(item['id']) == str(session_id)), None)
        if session_id and not selected:
            abort(400, description='이 발제문에 연결되지 않은 세미나 회차입니다.')
        if len(seminar_sessions) == 1 and not selected:
            selected = seminar_sessions[0]
        download = request.values.get('download', '1') != '0'
        if request.method == 'POST':
            if not _valid_topic_moderator_csrf():
                abort(403)
            try:
                if seminar_sessions and not selected:
                    raise ValueError('Word에 표시할 세미나 날짜를 선택해주세요.')
                name = _moderator_name(request.form.get('moderator_name'))
                table = 'seminar_sessions' if selected else 'topic_events'
                target_id = selected['id'] if selected else event_id
                updated = db().table(table).update({'moderator_name': name}).eq('id', target_id).execute().data or []
                if not updated:
                    raise RuntimeError('세미나 정보가 변경되었거나 삭제되었습니다.')
            except ValueError as exc:
                return _render_topic_document_setup(event, seminar_sessions, selected, download, error=str(exc)), 400
            except Exception as exc:
                app.logger.error('topic document metadata save failed: %s', exc, exc_info=True)
                return _render_topic_document_setup(event, seminar_sessions, selected, download,
                    error='사회자를 저장하지 못했습니다. 잠시 후 다시 시도해주세요.'), 503
            if download:
                return redirect(url_for('download_topics_word', event_id=event_id,
                                        session_id=selected['id'] if selected else None))
            flash('사회자를 저장했습니다.', 'success')
            return redirect(url_for('view_admin_topics', event_id=event_id))
        return _render_topic_document_setup(event, seminar_sessions, selected, download)

    # 4. 관리자: Word 파일로 출력 (template.docx 디자인 유지)
    # - docxtpl 라이브러리 버전 차이로 production에서 일부 iteration이 누락되는 이슈가 보고됨.
    #   대응:
    #   1) requirements.txt에 python-docx, docxtpl 버전 핀 (로컬과 동일하게 맞춤)
    #   2) 렌더링 후 모든 제출자의 이름이 문서에 실제로 들어갔는지 검증
    #   3) 누락 발견 시 누락된 제출만 python-docx로 문서 끝에 append (디자인은 일부 상이하나 누락 방지)
    @app.route('/admin/topics/<event_id>/download_word')
    @login_required(role="admin")
    def download_topics_word(event_id):
        try:
            from docxtpl import DocxTemplate
            from docx import Document
            from docx.shared import Pt, RGBColor
            from docx.enum.text import WD_BREAK

            event = db().table('topic_events').select('*').eq('id', event_id).single().execute().data
            if not event:
                return '발제문을 찾을 수 없습니다.', 404
            seminar_sessions = _topic_event_sessions(event)
            session_id = request.args.get('session_id')
            selected = next((item for item in seminar_sessions if str(item['id']) == str(session_id)), None)
            if session_id and not selected:
                return '이 발제문에 연결되지 않은 세미나 회차입니다.', 400
            if len(seminar_sessions) == 1 and not selected:
                selected = seminar_sessions[0]
            metadata = selected or event
            if (seminar_sessions and not selected) or not str(metadata.get('moderator_name') or '').strip():
                return redirect(url_for('topic_document_setup', event_id=event_id, session_id=session_id))
            # GET 다운로드에서는 저장하지 않는다. 사회자·날짜는 선택한 회차의 표시값만 사용한다.
            event = dict(event, meeting_date=metadata.get('meeting_date'), moderator_name=metadata['moderator_name'])
            submissions = db().table('topic_submissions').select('*') \
                .eq('event_id', event_id).order('created_at').execute().data or []
            submissions = number_topic_submissions(submissions)
            app.logger.info(f"download_topics_word: 제출 {len(submissions)}건")

            template_path = os.path.join(app.root_path, 'templates', 'template.docx')
            if not os.path.exists(template_path):
                flash("템플릿 워드 파일(template.docx)을 templates 폴더에서 찾을 수 없습니다.", "danger")
                return redirect(url_for('admin_dashboard'))

            # 1) docxtpl로 템플릿 렌더링 (원본 디자인 유지)
            # ※ 발제문 내용에 '<책제목>' 같이 꺾쇠괄호가 들어가면 Word XML 구조를 깨뜨려서
            #   해당 지점 이후 렌더링이 중단되고 파일이 손상됨.
            #   docxtpl의 자동 escape이 production 환경에서 일관되지 않게 동작하므로,
            #   사전에 풀-와이드 유니코드(〈, 〉)로 치환해서 시각적으로는 동일하지만 안전하게 처리.
            def _safe(s):
                if s is None:
                    return ''
                return (str(s)
                        .replace('<', '〈')
                        .replace('>', '〉'))

            doc = DocxTemplate(template_path)
            date_str = (event.get('meeting_date') or '').replace('-', '.')
            template_submissions = []
            for sub in submissions:
                identity = topic_submitter_identity(sub)
                template_submissions.append({
                    # 기존 템플릿의 department + author_name 배치를 유지하면서
                    # '전자공학부 22 박민서' 형태로 표시한다.
                    'department': _safe(identity['department_and_year']),
                    'author_name': _safe(identity['author_name']),
                    'topics': [
                        {
                            'topic': _safe(t.get('topic', '')),
                            'page': _safe(t.get('page', '')),
                            'reference': _safe(t.get('reference', '')),
                            'number': t.get('number'),
                        }
                        for t in (sub.get('topics') or [])
                    ],
                })
            context = {
                'book_title': _safe(event.get('book_title', '')),
                'meeting_date': date_str,
                'book_author': _safe(event.get('book_author', '')),
                'moderator_name': _safe(event['moderator_name']),
                'submissions': template_submissions,
            }
            doc.render(context, autoescape=True)

            # 메모리에 저장
            buf = BytesIO()
            doc.save(buf)
            buf.seek(0)

            # 2) 렌더링 검증 — 모든 제출자가 본문에 들어갔는지 확인 (누락 방지)
            import zipfile, re
            buf.seek(0)
            with zipfile.ZipFile(BytesIO(buf.getvalue())) as zin:
                body_xml = zin.read('word/document.xml').decode('utf-8', errors='replace')
            # 본문 plaintext만 추출
            body_text = ''.join(re.findall(r'<w:t[^>]*>([^<]*)</w:t>', body_xml))
            # 각 제출자가 '발제자' 섹션에 들어갔는지 검사: 이름 등장 횟수가 2 이상이면 OK
            # (1회: 참석자 명단, 2회 이상: 발제자 섹션 포함)
            missing = []
            for sub in submissions:
                nm = (sub.get('author_name') or '').strip()
                dept = (sub.get('department') or '').strip()
                if not nm:
                    continue
                # 이름이 '발제자' 섹션에 등장하는지 검사: '발제자' 텍스트 이후에 이름이 등장하는지
                # 간단하게 본문 전체에서 이름 등장 횟수로 판별
                cnt = body_text.count(nm)
                if cnt < 2:  # 참석자 명단 1회만 있고 발제 섹션엔 없음
                    missing.append(sub)
            if missing:
                app.logger.warning(f"download_topics_word: 누락 감지 {len(missing)}건 → python-docx로 append")
                # 3) 누락된 제출을 문서 끝에 직접 추가
                doc2 = Document(BytesIO(buf.getvalue()))
                for sub in missing:
                    # 페이지 나눔
                    br_p = doc2.add_paragraph()
                    br_p.add_run().add_break(WD_BREAK.PAGE)
                    # 발제자 헤더
                    hp = doc2.add_paragraph()
                    r1 = hp.add_run('발제자: ')
                    r1.bold = True
                    r1.font.size = Pt(13)
                    r1.font.color.rgb = RGBColor(0, 102, 204)
                    r2 = hp.add_run(topic_submitter_identity(sub)['full_label'])
                    r2.bold = True
                    r2.font.size = Pt(13)
                    # 발제 내용
                    for t in sub.get('topics') or []:
                        topic_text = (t.get('topic') or '').strip()
                        page = (t.get('page') or '').strip()
                        reference = (t.get('reference') or '').strip()
                        p = doc2.add_paragraph()
                        rn = p.add_run(f"{t.get('number')}. "); rn.bold = True; rn.font.size = Pt(11)
                        first = True
                        for line in topic_text.split('\n'):
                            if not first:
                                p.add_run().add_break()
                            rr = p.add_run(line); rr.font.size = Pt(11); first = False
                        if page or reference:
                            meta = doc2.add_paragraph()
                            parts = []
                            if page: parts.append(f"페이지: {page}")
                            if reference: parts.append(f"참조: {reference}")
                            rm = meta.add_run('   ' + ' | '.join(parts))
                            rm.italic = True; rm.font.size = Pt(10)
                            rm.font.color.rgb = RGBColor(102, 102, 102)
                buf = BytesIO()
                doc2.save(buf)
                buf.seek(0)

            # === 최종 폰트 일괄 적용: 함초롱바탕 ===
            # 한글은 w:eastAsia 속성까지 함께 지정해야 Word 에서 정확히 표시됨.
            try:
                from docx import Document as _Doc
                from docx.oxml.ns import qn
                from docx.oxml import OxmlElement
                TARGET_FONT = '함초롱바탕'

                def _apply_font(run, name):
                    rPr = run._element.get_or_add_rPr()
                    rFonts = rPr.find(qn('w:rFonts'))
                    if rFonts is None:
                        rFonts = OxmlElement('w:rFonts')
                        rPr.insert(0, rFonts)
                    rFonts.set(qn('w:ascii'),    name)
                    rFonts.set(qn('w:hAnsi'),    name)
                    rFonts.set(qn('w:eastAsia'), name)
                    rFonts.set(qn('w:cs'),       name)

                _final = _Doc(BytesIO(buf.getvalue()))
                for p in _final.paragraphs:
                    for r in p.runs:
                        _apply_font(r, TARGET_FONT)
                for table in _final.tables:
                    for row in table.rows:
                        for cell in row.cells:
                            for p in cell.paragraphs:
                                for r in p.runs:
                                    _apply_font(r, TARGET_FONT)
                buf = BytesIO()
                _final.save(buf)
                buf.seek(0)
            except Exception as fe:
                app.logger.warning(f"폰트 적용 실패(무시 가능): {fe}")

            filename = f"발제문_{event.get('book_title','')}_{event.get('meeting_date','')}.docx"
            app.logger.info(f"download_topics_word: 완료, 크기={len(buf.getvalue())} bytes")
            return Response(
                buf.getvalue(),
                mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                headers={"Content-disposition": f"attachment; filename={filename.encode('utf-8').decode('latin1')}"}
            )
        except Exception as e:
            app.logger.error("download_topics_word error: %s", e, exc_info=True)
            flash(SAFE_DOC_ERROR, "danger")
            return redirect(url_for('admin_dashboard'))

    @app.get('/seminars/topics/<event_id>')
    @login_required(role='ANY')
    def member_topic_reader(event_id):
        rows = db().table('topic_events').select('id,seminar_week_id').eq('id', event_id).limit(1).execute().data or []
        if not rows or not rows[0].get('seminar_week_id'):
            abort(404)
        event = rows[0]
        weeks = db().table('seminar_weeks').select('id,term_id,book_title').eq('id', event['seminar_week_id']).limit(1).execute().data or []
        if not weeks:
            abort(404)
        terms = db().table('seminar_terms').select('id,name').eq('id', weeks[0]['term_id']).limit(1).execute().data or []
        if not terms:
            abort(404)
        rows = db().table('topic_submissions').select('topics').eq('event_id', event_id).order('created_at').execute().data or []
        return render_template('member_topics.html', term=terms[0], week=weeks[0], topics=anonymous_topic_previews(rows))

    return SimpleNamespace(
        auto_close_topic_events=_auto_close_topic_events,
        authenticated_topic_member=_authenticated_topic_member,
    )
