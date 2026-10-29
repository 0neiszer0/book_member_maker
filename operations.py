"""Semester-scoped responsibilities and shared work, independent of global roles."""
from datetime import datetime, timedelta, timezone, date
from calendar import monthrange
from flask import g, request, session
from db_read import all_rows

KST = timezone(timedelta(hours=9))
CAPABILITIES = {'members': '회원 관리·신청 처리', 'attendance': '실제 출석 확정', 'tasks': '업무·반복 알림 관리'}

def active(member):
    return bool(member.get('is_active') and member.get('account_status') == 'active'
                and member.get('member_status') not in ('inactive', 'blocked'))

class Operations:
    def __init__(self, db):
        self.db = db
        self.terms = db.table('seminar_terms').select('*').order('start_date').execute().data or []
        self.roles = {r['id']: r for r in db.table('operation_roles').select('*').execute().data or []}
        self.assignments = all_rows(db.table('term_officers').select('*').order('id'))

    def assigned(self, member_id, term_id):
        return [a for a in self.assignments if str(a['member_id']) == str(member_id) and str(a['term_id']) == str(term_id)
                and self.roles.get(a['role_id'], {}).get('is_active', True)]

    def can(self, member, capability, term_id=None, today=None):
        if not active(member):
            return False
        if member.get('role') == 'admin':
            return True
        today = (today or datetime.now(KST).date()).isoformat()
        terms = [t for t in self.terms if str(t['id']) == str(term_id)] if term_id else [t for t in self.terms if t['start_date'] <= today <= t['end_date']]
        for term in terms:
            if not term.get('operations_initialized_at') and member.get('role') == 'officer':
                return True  # Existing staff keep access until this term is explicitly configured.
            for assignment in self.assigned(member['id'], term['id']):
                caps = assignment.get('capabilities')
                if capability in (caps if caps is not None else self.roles[assignment['role_id']].get('capabilities', [])):
                    return True
        return False

    def recipients(self, members, capability, term_id=None, today=None):
        today = (today or datetime.now(KST).date()).isoformat()
        terms = [t for t in self.terms if str(t['id']) == str(term_id)] if term_id else [t for t in self.terms if t['start_date'] <= today <= t['end_date']]
        assigned = []
        for m in members:
            if not active(m):
                continue
            for t in terms:
                selected = any(capability in (a['capabilities'] if a.get('capabilities') is not None else self.roles[a['role_id']].get('capabilities', []))
                               for a in self.assigned(m['id'], t['id']))
                if selected or (not t.get('operations_initialized_at') and m.get('role') == 'officer'):
                    assigned.append(m['id']); break
        # Global admin is a fallback, not a duplicate recipient for every work item.
        return assigned or [m['id'] for m in members if m.get('role') == 'admin' and active(m)]

    def rule_recipients(self, rule, members):
        roles = set(rule.get('role_ids') or [])
        chosen = set(rule.get('member_ids') or [])
        return [m['id'] for m in members if active(m) and self.assigned(m['id'], rule['term_id'])
                and (m['id'] in chosen or any(a['role_id'] in roles for a in self.assigned(m['id'], rule['term_id'])))]

def request_operations(db):
    if not hasattr(g, 'operation_context'):
        g.operation_context = Operations(db)
    return g.operation_context

def request_member(db):
    if not hasattr(g, 'operation_member'):
        rows = db.table('members').select('id,role,is_active,account_status,member_status').eq('id', session.get('user_id')).limit(1).execute().data or []
        g.operation_member = rows[0] if rows else {}
    return g.operation_member

# Explicit allowlist. Query/form input never grants arbitrary admin access.
SCOPED_ENDPOINTS = {
    'admin_term_members': 'members', 'save_term_members': 'members',
    'admin_seminar_roster': 'attendance', 'seminar_roster_preview': 'attendance',
    'seminar_roster_apply': 'attendance', 'seminar_roster_undo': 'attendance',
    'seminar_attendance_confirm': 'attendance', 'admin_term_attendance': 'attendance',
    'term_attendance_export': 'attendance', 'attendance_bulk_preview': 'attendance',
    'attendance_bulk_confirm': 'attendance', 'get_notifications': 'members', 'handle_notification': 'members',
}

def scoped_endpoint_allowed(db, endpoint, arguments):
    capability = SCOPED_ENDPOINTS.get(endpoint)
    if not capability:
        return None
    ops = request_operations(db)
    term_id = arguments.get('term_id') or request.args.get('term_id')
    if arguments.get('session_id'):
        rows = db.table('seminar_sessions').select('term_id').eq('id', arguments['session_id']).limit(1).execute().data or []
        if not rows:
            return False
        term_id = rows[0]['term_id']
    if not term_id and endpoint not in ('get_notifications', 'handle_notification'):
        # Same current/active fallback used by the existing page, before rendering.
        from term_membership import choose_term
        term = choose_term(sorted(ops.terms, key=lambda t: t['start_date'], reverse=True), None)
        term_id = term['id'] if term else None
        if not term_id:
            return False
    return ops.can(request_member(db), capability, term_id)

