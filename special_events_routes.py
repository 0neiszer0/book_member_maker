"""스페셜 이벤트(MT·워크숍·강연 등 1회성 행사)의 관리 라우트를 별도 모듈로 관리한다.

기존 app.py 에 있던 8개 라우트(HTML 2개, JSON API 6개)를 한데 모아
`init_special_events_routes`로 등록한다. 다른 모듈(records_activity_routes 등)과
동일하게 `get_supabase` 콜백을 통해 테스트 패치가 항상 동작하도록 내부에서
`db()` 헬퍼로 Supabase 클라이언트를 얻는다.

예외는 로그에만 남기고 클라이언트에는 원문 예외(str(e))를 절대 노출하지 않는다.
"""
from flask import flash, jsonify, redirect, render_template, request, session, url_for


# JSON API 공통 오류 메시지: 원문 예외(str(e))를 클라이언트에 노출하지 않는다.
SAFE_API_ERROR = '요청을 처리하지 못했습니다. 잠시 후 다시 시도해주세요.'
# HTML 뷰 공통 오류 플래시: 원문 예외를 노출하지 않는다.
SAFE_VIEW_ERROR = '행사 정보를 불러오는 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요.'


def init_special_events_routes(app, get_supabase, login_required, get_terms_for_filter):
    def db():
        return get_supabase()

    @app.route('/admin/special_events')
    @login_required(role="admin")
    def admin_special_events():
        """관리자: 스페셜 이벤트 목록 + 생성/관리 페이지"""
        try:
            events = db().table('special_events').select('*') \
                .order('event_date', desc=True).execute().data or []
            event_ids = [evt['id'] for evt in events]
            attendee_counts = {}
            if event_ids:
                attendee_rows = db().table('special_event_attendees') \
                    .select('event_id').in_('event_id', event_ids).execute().data or []
                for attendee in attendee_rows:
                    event_id = attendee.get('event_id')
                    attendee_counts[event_id] = attendee_counts.get(event_id, 0) + 1
            for evt in events:
                evt['attendee_count'] = attendee_counts.get(evt['id'], 0)
            terms = get_terms_for_filter()
            return render_template('admin_special_events.html', events=events, terms=terms)
        except Exception as e:
            app.logger.error("admin_special_events error: %s", e, exc_info=True)
            flash(SAFE_VIEW_ERROR, "danger")
            return redirect(url_for('admin_dashboard'))

    @app.route('/admin/special_events/<event_id>')
    @login_required(role="admin")
    def admin_special_event_detail(event_id):
        """관리자: 단일 이벤트 상세 + 참석자 관리"""
        try:
            evt = db().table('special_events').select('*').eq('id', event_id).single().execute().data
            if not evt:
                flash("이벤트를 찾을 수 없습니다.", "danger")
                return redirect(url_for('admin_special_events'))
            attendees = db().table('special_event_attendees') \
                .select('id, member_id, role, note, members(id, name, student_id, department)') \
                .eq('event_id', event_id).order('created_at').execute().data or []
            # Actual event attendance can include returning or previously dormant members.
            all_members = db().table('members').select('id, name, student_id, department').order('name').execute().data or []
            attendee_ids = {a['member_id'] for a in attendees}
            candidates = [m for m in all_members if m['id'] not in attendee_ids]
            return render_template('admin_special_event_detail.html',
                                   event=evt, attendees=attendees, candidates=candidates)
        except Exception as e:
            app.logger.error("admin_special_event_detail error: %s", e, exc_info=True)
            flash(SAFE_VIEW_ERROR, "danger")
            return redirect(url_for('admin_special_events'))

    @app.route('/api/admin/special_events/create', methods=['POST'])
    @login_required(role="admin")
    def create_special_event():
        try:
            data = request.json or {}
            name = (data.get('name') or '').strip()
            event_date = data.get('event_date')
            if not name or not event_date:
                return jsonify({'error': '이름과 날짜는 필수입니다.'}), 400
            payload = {
                'name': name,
                'description': (data.get('description') or '').strip() or None,
                'event_date': event_date,
                'end_date': data.get('end_date') or None,
                'category': (data.get('category') or 'event'),
                'term_id': data.get('term_id') or None,
                'created_by': session.get('user_id'),
            }
            res = db().table('special_events').insert(payload).execute()
            return jsonify({'status': 'success', 'event': res.data[0]})
        except Exception as e:
            app.logger.error("create_special_event error: %s", e, exc_info=True)
            return jsonify({'error': SAFE_API_ERROR}), 500

    @app.route('/api/admin/special_events/<event_id>/update', methods=['POST'])
    @login_required(role="admin")
    def update_special_event(event_id):
        try:
            data = request.json or {}
            update = {}
            for k in ('name', 'description', 'event_date', 'end_date', 'category', 'term_id'):
                if k in data:
                    update[k] = data[k] if data[k] != '' else None
            if 'is_active' in data:
                update['is_active'] = bool(data['is_active'])
            if not update:
                return jsonify({'error': '수정할 내용이 없습니다.'}), 400
            db().table('special_events').update(update).eq('id', event_id).execute()
            return jsonify({'status': 'success'})
        except Exception as e:
            app.logger.error("update_special_event error: %s", e, exc_info=True)
            return jsonify({'error': SAFE_API_ERROR}), 500

    @app.route('/api/admin/special_events/<event_id>/toggle_active', methods=['POST'])
    @login_required(role="admin")
    def toggle_special_event(event_id):
        try:
            cur = db().table('special_events').select('is_active').eq('id', event_id).single().execute().data
            if not cur:
                return jsonify({'error': '이벤트를 찾을 수 없습니다.'}), 404
            new_state = not bool(cur.get('is_active'))
            db().table('special_events').update({'is_active': new_state}).eq('id', event_id).execute()
            return jsonify({'status': 'success', 'is_active': new_state})
        except Exception as e:
            app.logger.error("toggle_special_event error: %s", e, exc_info=True)
            return jsonify({'error': SAFE_API_ERROR}), 500

    @app.route('/api/admin/special_events/<event_id>/delete', methods=['POST'])
    @login_required(role="admin")
    def delete_special_event(event_id):
        try:
            # cascade로 참석자도 함께 삭제됨
            db().table('special_events').delete().eq('id', event_id).execute()
            return jsonify({'status': 'success'})
        except Exception as e:
            app.logger.error("delete_special_event error: %s", e, exc_info=True)
            return jsonify({'error': SAFE_API_ERROR}), 500

    @app.route('/api/admin/special_events/<event_id>/attendees/add', methods=['POST'])
    @login_required(role="admin")
    def add_special_event_attendee(event_id):
        try:
            data = request.json or {}
            member_ids = data.get('member_ids') or []
            if isinstance(member_ids, (int, str)):
                member_ids = [member_ids]
            if not member_ids:
                return jsonify({'error': '추가할 회원을 선택하세요.'}), 400
            rows = [{'event_id': event_id, 'member_id': int(mid),
                     'role': data.get('role', 'attendee'),
                     'note': (data.get('note') or '').strip() or None}
                    for mid in member_ids]
            # ON CONFLICT DO NOTHING 동작 — 이미 등록된 멤버는 스킵
            db().table('special_event_attendees').upsert(rows, on_conflict='event_id,member_id').execute()
            return jsonify({'status': 'success', 'added': len(rows)})
        except Exception as e:
            app.logger.error("add_special_event_attendee error: %s", e, exc_info=True)
            return jsonify({'error': SAFE_API_ERROR}), 500

    @app.route('/api/admin/special_events/<event_id>/attendees/<int:member_id>/remove', methods=['POST'])
    @login_required(role="admin")
    def remove_special_event_attendee(event_id, member_id):
        try:
            db().table('special_event_attendees').delete() \
                .eq('event_id', event_id).eq('member_id', member_id).execute()
            return jsonify({'status': 'success'})
        except Exception as e:
            app.logger.error("remove_special_event_attendee error: %s", e, exc_info=True)
            return jsonify({'error': SAFE_API_ERROR}), 500
