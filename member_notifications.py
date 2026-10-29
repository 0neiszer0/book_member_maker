"""Session-owned inbox, preferences and explicit browser push enrollment."""
import base64
import hashlib
import hmac
import os
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit
from flask import abort, jsonify, render_template, request, session, make_response, send_from_directory
from cryptography.hazmat.primitives.asymmetric import ec
from lms_learning import historical_courses
from db_read import all_rows

KST = timezone(timedelta(hours=9))


def subscription_payload(value):
    if not isinstance(value, dict):
        raise ValueError('브라우저 알림 정보를 확인해주세요.')
    endpoint = value.get('endpoint', '')
    if not isinstance(endpoint, str) or len(endpoint) > 2048:
        raise ValueError('알림 주소 형식이 올바르지 않습니다.')
    url = urlsplit(endpoint)
    host = url.hostname or ''
    # Fixed browser push providers only: never let a stored endpoint become an SSRF proxy.
    allowed = (host in {'fcm.googleapis.com', 'updates.push.services.mozilla.com', 'web.push.apple.com'}
               or host.endswith('.push.services.mozilla.com') or host.endswith('.notify.windows.com'))
    if not allowed or url.scheme != 'https' or url.port not in (None, 443) or url.username or url.password or url.fragment:
        raise ValueError('지원하지 않는 브라우저 알림 주소입니다.')
    keys = value.get('keys') or {}
    if not isinstance(keys, dict):
        raise ValueError('알림 암호화 키를 확인해주세요.')
    def decode(key, size):
        text = keys.get(key, '')
        if not isinstance(text, str) or len(text) > 128:
            raise ValueError('알림 암호화 키를 확인해주세요.')
        try:
            result = base64.b64decode(text + '=' * (-len(text) % 4), altchars=b'-_', validate=True)
        except Exception as exc:
            raise ValueError('알림 암호화 키를 확인해주세요.') from exc
        if len(result) != size:
            raise ValueError('알림 암호화 키를 확인해주세요.')
        return result
    public_key = decode('p256dh', 65)
    decode('auth', 16)
    ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), public_key)
    return {'endpoint': endpoint, 'endpoint_hash': hashlib.sha256(endpoint.encode()).hexdigest(),
            'p256dh': keys['p256dh'], 'auth': keys['auth']}


def check_csrf():
    expected = session.get('sensitive_csrf', '')
    actual = request.headers.get('X-App-CSRF') or request.form.get('csrf_token', '')
    if not expected or not actual or not hmac.compare_digest(expected.encode(), actual.encode()):
        abort(403)


