"""Periodic inbox reconciliation and bounded Web Push delivery, outside web requests.

Run under the supplied systemd unit (flock prevents concurrent senders).
Never log subscription endpoints, key material or member details.
"""
import json
import os
import requests
from db_read import all_rows
from datetime import datetime, timedelta, timezone
from home_overview import load_seminar_context
from topic_lifecycle import topic_event_is_open
from term_membership import scope_members
from engagement_utils import form_is_open
from collections import Counter
from backup_health import backup_notice
from member_notifications import subscription_payload
from operations import Operations, KST, pending_work, sync_custom_tasks, filter_inbox


class NoRedirectSession(requests.Session):
    def request(self, method, url, **kwargs):
        kwargs['allow_redirects'] = False
        response = super().request(method, url, **kwargs)
        if 300 <= response.status_code < 400:
            raise ValueError('Push provider redirect rejected')
        return response


def collect_items(db, now):
    members = all_rows(db.table('members').select('id,name,student_id,role,is_active,account_status,member_status').order('id'))
    identities = members
    members = [m for m in members if m.get('is_active') and m.get('account_status') == 'active' and m.get('member_status') not in ('inactive', 'blocked')]
    ops = Operations(db)
    staff_ids = set(ops.recipients(members, 'members', today=now.astimezone(KST).date()))
    staff = [m for m in members if m['id'] in staff_ids]
    active = {int(m['id']) for m in members}
    items = []
    def add(mid, key, title, body, url):
        items.append({'member_id': mid, 'event_key': key, 'title': title, 'body': body, 'url': url})
    pending = all_rows(db.table('notifications').select('id,type,status,related_member_id,created_at').eq('status', 'pending').order('id'))
    recent = all_rows(db.table('notifications').select('id,type,status,related_member_id,created_at').gte('created_at', (now-timedelta(days=14)).isoformat()).order('id'))
    labels = {'new_user_request': '새 가입 신청', 'account_link_request': '계정 연결 신청', 'absence_request': '불참 신청'}
    for row in pending:
        for m in staff:
            add(m['id'], f"request:{row['id']}", labels.get(row['type'], '새 신청'), '신청 내용을 확인하고 처리해주세요.', '/notifications?requests=1')
    rules = sync_custom_tasks(db, ops, now)
    work = pending_work(db, ops, members, now, rules)
    totals = Counter({m['id']: len(pending) for m in staff if pending})
    for task in work:
        for mid in task['recipients']:
            items.append({'member_id': mid, 'event_key': 'work:'+task['key'], 'operation_key': task['key'],
                'operation_term_id': task['term_id'], 'title': task['title'], 'body': task['body'], 'url': task['url']})
            totals[mid] += 1
    local = now.astimezone(KST)
    if local.hour >= 13:
        for mid, count in totals.items():
            items.append({'member_id': mid, 'event_key': 'work-digest:'+local.date().isoformat(),
                'operation_key': 'digest', 'title': '오늘 확인할 운영 업무', 'body': f'처리를 기다리는 업무 {count}개가 있습니다.', 'url': '/operations'})
    for row in recent:
        if row.get('status') in ('approved', 'denied') and row.get('related_member_id') in active:
            add(row['related_member_id'], f"decision:{row['id']}:{row['status']}", '신청 처리 결과',
                '신청이 승인되었습니다.' if row['status']=='approved' else '신청이 반려되었습니다. 운영진에게 문의해주세요.', '/mypage')
    today = now.astimezone(timezone(timedelta(hours=9))).date()
    context = load_seminar_context(db, today=today)
    events = [e for e in context['topics'].values() if topic_event_is_open(e, today=today)]
    ids = [e['id'] for e in events]
    submissions = all_rows(db.table('topic_submissions').select('event_id,member_id,student_id').in_('event_id', ids).order('id')) if ids else []
    owned = {(str(s['event_id']), str(s['member_id'])) for s in submissions if s.get('member_id') is not None}
    legacy = {(str(s['event_id']), str(s.get('student_id') or '').strip()) for s in submissions if s.get('member_id') is None}
    for m in scope_members(db, members, term=context['term']):
        if not m.get('is_active'):
            continue
        for event in events:
            if ((str(event['id']), str(m['id'])) in owned or
                (m.get('student_id') and (str(event['id']), str(m['student_id']).strip()) in legacy)):
                continue
            title = context['weeks'].get(event['seminar_week_id'], {}).get('book_title') or '세미나'
            add(m['id'], f"topic:{event['id']}", f'{title} 발제문 작성',
                '접수 중인 발제문을 작성해주세요.', f"/seminars?term_id={context['term']['id']}&section=topics#topic-{event['seminar_week_id']}")
    # Review reminders go only to confirmed participants, not everyone in the club.
    forms = [f for f in all_rows(db.table('seminar_review_forms').select('id,seminar_session_id,share_token,status,open_at,close_at').eq('status', 'open').order('id')) if form_is_open(f, now)]
    if forms:
        session_ids = [f['seminar_session_id'] for f in forms]
        meetings = all_rows(db.table('seminar_sessions').select('id,book_title,actual_member_ids,attendance_confirmed_at').in_('id', session_ids).order('id'))
        histories = all_rows(db.table('history').select('id,seminar_session_id,present,actual_member_ids,attendance_confirmed_at').in_('seminar_session_id', session_ids).order('id'))
        reviewed = {(r['form_id'], r['member_id']) for r in all_rows(db.table('seminar_reviews').select('id,form_id,member_id').in_('form_id', [f['id'] for f in forms]).is_('deleted_at', 'null').order('id'))}
        no_shows = {(r['session_id'], r['member_id']) for r in all_rows(db.table('seminar_no_shows').select('id,session_id,member_id').in_('session_id', session_ids).is_('cancelled_at', 'null').order('id'))}
        names = Counter(m.get('name') for m in identities)
        for form in forms:
            meeting = next((m for m in meetings if m['id'] == form['seminar_session_id']), {})
            confirmed = set(meeting.get('actual_member_ids') or []) if meeting.get('attendance_confirmed_at') and meeting.get('actual_member_ids') is not None else set()
            if not (meeting.get('attendance_confirmed_at') and meeting.get('actual_member_ids') is not None):
                for h in histories:
                    if h.get('seminar_session_id') != form['seminar_session_id'] or not h.get('attendance_confirmed_at'):
                        continue
                    if h.get('actual_member_ids') is not None:
                        confirmed.update(h['actual_member_ids'])
                    else:
                        confirmed.update(m['id'] for m in members if names[m.get('name')] == 1 and m.get('name') in (h.get('present') or []))
            for mid in confirmed & active:
                if (form['id'], mid) not in reviewed and (form['seminar_session_id'], mid) not in no_shows:
                    add(mid, f"review:{form['id']}", f"{meeting.get('book_title') or '세미나'} 후기", '참여한 세미나의 후기를 남겨주세요.', f"/review/seminar/{form['share_token']}")
    backup = backup_notice(now)
    if backup:
        items.extend({'member_id':m['id'], **backup} for m in members if m.get('role') == 'admin')
    return items, members


