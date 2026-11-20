"""벽돌책(records)과 소모임(study groups)의 기록/관리 라우트를 별도 모듈로 관리한다.

기존 app.py 에 흩어져 있던 12개 라우트(HTML 4개, JSON API 8개)를 한데 모아
`init_records_activity_routes`로 등록한다. 다른 모듈(attendance_routes, club_room,
wiki_routes 등)과 동일하게 `get_supabase` 콜백을 통해 테스트 패치가 항상 동작하도록
내부에서 `db()` 헬퍼로 Supabase 클라이언트를 얻는다.
"""
from flask import flash, jsonify, redirect, render_template, request, url_for


# JSON API 공통 오류 메시지: 원문 예외(str(e))를 클라이언트에 노출하지 않는다.
SAFE_API_ERROR = '요청을 처리하지 못했습니다. 잠시 후 다시 시도해주세요.'
# HTML 뷰 공통 오류 플래시: 원문 예외를 노출하지 않는다.
SAFE_VIEW_ERROR = '기록을 불러오는 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요.'
# 참여자 ID 형식 오류 메시지.
INVALID_MEMBER_IDS = '참여자 ID 형식이 올바르지 않습니다.'


def init_records_activity_routes(app, get_supabase, login_required, get_term_range, get_terms_for_filter):
    def db():
        return get_supabase()

    # --- 벽돌책 ---
    @app.route('/records/brick_books')
    @login_required(role="admin")
    def records_brick_books():
        term_id = request.args.get('term_id') or ''
        try:
            books = db().table('brick_books').select('*').order('created_at', desc=True).execute().data or []
            start, end, _ = get_term_range(term_id)
            if books:
                ids = [b['id'] for b in books]
                sq = db().table('brick_book_sessions').select('brick_book_id, meeting_date').in_('brick_book_id', ids)
                if start and end:
                    sq = sq.gte('meeting_date', start).lte('meeting_date', end)
                sess_res = sq.execute().data or []
                cnt = {}
                for s in sess_res:
                    cnt[s['brick_book_id']] = cnt.get(s['brick_book_id'], 0) + 1
                for b in books:
                    b['session_count'] = cnt.get(b['id'], 0)
                # 학기 필터링 시: 해당 학기 내 세션이 있는 책만 표시
                if start and end:
                    books = [b for b in books if b['session_count'] > 0]
            terms = get_terms_for_filter()
        except Exception as e:
            app.logger.error("records_brick_books error: %s", e, exc_info=True)
            flash(SAFE_VIEW_ERROR, 'danger')
            books, terms = [], []
        return render_template('records_brick_books.html', books=books,
                               terms=terms, selected_term_id=term_id)

    @app.route('/records/brick_books/<book_id>')
    @login_required(role="admin")
    def records_brick_book_detail(book_id):
        try:
            book = db().table('brick_books').select('*').eq('id', book_id).single().execute().data
            sessions_res = db().table('brick_book_sessions').select('*') \
                .eq('brick_book_id', book_id).order('meeting_date', desc=True).execute()
            sessions = sessions_res.data or []
            sess_ids = [s['id'] for s in sessions]
            member_map_by_sess = {}
            if sess_ids:
                parts = db().table('brick_session_members').select('session_id, member_id, members(id, name)') \
                    .in_('session_id', sess_ids).execute().data or []
                for p in parts:
                    sid = p['session_id']
                    member_map_by_sess.setdefault(sid, []).append(p.get('members') or {})
            for s in sessions:
                s['members'] = member_map_by_sess.get(s['id'], [])
            all_members = db().table('members').select('id, name').eq('is_active', True).order('name').execute().data or []
            return render_template('records_brick_book_detail.html',
                                   book=book, sessions=sessions, all_members=all_members)
        except Exception as e:
            app.logger.error("records_brick_book_detail error: %s", e, exc_info=True)
            flash(SAFE_VIEW_ERROR, 'danger')
            return redirect(url_for('records_brick_books'))

    @app.route('/api/admin/brick_books/create', methods=['POST'])
    @login_required(role="admin")
    def brick_book_create():
        try:
            data = request.json or {}
            title = (data.get('title') or '').strip()
            if not title:
                return jsonify({'status': 'error', 'message': '제목은 필수입니다.'}), 400
            res = db().table('brick_books').insert({
                'title': title,
                'notes': (data.get('notes') or '').strip() or None,
            }).execute()
            return jsonify({'status': 'success', 'book': res.data[0]})
        except Exception as e:
            app.logger.error("brick_book_create error: %s", e, exc_info=True)
            return jsonify({'status': 'error', 'message': SAFE_API_ERROR}), 500

    @app.route('/api/admin/brick_books/<book_id>/delete', methods=['POST'])
    @login_required(role="admin")
    def brick_book_delete(book_id):
        try:
            db().table('brick_books').delete().eq('id', book_id).execute()
            return jsonify({'status': 'success'})
        except Exception as e:
            app.logger.error("brick_book_delete error: %s", e, exc_info=True)
            return jsonify({'status': 'error', 'message': SAFE_API_ERROR}), 500

    @app.route('/api/admin/brick_books/<book_id>/sessions/add', methods=['POST'])
    @login_required(role="admin")
    def brick_session_add(book_id):
        try:
            data = request.json or {}
            meeting_date = data.get('meeting_date')
            if not meeting_date:
                return jsonify({'status': 'error', 'message': '날짜가 필요합니다.'}), 400
            try:
                member_ids = [int(m) for m in (data.get('member_ids') or []) if m]
            except (TypeError, ValueError):
                return jsonify({'status': 'error', 'message': INVALID_MEMBER_IDS}), 400
            sess = db().table('brick_book_sessions').insert({
                'brick_book_id': book_id,
                'meeting_date': meeting_date,
                'notes': (data.get('notes') or '').strip() or None,
            }).execute().data[0]
            if member_ids:
                db().table('brick_session_members').insert([
                    {'session_id': sess['id'], 'member_id': mid} for mid in member_ids
                ]).execute()
            return jsonify({'status': 'success', 'session': sess})
        except Exception as e:
            app.logger.error("brick_session_add error: %s", e, exc_info=True)
            return jsonify({'status': 'error', 'message': SAFE_API_ERROR}), 500

    @app.route('/api/admin/brick_sessions/<session_id>/delete', methods=['POST'])
    @login_required(role="admin")
    def brick_session_delete(session_id):
        try:
            db().table('brick_book_sessions').delete().eq('id', session_id).execute()
            return jsonify({'status': 'success'})
        except Exception as e:
            app.logger.error("brick_session_delete error: %s", e, exc_info=True)
            return jsonify({'status': 'error', 'message': SAFE_API_ERROR}), 500

    # --- 소모임 ---
    @app.route('/records/study_groups')
    @login_required(role="admin")
    def records_study_groups():
        term_id = request.args.get('term_id') or ''
        try:
            groups = db().table('study_groups').select('*').order('created_at', desc=True).execute().data or []
            start, end, _ = get_term_range(term_id)
            if groups:
                ids = [g['id'] for g in groups]
                sq = db().table('study_group_sessions').select('study_group_id, meeting_date').in_('study_group_id', ids)
                if start and end:
                    sq = sq.gte('meeting_date', start).lte('meeting_date', end)
                sess_res = sq.execute().data or []
                cnt = {}
                for s in sess_res:
                    cnt[s['study_group_id']] = cnt.get(s['study_group_id'], 0) + 1
                for g in groups:
                    g['session_count'] = cnt.get(g['id'], 0)
                if start and end:
                    groups = [g for g in groups if g['session_count'] > 0]
            terms = get_terms_for_filter()
        except Exception as e:
            app.logger.error("records_study_groups error: %s", e, exc_info=True)
            flash(SAFE_VIEW_ERROR, 'danger')
            groups, terms = [], []
        return render_template('records_study_groups.html', groups=groups,
                               terms=terms, selected_term_id=term_id)

    @app.route('/records/study_groups/<group_id>')
    @login_required(role="admin")
    def records_study_group_detail(group_id):
        try:
            group = db().table('study_groups').select('*').eq('id', group_id).single().execute().data
            sessions_res = db().table('study_group_sessions').select('*') \
                .eq('study_group_id', group_id).order('meeting_date', desc=True).execute()
            sessions = sessions_res.data or []
            sess_ids = [s['id'] for s in sessions]
            member_map_by_sess = {}
            if sess_ids:
                parts = db().table('study_session_members').select('session_id, member_id, members(id, name)') \
                    .in_('session_id', sess_ids).execute().data or []
                for p in parts:
                    sid = p['session_id']
                    member_map_by_sess.setdefault(sid, []).append(p.get('members') or {})
            for s in sessions:
                s['members'] = member_map_by_sess.get(s['id'], [])
            all_members = db().table('members').select('id, name').eq('is_active', True).order('name').execute().data or []
            return render_template('records_study_group_detail.html',
                                   group=group, sessions=sessions, all_members=all_members)
        except Exception as e:
            app.logger.error("records_study_group_detail error: %s", e, exc_info=True)
            flash(SAFE_VIEW_ERROR, 'danger')
            return redirect(url_for('records_study_groups'))

    @app.route('/api/admin/study_groups/create', methods=['POST'])
    @login_required(role="admin")
    def study_group_create():
        try:
            data = request.json or {}
            name = (data.get('name') or '').strip()
            if not name:
                return jsonify({'status': 'error', 'message': '이름은 필수입니다.'}), 400
            res = db().table('study_groups').insert({
                'name': name,
                'notes': (data.get('notes') or '').strip() or None,
            }).execute()
            return jsonify({'status': 'success', 'group': res.data[0]})
        except Exception as e:
            app.logger.error("study_group_create error: %s", e, exc_info=True)
            return jsonify({'status': 'error', 'message': SAFE_API_ERROR}), 500

    @app.route('/api/admin/study_groups/<group_id>/delete', methods=['POST'])
    @login_required(role="admin")
    def study_group_delete(group_id):
        try:
            db().table('study_groups').delete().eq('id', group_id).execute()
            return jsonify({'status': 'success'})
        except Exception as e:
            app.logger.error("study_group_delete error: %s", e, exc_info=True)
            return jsonify({'status': 'error', 'message': SAFE_API_ERROR}), 500

    @app.route('/api/admin/study_groups/<group_id>/sessions/add', methods=['POST'])
    @login_required(role="admin")
    def study_session_add(group_id):
        try:
            data = request.json or {}
            meeting_date = data.get('meeting_date')
            if not meeting_date:
                return jsonify({'status': 'error', 'message': '날짜가 필요합니다.'}), 400
            try:
                member_ids = [int(m) for m in (data.get('member_ids') or []) if m]
            except (TypeError, ValueError):
                return jsonify({'status': 'error', 'message': INVALID_MEMBER_IDS}), 400
            sess = db().table('study_group_sessions').insert({
                'study_group_id': group_id,
                'meeting_date': meeting_date,
                'notes': (data.get('notes') or '').strip() or None,
            }).execute().data[0]
            if member_ids:
                db().table('study_session_members').insert([
                    {'session_id': sess['id'], 'member_id': mid} for mid in member_ids
                ]).execute()
            return jsonify({'status': 'success', 'session': sess})
        except Exception as e:
            app.logger.error("study_session_add error: %s", e, exc_info=True)
            return jsonify({'status': 'error', 'message': SAFE_API_ERROR}), 500

    @app.route('/api/admin/study_sessions/<session_id>/delete', methods=['POST'])
    @login_required(role="admin")
    def study_session_delete(session_id):
        try:
            db().table('study_group_sessions').delete().eq('id', session_id).execute()
            return jsonify({'status': 'success'})
        except Exception as e:
            app.logger.error("study_session_delete error: %s", e, exc_info=True)
            return jsonify({'status': 'error', 'message': SAFE_API_ERROR}), 500
