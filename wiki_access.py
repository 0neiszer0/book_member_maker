"""Wiki access is derived from Kakao identity and today's saved semester roster.

No selected-term parameter, global active-member fallback or staff exemption
for ordinary documents. The existing is_active on seminar_terms means enabled,
not 'current semester'.

Documents whose title starts with OFFICER_PREFIX ('운영진:') are officer-only:
only active admin/officer accounts (the same members.role check used by the
club room and member management) may read, list, search or edit them. Every
other member gets the same 404 as for a missing document.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import re
import unicodedata

OFFICER_PREFIX = '운영진:'
OFFICER_ROLES = ('admin', 'officer')


@dataclass(frozen=True)
class WikiAccess:
    member_id: int
    can_edit: bool
    term_name: str
    reason: str
    is_officer: bool = False


def _normal(value):
    return unicodedata.normalize('NFKC', value or '').strip()


def is_officer_title(title):
    """True for the officer namespace, also after width/compatibility folding."""
    return _normal(title).startswith(OFFICER_PREFIX)


def can_read_title(access, title):
    return bool(access) and (access.is_officer or not is_officer_title(title))


def can_edit_title(access, title):
    if not access:
        return False
    if is_officer_title(title):
        return access.is_officer
    return access.can_edit


# openNamu renders [include(문서)] server-side with the shared bridge account, so
# a member-written page could otherwise transclude an officer document.
_OFFICER_INCLUDE = re.compile(r'\[\s*include\s*\(\s*' + re.escape(OFFICER_PREFIX), re.IGNORECASE)


def strip_officer_includes(source):
    folded = _normal(source).replace('\\', '')
    if not _OFFICER_INCLUDE.search(folded):
        return source
    lines = []
    for line in source.split('\n'):
        if _OFFICER_INCLUDE.search(_normal(line).replace('\\', '')):
            line = '(운영진 전용 문서는 표시할 수 없습니다.)'
        lines.append(line)
    result = '\n'.join(lines)
    # Multi-line or otherwise obfuscated macros: refuse to render rather than leak.
    if _OFFICER_INCLUDE.search(_normal(result).replace('\\', '')):
        return '(운영진 전용 문서를 포함한 내용은 표시할 수 없습니다.)'
    return result


def wiki_access(db, identity, today=None):
    if identity.get('auth_provider') != 'kakao' or not identity.get('user_id'):
        return None
    members = db.table('members').select(
        'id,social_id,account_status,member_status,role,is_active'
    ).eq('id', identity['user_id']).limit(1).execute().data or []
    member = members[0] if members else None
    if (not member or not member.get('social_id') or member.get('account_status') != 'active'
            or member.get('member_status') in ('inactive', 'blocked', 'pending')):
        return None
    is_officer = member.get('role') in OFFICER_ROLES and member.get('is_active') is not False
    today = today or datetime.now(timezone(timedelta(hours=9))).date()
    terms = db.table('seminar_terms').select(
        'id,name,start_date,end_date,is_active,roster_initialized_at'
    ).eq('is_active', True).lte('start_date', today.isoformat()).gte('end_date', today.isoformat()).limit(2).execute().data or []
    if len(terms) != 1:
        return WikiAccess(member['id'], False, '', '편집할 학기 확인이 필요합니다. 읽기는 가능하며, 편집하려면 운영진에게 문의해 주세요.', is_officer)
    term = terms[0]
    if not term.get('roster_initialized_at'):
        return WikiAccess(member['id'], False, term['name'], '이번 학기 활동 명단이 확정되면 편집할 수 있습니다.', is_officer)
    rows = db.table('seminar_term_members').select('status').eq(
        'term_id', term['id']).eq('member_id', member['id']).limit(2).execute().data or []
    can_edit = len(rows) == 1 and rows[0].get('status') == 'active'
    return WikiAccess(member['id'], can_edit, term['name'],
                      '이번 학기 활동 회원으로 문서를 편집할 수 있습니다.' if can_edit
                      else '이번 학기 활동 회원만 편집할 수 있습니다. 현재는 읽기 전용입니다.', is_officer)