def occurrence_dates(rule, today):
    """Bounded calendar recurrence, inclusive dates and stable monthly end-day."""
    start = date.fromisoformat(rule['start_date'])
    end = min(today, date.fromisoformat(rule['end_date']))
    if (end - start).days > 740:
        raise ValueError('업무 기간은 2년 이내로 설정해주세요.')
    day = start
    while day <= end:
        frequency = rule['frequency']
        if (frequency == 'once' and day == start or frequency == 'daily'
                or frequency == 'weekly' and day.weekday() == rule['weekday']
                or frequency == 'monthly' and day.day == min(rule['month_day'], monthrange(day.year, day.month)[1])):
            yield day
        day += timedelta(days=1)

def sync_custom_tasks(db, ops, now):
    today = now.astimezone(KST).date()
    rules = db.table('operation_rules').select('*').eq('is_active', True).execute().data or []
    existing = {(str(t['rule_id']), t['occurrence_date']) for t in all_rows(
        db.table('operation_tasks').select('id,rule_id,occurrence_date').order('id'))} if rules else set()
    for rule in rules:
        term = next((t for t in ops.terms if str(t['id']) == str(rule['term_id'])), None)
        if not term:
            continue
        for day in occurrence_dates(rule, min(today, date.fromisoformat(term['end_date']))):
            if (str(rule['id']), day.isoformat()) in existing:
                continue
            due = datetime.combine(day, datetime.min.time(), KST).replace(hour=rule.get('hour', 13))
            if due > now:
                continue
            db.table('operation_tasks').upsert({'rule_id': rule['id'], 'occurrence_date': day.isoformat(),
                'term_id': rule['term_id'], 'title': rule['title'], 'body': rule['body'], 'due_at': due.isoformat()},
                on_conflict='rule_id,occurrence_date', ignore_duplicates=True).execute()
    return rules

def pending_work(db, ops, members, now, rules=None):
    from lms_learning import is_break_week, link_legacy_histories
    from attendance_workflow import confirmed_history_session_ids, attendance_is_confirmed
    today = now.astimezone(KST).date()
    result = []
    def add(key, term_id, title, body, url, recipients):
        if recipients:
            result.append(dict(key=key, term_id=term_id, title=title, body=body, url=url, recipients=recipients))
    for term in ops.terms:
        if term['start_date'] <= today.isoformat() <= term['end_date'] and not term.get('roster_initialized_at'):
            add('roster:'+str(term['id']), term['id'], term['name']+' 회원 명단 확정', '활동 회원을 확인하고 명단을 확정해주세요.',
                '/admin/term_members?term_id='+str(term['id']), ops.recipients(members, 'members', term['id'], today))
    sessions = all_rows(db.table('seminar_sessions').select('*').lte('meeting_date', today.isoformat()).order('id'))
    weeks = {str(w['id']): w for w in all_rows(db.table('seminar_weeks').select('id,note,book_title').order('id'))}
    histories = all_rows(db.table('history').select('id,date,book_title,seminar_session_id,attendance_confirmed_at').order('id'))
    confirmed = confirmed_history_session_ids(link_legacy_histories(histories, sessions))
    for meeting in sessions:
        if not meeting.get('is_active', True) or is_break_week(weeks.get(str(meeting.get('seminar_week_id')), {})) or attendance_is_confirmed(meeting, confirmed):
            continue
        # A date-only meeting is ready for a reminder the following day.
        if meeting['meeting_date'] >= today.isoformat():
            continue
        add('attendance:'+str(meeting['id']), meeting['term_id'], meeting['meeting_date']+' 출석 확정', '예정 명단을 확인하고 실제 출석을 확정해주세요.',
            '/admin/seminar_sessions/'+str(meeting['id'])+'/roster#actual-attendance', ops.recipients(members, 'attendance', meeting['term_id'], today))
    rules = rules if rules is not None else db.table('operation_rules').select('*').eq('is_active', True).execute().data or []
    rule_map = {str(r['id']): r for r in rules}
    tasks = all_rows(db.table('operation_tasks').select('*').is_('completed_at', 'null').order('id'))
    for task in tasks:
        rule = rule_map.get(str(task['rule_id']))
        if rule:
            add('custom:'+str(task['id']), task['term_id'], task['title'], task['body'], '/operations/tasks/'+str(task['id']), ops.rule_recipients(rule, members))
    return result


def filter_inbox(db, ops, member, rows):
    """Recheck assignment revocation and completion without trusting old inbox text."""
    rules = None
    tasks = None
    def allowed(item):
        nonlocal rules, tasks
        key = item.get('operation_key') or ''
        if item.get('url') == '/notifications?requests=1':
            return ops.can(member, 'members')
        if key.startswith(('attendance:', 'roster:')):
            return ops.can(member, 'attendance' if key.startswith('attendance:') else 'members', item.get('operation_term_id'))
        if key.startswith('custom:'):
            if rules is None:
                rules = {str(r['id']): r for r in db.table('operation_rules').select('*').eq('is_active', True).execute().data or []}
                tasks = {str(t['id']): t for t in all_rows(db.table('operation_tasks').select('*').is_('completed_at', 'null').order('id'))}
            task = tasks.get(key.split(':',1)[1])
            rule = rules.get(str(task['rule_id'])) if task else None
            return bool(rule and member['id'] in ops.rule_recipients(rule, [member]))
        if key == 'digest':
            return member.get('role') == 'admin' or any(ops.assigned(member.get('id'), t['id']) for t in ops.terms)
        return True
    return [r for r in rows if allowed(r)]