def reconcile(db, items, now):
    existing = all_rows(db.table('member_inbox').select('id,member_id,event_key,resolved_at').order('id'))
    indexed = {(r['member_id'], r['event_key']): r for r in existing}
    desired = {(r['member_id'], r['event_key']) for r in items}
    for item in items:
        row = indexed.get((item['member_id'], item['event_key']))
        if row is None:
            db.table('member_inbox').upsert(item, on_conflict='member_id,event_key', ignore_duplicates=True).execute()
        elif row.get('resolved_at'):
            db.table('member_inbox').update({'resolved_at': None}).eq('id', row['id']).execute()
    stale = [r['id'] for key, r in indexed.items() if key not in desired and not r.get('resolved_at')]
    for offset in range(0, len(stale), 100):
        db.table('member_inbox').update({'resolved_at': now.isoformat()}).in_('id', stale[offset:offset+100]).execute()


def deliver(db, members, now, send=None):
    if not os.environ.get('WEB_PUSH_PRIVATE_KEY'):
        return {'sent': 0, 'failed': 0}
    if send is None:
        from pywebpush import webpush
        send = webpush
    inbox = all_rows(db.table('member_inbox').select('*').is_('resolved_at', 'null').is_('dismissed_at', 'null').is_('read_at', 'null').order('created_at', desc=True).order('id'))
    subscriptions = all_rows(db.table('push_subscriptions').select('*').order('endpoint_hash'))
    deliveries = all_rows(db.table('push_deliveries').select('*').order('notification_id').order('endpoint_hash'))
    previous = {(r['notification_id'], r['endpoint_hash']): r for r in deliveries}
    users = {m['id']: m for m in members}
    ops = Operations(db)
    visible = {mid: {r['id'] for r in filter_inbox(db, ops, m, [r for r in inbox if r['member_id']==mid])} for mid,m in users.items()}
    counts = {'sent': 0, 'failed': 0}
    for sub in subscriptions:
        member = users.get(sub['member_id'])
        if not member:
            db.table('push_subscriptions').delete().eq('endpoint_hash', sub['endpoint_hash']).execute()
            continue
        for item in inbox:
            if item['member_id'] != sub['member_id'] or item['id'] not in visible.get(sub['member_id'], set()):
                continue
            old = previous.get((item['id'], sub['endpoint_hash']), {})
            if old.get('sent_at') or (old.get('next_attempt_at') or '') > now.isoformat():
                continue
            if sum(counts.values()) >= 100:
                return counts
            record = {'notification_id': item['id'], 'endpoint_hash': sub['endpoint_hash'],
                      'attempts': (old.get('attempts', 0) % 3) + 1, 'next_attempt_at': (now+timedelta(minutes=15)).isoformat()}
            try:
                validated = subscription_payload({'endpoint': sub['endpoint'], 'keys': {'p256dh': sub['p256dh'], 'auth': sub['auth']}})
                send(subscription_info={'endpoint': validated['endpoint'], 'keys': {'p256dh': sub['p256dh'], 'auth': sub['auth']}},
                     data=json.dumps({'id': item['id'], 'url': item['url']}),
                     vapid_private_key=os.environ['WEB_PUSH_PRIVATE_KEY'],
                     vapid_claims={'sub': os.environ.get('WEB_PUSH_SUBJECT', os.environ.get('PUBLIC_BASE_URL', 'https://knu-read.xyz'))},
                     timeout=10, ttl=3600, requests_session=NoRedirectSession())
                record['sent_at'] = now.isoformat()
                counts['sent'] += 1
            except Exception as exc:
                counts['failed'] += 1
                response = getattr(exc, 'response', None)
                status = getattr(response, 'status_code', None)
                if status in (404, 410):
                    db.table('push_subscriptions').delete().eq('endpoint_hash', sub['endpoint_hash']).execute()
                    break
                if isinstance(exc, ValueError):
                    record['attempts'] = 3
                if record['attempts'] >= 3:
                    record['next_attempt_at'] = (now+timedelta(days=1)).isoformat()
            db.table('push_deliveries').upsert(record, on_conflict='notification_id,endpoint_hash').execute()
    return counts


def run(db, now=None, send=None):
    now = now or datetime.now(timezone.utc)
    items, members = collect_items(db, now)
    reconcile(db, items, now)
    return deliver(db, members, now, send)


if __name__ == '__main__':
    from supabase import create_client
    result = run(create_client(os.environ['SUPABASE_URL'], os.environ['SUPABASE_SERVICE_KEY']))
    print(json.dumps(result))
