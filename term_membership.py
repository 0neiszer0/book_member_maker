"""Semester participation is independent of account access and global status."""
from datetime import datetime, timedelta, timezone

STATUSES = {'active': '활동', 'paused': '휴식', 'left': '종료'}
ENTRY_TYPES = {'continuing': '계속 활동', 'new': '신규', 'returning': '복귀'}


def choose_term(terms, term_id=None):
    if term_id:
        return next((t for t in terms if str(t['id']) == str(term_id)), None)
    today = datetime.now(timezone(timedelta(hours=9))).date().isoformat()
    return (next((t for t in terms if t['start_date'] <= today <= t['end_date']), None)
            or next((t for t in terms if t.get('is_active')), None)
            or (terms[0] if terms else None))


def scope_members(db, members, term=None, term_id=None):
    """Copies only: never mutate global member status or infer historical rosters.

    Legacy terms retain their old active-member fallback until explicitly saved.
    An initialized empty roster is intentionally empty, not a fallback.
    """
    if term is None and term_id:
        rows = db.table('seminar_terms').select('*').eq('id', term_id).limit(1).execute().data or []
        term = rows[0] if rows else None
    if not term or not term.get('roster_initialized_at'):
        return [dict(m) for m in members]
    memberships = db.table('seminar_term_members').select('member_id,status,entry_type').eq('term_id', term['id']).execute().data or []
    by_id = {int(row['member_id']): row for row in memberships}
    return [{**m, 'is_active': by_id.get(int(m['id']), {}).get('status') == 'active',
             'term_status': by_id.get(int(m['id']), {}).get('status'),
             'entry_type': by_id.get(int(m['id']), {}).get('entry_type')} for m in members]


def validate_entries(entries, valid_ids):
    if not isinstance(entries, list) or len(entries) > 5000:
        raise ValueError('명단 형식을 확인해주세요.')
    seen, result = set(), []
    for row in entries:
        if not isinstance(row, dict) or type(row.get('member_id')) is not int:
            raise ValueError('회원 번호를 확인해주세요.')
        mid = row['member_id']
        if mid in seen or mid not in valid_ids:
            raise ValueError('중복되거나 존재하지 않는 회원이 있습니다. 새로고침해주세요.')
        if row.get('status') not in STATUSES or row.get('entry_type') not in ENTRY_TYPES:
            raise ValueError('활동 상태와 가입 구분을 확인해주세요.')
        seen.add(mid)
        result.append({key: row[key] for key in ('member_id', 'status', 'entry_type')})
    return sorted(result, key=lambda row: row['member_id'])
