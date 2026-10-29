"""Officer setup and recurring work; global structure is primary-admin only."""
from datetime import date, datetime, timezone
from uuid import UUID
from flask import abort, jsonify, render_template, request, session
from member_notifications import check_csrf
from operations import CAPABILITIES, KST, request_operations, request_member, active, pending_work

def init_operation_routes(app, get_db, login_required):
    def context(term_id=None, edit=False):
        db = get_db()
        ops, member = request_operations(db), request_member(db)
        term = next((t for t in ops.terms if str(t['id']) == str(term_id)), None)
        if term_id and not term:
            abort(404)
        if not active(member):
            abort(403)
        if edit and not ops.can(member, 'tasks', term_id):
            abort(403)
        return db, ops, member, term

    def primary():
        member = request_member(get_db())
        if not active(member) or member.get('role') != 'admin':
            abort(403)

    @app.context_processor
    def operation_navigation():
        def can(capability, term_id=None):
            if not session.get('user_id'):
                return False
            try:
                member = request_member(get_db())
                if not active(member):
                    return False
                if member.get('role') == 'admin':
                    return True
                return request_operations(get_db()).can(member, capability, term_id)
            except Exception:
                app.logger.error('Operation navigation unavailable')
                return False
        return {'operation_can': can}

    @app.get('/operations')
    @login_required()
    def operation_workbench():
        db, ops, member, term = context(request.args.get('term_id'))
        work = pending_work(db, ops, [member], datetime.now(timezone.utc))
        work = [w for w in work if member['id'] in w['recipients'] and (not term or str(w['term_id']) == str(term['id']))]
        if not term and ops.can(member, 'members'):
            from db_read import all_rows
            requests = all_rows(db.table('notifications').select('id').eq('status', 'pending').order('id'))
            if requests:
                work.insert(0, dict(title='가입·계정 신청 '+str(len(requests))+'건', body='신청 내용을 확인하고 처리해주세요.', url='/notifications?requests=1#requests'))
        return render_template('operations.html', work=work, term=term, terms=ops.terms)

    @app.get('/operations/settings')
    @login_required()
    def operation_settings():
        primary()
        db, ops, member, term = context()
        return render_template('operation_roles.html', roles=list(ops.roles.values()), capabilities=CAPABILITIES)

    @app.post('/api/operations/roles')
    @login_required()
    def operation_role_save():
        check_csrf(); primary()
        data = request.get_json(silent=True) or {}
        import re
        if not data.get('id'):
            import secrets
            data['id'] = 'role_'+secrets.token_hex(8)
        if not re.fullmatch('[a-z][a-z0-9_-]{0,39}', str(data.get('id', ''))):
            return jsonify(message='직책 ID는 영문 소문자·숫자·하이픈으로 입력해주세요.'), 400
        if not isinstance(data.get('label'), str) or not 1 <= len(data['label'].strip()) <= 40:
            abort(400)
        caps = data.get('capabilities', [])
        if not isinstance(caps, list) or any(c not in CAPABILITIES for c in caps):
            abort(400)
        get_db().table('operation_roles').upsert({'id': data['id'], 'label': data['label'].strip(),
            'department': str(data.get('department', ''))[:40], 'capabilities': sorted(set(caps)), 'is_active': data.get('is_active') is True}, on_conflict='id').execute()
        get_db().table('operation_audit').insert({'actor_id': session['user_id'], 'action': 'role_update', 'details': {'role_id': data['id'], 'capabilities': caps, 'is_active': data.get('is_active') is True}}).execute()
        return jsonify(status='success')

    @app.get('/operations/terms/<term_id>/officers')
    @login_required()
    def operation_officers(term_id):
        db, ops, member, term = context(term_id)
        if not (ops.can(member, 'members', term_id) or ops.can(member, 'tasks', term_id)):
            abort(403)
        members = db.table('members').select('id,name,student_id,account_status,is_active,member_status').order('name').execute().data or []
        rows = [a for a in ops.assignments if str(a['term_id']) == str(term_id)]
        return render_template('operation_officers.html', term=term, members=[m for m in members if active(m)],
            roles=[r for r in ops.roles.values() if r.get('is_active')], assignments=rows, capabilities=CAPABILITIES,
            can_edit=member.get('role') == 'admin')

    @app.post('/api/operations/terms/<term_id>/officers')
    @login_required()
    def operation_officers_save(term_id):
        check_csrf(); primary()
        db, ops, member, term = context(term_id)
        data = request.get_json(silent=True) or {}
        entries = data.get('entries')
        if not isinstance(entries, list) or len(entries) > 100 or type(data.get('revision')) is not int:
            abort(400)
        seen = set()
        for e in entries:
            if not isinstance(e, dict) or type(e.get('member_id')) is not int or e.get('role_id') not in ops.roles or not ops.roles[e['role_id']].get('is_active'):
                abort(400)
            key = (e['member_id'], e['role_id'])
            if key in seen:
                return jsonify(message='같은 회원의 같은 직책이 중복됐습니다.'), 400
            seen.add(key)
            caps = e.get('capabilities')
            if caps is not None and (not isinstance(caps, list) or any(c not in CAPABILITIES for c in caps)):
                abort(400)
        result = db.rpc('save_term_officers', {'p_term': term_id, 'p_actor': member['id'], 'p_revision': data['revision'], 'p_entries': entries}).execute().data or {}
        return (jsonify(result), 200 if result.get('accepted') else 409)

    @app.get('/operations/terms/<term_id>/rules')
    @login_required()
    def operation_rules(term_id):
        db, ops, member, term = context(term_id, edit=True)
        rules = db.table('operation_rules').select('*').eq('term_id', term_id).order('created_at').execute().data or []
        ids = {a['member_id'] for a in ops.assignments if str(a['term_id']) == str(term_id)}
        members = db.table('members').select('id,name').in_('id', list(ids)).order('name').execute().data or [] if ids else []
        return render_template('operation_rules.html', term=term, rules=rules, members=members,
            roles=[r for r in ops.roles.values() if r.get('is_active')], today=datetime.now(KST).date().isoformat())

    @app.post('/api/operations/terms/<term_id>/rules')
    @login_required()
    def operation_rule_save(term_id):
        check_csrf()
        db, ops, member, term = context(term_id, edit=True)
        data = request.get_json(silent=True) or {}
        if data.get('id'):
            try:
                UUID(str(data['id']))
            except ValueError:
                abort(400)
            existing = db.table('operation_rules').select('*').eq('id', data['id']).eq('term_id', term_id).limit(1).execute().data or []
            if not existing:
                abort(404)
            # Pause is reversible; existing completed records remain.
            db.table('operation_rules').update({'is_active': data.get('is_active') is True}).eq('id', data['id']).eq('term_id', term_id).execute()
            return jsonify(status='success')
        try:
            title, body = str(data.get('title', '')).strip(), str(data.get('body', '')).strip()
            start, end = date.fromisoformat(data['start_date']), date.fromisoformat(data['end_date'])
            today = datetime.now(KST).date()
            if not title or len(title) > 150 or len(body) > 2000 or start < today or end < start or (end-start).days > 740:
                raise ValueError('제목과 오늘 이후의 업무 기간을 확인해주세요.')
            if not term['start_date'] <= start.isoformat() <= end.isoformat() <= term['end_date']:
                raise ValueError('업무 기간은 해당 학기 안으로 설정해주세요.')
            frequency = data['frequency']
            if frequency not in ('once', 'daily', 'weekly', 'monthly'):
                raise ValueError('반복 주기를 선택해주세요.')
            weekday, month_day, hour = int(data.get('weekday', 0)), int(data.get('month_day', 1)), int(data.get('hour', 13))
            if not 0 <= weekday <= 6 or not 1 <= month_day <= 31 or not 0 <= hour <= 23:
                raise ValueError('요일·날짜·시간을 확인해주세요.')
            role_ids, member_ids = data.get('role_ids', []), data.get('member_ids', [])
            if not isinstance(role_ids, list) or not isinstance(member_ids, list) or len(role_ids)+len(member_ids)>100:
                raise ValueError('담당자를 확인해주세요.')
            allowed_ids = {a['member_id'] for a in ops.assignments if str(a['term_id']) == str(term_id)}
            if any(type(i) is not int or i not in allowed_ids for i in member_ids) or any(i not in ops.roles for i in role_ids):
                raise ValueError('해당 학기의 직책·부원만 선택해주세요.')
            rule = dict(term_id=term_id, title=title, body=body, start_date=start.isoformat(), end_date=end.isoformat(),
                frequency=frequency, weekday=weekday, month_day=month_day, hour=hour, role_ids=role_ids, member_ids=member_ids, created_by=member['id'], is_active=True)
            candidates = db.table('members').select('id,is_active,account_status,member_status').in_('id', list(allowed_ids)).execute().data or [] if allowed_ids else []
            if not ops.rule_recipients(rule, candidates):
                raise ValueError('선택한 직책·부원에 현재 담당자가 없습니다. 먼저 임원을 배치해주세요.')
        except (ValueError, KeyError, TypeError) as exc:
            return jsonify(message=str(exc)), 400
        db.table('operation_rules').insert(rule).execute()
        return jsonify(status='success')

    @app.get('/operations/tasks/<task_id>')
    @login_required()
    def operation_task(task_id):
        db, ops, member, _ = context()
        rows = db.table('operation_tasks').select('*').eq('id', task_id).limit(1).execute().data or []
        if not rows:
            abort(404)
        task = rows[0]
        rules = db.table('operation_rules').select('*').eq('id', task['rule_id']).limit(1).execute().data or []
        if not rules or not (member['id'] in ops.rule_recipients(rules[0], [member]) or ops.can(member, 'tasks', task['term_id'])):
            abort(403)
        term = next(t for t in ops.terms if str(t['id']) == str(task['term_id']))
        return render_template('operation_task.html', task=task, term=term, rule_active=rules[0]['is_active'])

    @app.post('/api/operations/tasks/<task_id>/complete')
    @login_required()
    def operation_task_complete(task_id):
        check_csrf()
        result = get_db().rpc('complete_operation_task', {'p_task': task_id, 'p_actor': session['user_id']}).execute().data or {}
        return jsonify(result), 200 if result.get('accepted') else 403
