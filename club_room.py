"""Public room availability; private participant lists and staff-only meetings."""
from datetime import date, datetime, time, timedelta, timezone
import hashlib
import hmac
import re
import secrets
from uuid import UUID

from flask import abort, jsonify, render_template, request, session
from security_utils import forwarded_client_address

KST = timezone(timedelta(hours=9))
PRIVATE_FIELDS = 'id,kind,starts_at,ends_at,representative,participants,purpose,version,cancelled_at'
PUBLIC_FIELDS = 'id,kind,starts_at,ends_at,representative'


def edit_digest(code, secret):
    return hmac.new(str(secret).encode(), ('club-room-edit:v1:' + code).encode(), hashlib.sha256).hexdigest()


def booking_payload(body):
    def text(key, maximum, required=False):
        value = body.get(key, '')
        if not isinstance(value, str) or len(value.strip()) > maximum or (required and not value.strip()):
            raise ValueError('이름과 사용 목적의 입력 길이를 확인해주세요.')
        return value.strip()

    representative = text('representative', 80, True)
    raw = body.get('participants', '')
    if not isinstance(raw, str) or len(raw) > 17000:
        raise ValueError('참여자 이름을 쉼표 또는 줄바꿈으로 구분해주세요.')
    names = list(dict.fromkeys([representative] + [n.strip() for n in re.split(r'[,\n\r]+', raw) if n.strip()]))
    if not raw.strip() or len(names) > 200 or any(len(n) > 80 for n in names):
        raise ValueError('참여자 이름을 확인해주세요. 대표자를 포함해 1명 이상 입력해주세요.')
    values = []
    for key in ('starts_at', 'ends_at'):
        raw_date = body.get(key)
        if not isinstance(raw_date, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:00', raw_date):
            raise ValueError('시작·종료 날짜와 시간을 1시간 단위로 선택해주세요.')
        values.append(datetime.fromisoformat(raw_date).replace(tzinfo=KST))
    if values[1] <= values[0]:
        raise ValueError('종료 시간은 시작 시간보다 뒤여야 합니다.')
    kind = body.get('kind', 'regular')
    if kind not in ('regular', 'meeting'):
        raise ValueError('예약 종류를 확인해주세요.')
    return dict(starts_at=values[0].isoformat(), ends_at=values[1].isoformat(), kind=kind,
                representative=representative, participants=names, purpose=text('purpose', 1000))


def public_booking(row):
    # A meeting's organizer, participants, purpose and identifier stay private.
    if row['kind'] == 'meeting':
        return dict(kind='blocked', starts_at=row['starts_at'], ends_at=row['ends_at'])
    return {key: row[key] for key in ('id', 'kind', 'starts_at', 'ends_at', 'representative')}


def init_club_room_routes(app, get_db, login_required):
    def staff_id():
        if not session.get('user_id'):
            return None
        rows = get_db().table('members').select('id,role,is_active,account_status,member_status') \
            .eq('id', session['user_id']).limit(1).execute().data or []
        member = rows[0] if rows else {}
        if (member.get('role') in ('admin', 'officer') and member.get('is_active') is not False
                and member.get('account_status') == 'active' and member.get('member_status') != 'inactive'):
            return session['user_id']
        return None

    def body_with_csrf():
        if request.content_length and request.content_length > 24000:
            abort(413)
        value = request.headers.get('X-Room-CSRF', '')
        if not session.get('room_csrf') or not hmac.compare_digest(value, session['room_csrf']):
            abort(403)
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            abort(400)
        return body

    def schedule_rows(private=False):
        start = date.fromisoformat(request.args.get('date') or datetime.now(KST).date().isoformat())
        end = start + timedelta(days=7)
        first = datetime.combine(start, time(), KST).isoformat()
        last = datetime.combine(end, time(), KST).isoformat()
        rows = []
        # Page through dense schedules instead of mistaking an API row limit for availability.
        while True:
            batch = get_db().table('club_room_bookings').select(PRIVATE_FIELDS if private else PUBLIC_FIELDS) \
                .is_('cancelled_at', 'null').gte('ends_at', first).lte('starts_at', last) \
                .order('starts_at').order('id').range(len(rows), len(rows) + 999).execute().data or []
            rows.extend(batch)
            if len(batch) < 1000:
                break
        return start, rows

    @app.after_request
    def protect_room_responses(response):
        if request.path == '/club-room' or request.path.startswith('/api/club-room/'):
            response.headers['Cache-Control'] = 'no-store'
            response.headers['Referrer-Policy'] = 'no-referrer'
            response.headers['X-Robots-Tag'] = 'noindex, nofollow'
        return response

    @app.get('/club-room')
    def club_room():
        session.setdefault('room_csrf', secrets.token_urlsafe(32))
        try:
            staff = bool(staff_id()) and not session.get('member_preview')
        except Exception:
            app.logger.exception('Room staff visibility check failed')
            staff = False
        return render_template('club_room.html', room_staff=staff, room_csrf=session['room_csrf'],
                               room_today=datetime.now(KST).date().isoformat())

    @app.get('/api/club-room/schedule')
    def club_room_schedule():
        try:
            start, rows = schedule_rows()
            return jsonify(date=start.isoformat(), bookings=[public_booking(row) for row in rows],
                           now=datetime.now(KST).isoformat())
        except (ValueError, OverflowError):
            return jsonify(error='날짜를 확인해주세요.'), 400
        except Exception:
            app.logger.exception('Room schedule failed')
            return jsonify(error='시간표를 불러오지 못했어요. 빈 시간으로 간주하지 말고 다시 시도해주세요.'), 503

    @app.get('/api/club-room/staff')
    @login_required(role='admin')
    def club_room_staff():
        try:
            start, rows = schedule_rows(private=True)
            return jsonify(date=start.isoformat(), bookings=[{k: r.get(k) for k in PRIVATE_FIELDS.split(',')} for r in rows])
        except (ValueError, OverflowError):
            return jsonify(error='날짜를 확인해주세요.'), 400
        except Exception:
            app.logger.exception('Room management failed')
            return jsonify(error='관리 목록을 불러오지 못했어요.'), 503

    @app.post('/api/club-room/bookings/<booking_id>')
    def club_room_booking(booking_id):
        body = body_with_csrf()
        action = body.get('action')
        if action not in ('create', 'read', 'update', 'cancel'):
            return jsonify(error='예약 작업을 확인해주세요.'), 400
        try:
            booking_id = str(UUID(booking_id))
            code = body.get('edit_code', '')
            if not isinstance(code, str) or (code and not re.fullmatch(r'[A-Za-z0-9_-]{43}', code)):
                raise ValueError('개인 관리 코드를 확인해주세요.')
            actor = staff_id()
            if not code and (action == 'create' or not actor):
                raise ValueError('개인 관리 코드를 확인해주세요.')
            digest = edit_digest(code, app.secret_key) if code else ''
            if action == 'read':
                rows = get_db().table('club_room_bookings').select(PRIVATE_FIELDS + ',edit_digest') \
                    .eq('id', booking_id).limit(1).execute().data or []
                row = rows[0] if rows else None
                if not row or (row['kind'] == 'meeting' and not actor) or (not actor and not hmac.compare_digest(row['edit_digest'], digest)):
                    return jsonify(error='예약 또는 개인 관리 코드를 확인해주세요.'), 403
                return jsonify(status='success', booking={k: row.get(k) for k in PRIVATE_FIELDS.split(',')})
            payload = booking_payload(body) if action in ('create', 'update') else {}
            if payload:
                start = datetime.fromisoformat(payload['starts_at'])
                end = datetime.fromisoformat(payload['ends_at'])
                midnight = datetime.combine(start.date() + timedelta(days=1), time(), KST)
                if start.hour < 9 or end > midnight:
                    return jsonify(error='예약은 오전 9시부터 밤 12시(24:00)까지만 가능해요.'), 400
            if payload.get('kind') == 'meeting' and not actor:
                return jsonify(error='임원진 회의는 로그인한 임원만 등록할 수 있어요.'), 403
            version = body.get('version')
            if action != 'create' and (type(version) is not int or version < 1):
                raise ValueError('예약을 다시 불러온 뒤 수정해주세요.')
            address = forwarded_client_address(request.headers.get('X-Forwarded-For'), request.remote_addr)
            fingerprint = hmac.new(str(app.secret_key).encode(), ('room-rate:' + address).encode(), hashlib.sha256).hexdigest()
            result = get_db().rpc('club_room_mutate', dict(p_action=action, p_id=booking_id,
                p_payload=payload, p_digest=digest, p_actor=actor, p_fingerprint=fingerprint,
                p_ack=body.get('acknowledge_overlap') is True, p_version=version)).execute().data
            status = (result or {}).get('status')
            if status == 'success':
                row = result['booking']
                return jsonify(status=status, booking={k: row.get(k) for k in PRIVATE_FIELDS.split(',')})
            if status == 'overlap':
                return jsonify(status=status, conflicts=[public_booking({**r, 'id': ''}) for r in result['conflicts']],
                               error='겹치는 예약이 있어요. 함께 사용해도 괜찮은지 확인해주세요.'), 409
            messages = {'forbidden': ('예약 또는 권한을 확인해주세요.', 403),
                        'blocked': ('동아리 일정으로 이용할 수 없는 시간이 포함되어 있어요.', 409),
                        'stale': ('다른 곳에서 변경된 예약이에요. 다시 불러온 뒤 수정해주세요.', 409),
                        'cancelled': ('이미 취소된 예약이에요.', 409),
                        'past': ('지난 시간은 새로 예약할 수 없어요. 날짜와 시간을 확인해주세요.', 400),
                        'rate_limited': ('신청이 너무 많아요. 잠시 후 다시 시도해주세요.', 429)}
            message, code = messages.get(status, ('입력한 예약 내용을 확인해주세요.', 400))
            return jsonify(status=status, error=message), code
        except (ValueError, TypeError, OverflowError):
            return jsonify(error='날짜·시간·이름·개인 관리 코드를 확인해주세요.'), 400
        except Exception:
            app.logger.exception('Room booking operation failed')
            return jsonify(error='처리 결과를 확인하지 못했어요. 입력을 유지한 채 다시 시도해주세요.'), 503
