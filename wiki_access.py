"""Wiki access is derived from Kakao identity and today's saved semester roster.

No selected-term parameter, global active-member fallback or staff exemption.
The existing is_active on seminar_terms means enabled, not 'current semester'.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


@dataclass(frozen=True)
class WikiAccess:
    member_id: int
    can_edit: bool
    term_name: str
    reason: str


def wiki_access(db, identity, today=None):
    if identity.get('auth_provider') != 'kakao' or not identity.get('user_id'):
        return None
    members = db.table('members').select(
        'id,social_id,account_status,member_status'
    ).eq('id', identity['user_id']).limit(1).execute().data or []
    member = members[0] if members else None
    if (not member or not member.get('social_id') or member.get('account_status') != 'active'
            or member.get('member_status') in ('inactive', 'blocked', 'pending')):
        return None
    today = today or datetime.now(timezone(timedelta(hours=9))).date()
    terms = db.table('seminar_terms').select(
        'id,name,start_date,end_date,is_active,roster_initialized_at'
    ).eq('is_active', True).lte('start_date', today.isoformat()).gte('end_date', today.isoformat()).limit(2).execute().data or []
    if len(terms) != 1:
        return WikiAccess(member['id'], False, '', '현재 학기를 하나로 확인할 수 없어 읽기만 가능합니다.')
    term = terms[0]
    if not term.get('roster_initialized_at'):
        return WikiAccess(member['id'], False, term['name'], '이번 학기 활동 명단이 확정되면 편집할 수 있습니다.')
    rows = db.table('seminar_term_members').select('status').eq(
        'term_id', term['id']).eq('member_id', member['id']).limit(2).execute().data or []
    can_edit = len(rows) == 1 and rows[0].get('status') == 'active'
    return WikiAccess(member['id'], can_edit, term['name'],
                      '이번 학기 활동 회원으로 문서를 편집할 수 있습니다.' if can_edit
                      else '이번 학기 활동 회원만 편집할 수 있습니다. 현재는 읽기 전용입니다.')