def init_member_notifications(app, get_db, login_required):
    def prefs():
        rows = get_db().table('member_preferences').select('hidden_courses').eq('member_id', session['user_id']).limit(1).execute().data or []
        return rows[0] if rows else {'hidden_courses': []}

    @app.get('/notifications')
    @login_required(role='ANY')
    def notification_center():
        return render_template('notifications.html')

    @app.get('/api/member-notifications')
    @login_required(role='ANY')
    def member_notification_list():
        rows = get_db().table('member_inbox').select('id,title,body,url,created_at,read_at,operation_key,operation_term_id').eq('member_id', session['user_id']).is_('resolved_at', 'null').is_('dismissed_at', 'null').order('created_at', desc=True).limit(100).execute().data or []
        from operations import request_operations, request_member, filter_inbox
        if any(r.get('operation_key') or r.get('url') == '/notifications?requests=1' for r in rows):
            ops, member = request_operations(get_db()), request_member(get_db())
            rows = filter_inbox(get_db(), ops, member, rows)
        return jsonify(items=rows, unread=sum(not r.get('read_at') for r in rows))

    @app.post('/api/member-notifications/read-all')
    @login_required(role='ANY')
    def member_notification_read_all():
        check_csrf()
        get_db().table('member_inbox').update({'read_at': datetime.now(timezone.utc).isoformat()}).eq('member_id', session['user_id']).is_('read_at', 'null').execute()
        return jsonify(status='success')

    @app.post('/api/member-notifications/<notification_id>/dismiss')
    @login_required(role='ANY')
    def member_notification_dismiss(notification_id):
        check_csrf()
        get_db().table('member_inbox').update({'dismissed_at': datetime.now(timezone.utc).isoformat()}).eq('id', notification_id).eq('member_id', session['user_id']).execute()
        return jsonify(status='success')

    @app.post('/api/member-notifications/<notification_id>/read')
    @login_required(role='ANY')
    def member_notification_read(notification_id):
        check_csrf()
        get_db().table('member_inbox').update({'read_at': datetime.now(timezone.utc).isoformat()}).eq('id', notification_id).eq('member_id', session['user_id']).execute()
        return jsonify(status='success')

    @app.get('/api/push/config')
    @login_required(role='ANY')
    def push_config():
        key = os.environ.get('WEB_PUSH_PUBLIC_KEY', '')
        owned = get_db().table('push_subscriptions').select('endpoint_hash').eq('member_id', session['user_id']).execute().data or []
        return jsonify(available=bool(key and os.environ.get('WEB_PUSH_PRIVATE_KEY')), public_key=key, subscription_hashes=[r['endpoint_hash'] for r in owned])

    @app.post('/api/push/subscription')
    @login_required(role='ANY')
    def push_subscribe():
        check_csrf()
        if not os.environ.get('WEB_PUSH_PUBLIC_KEY') or not os.environ.get('WEB_PUSH_PRIVATE_KEY'):
            return jsonify(message='브라우저 알림을 준비 중입니다.'), 503
        try:
            payload = subscription_payload(request.get_json(silent=True))
        except (ValueError, TypeError):
            return jsonify(message='지원되는 브라우저에서 알림 권한을 다시 확인해주세요.'), 400
        owned = get_db().table('push_subscriptions').select('endpoint_hash').eq('member_id', session['user_id']).execute().data or []
        if len(owned) >= 10 and payload['endpoint_hash'] not in {r['endpoint_hash'] for r in owned}:
            return jsonify(message='연결된 기기가 10개입니다. 사용하지 않는 기기 알림을 먼저 꺼주세요.'), 409
        payload.update(member_id=session['user_id'], updated_at=datetime.now(timezone.utc).isoformat())
        # One browser subscription belongs to the currently signed-in account only.
        get_db().table('push_subscriptions').upsert(payload, on_conflict='endpoint_hash').execute()
        return jsonify(status='success')

    @app.post('/api/push/unsubscribe')
    @login_required(role='ANY')
    def push_unsubscribe():
        check_csrf()
        endpoint = (request.get_json(silent=True) or {}).get('endpoint')
        if not isinstance(endpoint, str) or len(endpoint) > 2048:
            abort(400)
        get_db().table('push_subscriptions').delete().eq('endpoint_hash', hashlib.sha256(endpoint.encode()).hexdigest()).eq('member_id', session['user_id']).execute()
        return jsonify(status='success')

    @app.get('/manifest.webmanifest')
    def push_manifest():
        return jsonify(name='책 먹는 호반우', short_name='책반우', start_url='/notifications', scope='/', display='standalone', theme_color='#d20f17', background_color='#ffffff')

    @app.get('/push-worker.js')
    def push_service_worker():
        response = make_response(send_from_directory(app.root_path, 'push-worker.js', mimetype='application/javascript'))
        response.headers['Cache-Control'] = 'no-store'
        response.headers['Service-Worker-Allowed'] = '/'
        return response

    def past_courses_for_current_member():
        db = get_db()
        members = all_rows(db.table('members').select('id,name').order('id'))
        histories = all_rows(db.table('history').select('id,date,book_title,present,actual_member_ids,attendance_confirmed_at,seminar_session_id').order('id'))
        terms = db.table('seminar_terms').select('id,name,start_date,end_date').execute().data or []
        sessions = all_rows(db.table('seminar_sessions').select('id,term_id').order('id'))
        return historical_courses(members, histories, terms, session['user_id'], datetime.now(KST).date(), sessions)

    @app.get('/api/my/courses')
    @login_required(role='ANY')
    def my_past_courses():
        courses = past_courses_for_current_member()
        hidden = prefs().get('hidden_courses') or []
        for course in courses:
            course['hidden'] = course['key'] in hidden
            course.pop('records')
        return jsonify(courses=courses)

    @app.get('/my/seminars/archive/<course_key>')
    @login_required(role='ANY')
    def my_seminar_archive(course_key):
        course = next((c for c in past_courses_for_current_member() if c['key'] == course_key), None)
        if not course:
            abort(404)
        return render_template('member_course_archive.html', course=course)

    @app.post('/api/my/courses/visibility')
    @login_required(role='ANY')
    def course_visibility():
        check_csrf()
        data = request.get_json(silent=True) or {}
        key = data.get('key')
        if not isinstance(key, str) or len(key) > 80 or type(data.get('hidden')) is not bool:
            abort(400)
        hidden = set(prefs().get('hidden_courses') or [])
        if data['hidden']:
            hidden.add(key)
        else:
            hidden.discard(key)
        if len(hidden) > 100:
            abort(400)
        get_db().table('member_preferences').upsert({'member_id': session['user_id'], 'hidden_courses': sorted(hidden)}, on_conflict='member_id').execute()
        return jsonify(status='success')
