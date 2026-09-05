"""Admin-only semester roster drafts, carry-forward and atomic saves."""
import secrets
from flask import abort, jsonify, render_template, request, session
from term_membership import automatic_source_terms, choose_term, validate_entries, STATUSES, ENTRY_TYPES


def init_term_membership_routes(app, get_db, login_required, create_member, create_term):
    def csrf():
        if not session.get('term_members_csrf'):
            session['term_members_csrf'] = secrets.token_urlsafe(32)
        return session['term_members_csrf']

    def check_csrf():
        expected = session.get('term_members_csrf') or ''
        if not expected or not secrets.compare_digest(request.headers.get('X-CSRF-Token', ''), expected):
            abort(403)

    @app.get('/admin/term_members')
    @login_required(role='admin')
    def admin_term_members():
        db = get_db()
        terms = db.table('seminar_terms').select('*').order('start_date', desc=True).execute().data or []
        term = choose_term(terms, request.args.get('term_id'))
        if request.args.get('term_id') and not term:
            abort(404)
        members = db.table('members').select('id,name,student_id,department,gender,is_active,member_status').order('name').execute().data or []
        memberships = []
        while True:
            batch = db.table('seminar_term_members').select('term_id,member_id,status,entry_type').order('term_id').order('member_id').range(len(memberships), len(memberships) + 999).execute().data or []
            memberships.extend(batch)
            if len(batch) < 1000:
                break
        source_terms = automatic_source_terms(terms, term) if term else []
        audit = db.table('seminar_term_roster_changes').select('created_at,revision').eq('term_id', term['id']).order('revision', desc=True).limit(5).execute().data or [] if term else []
        return render_template('admin_term_members.html', terms=terms, term=term, members=members,
                               memberships=memberships, audit=audit, csrf_token=csrf(),
                               statuses=STATUSES, entry_types=ENTRY_TYPES,
                               source_terms=source_terms)

    @app.post('/api/admin/term_members/<term_id>')
    @login_required(role='admin')
    def save_term_members(term_id):
        check_csrf()
        data = request.get_json(silent=True) or {}
        try:
            if type(data.get('revision')) is not int or data['revision'] < 0:
                raise ValueError('명단 버전을 확인할 수 없습니다. 새로고침해주세요.')
            ids = {m['id'] for m in get_db().table('members').select('id').execute().data or []}
            entries = validate_entries(data.get('entries'), ids)
        except (ValueError, TypeError) as exc:
            return jsonify(message=str(exc)), 400
        try:
            result = get_db().rpc('save_seminar_term_members', {
                'p_term_id': term_id, 'p_revision': data['revision'],
                'p_entries': entries, 'p_actor': session['user_id'],
            }).execute().data or {}
        except Exception:
            app.logger.exception('Term roster save failed')
            return jsonify(message='저장 결과를 확인하지 못했습니다. 새로고침 후 명단을 먼저 확인해주세요.'), 503
        if not result.get('accepted'):
            return jsonify(message='다른 운영진의 변경이 있습니다. 새로고침 후 다시 확인해주세요.'), 409
        return jsonify(status='success', revision=result['revision'])

    @app.post('/api/admin/term_members/new_member')
    @login_required(role='admin')
    def create_term_member():
        check_csrf()
        # Reuse the established identity validation. Roles are never editable here.
        data = request.get_json(silent=True) or {}
        if data.get('role', 'member') != 'member':
            abort(400)
        return create_member()

    @app.post('/api/admin/term_members/create_term')
    @login_required(role='admin')
    def create_membership_term():
        check_csrf()
        return create_term()
