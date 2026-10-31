"""Wiki access is derived from Kakao identity and today's saved semester roster.

No selected-term parameter, global active-member fallback or staff exemption
for ordinary documents. The existing is_active on seminar_terms means enabled,
not 'current semester'.

Documents whose title starts with OFFICER_PREFIX ('운영진:') are officer-only.
Officers are the current semester's officer roster (term_officers rows with an
active operation_role for today's single current term). Site admins
(members.role='admin') always count, so the wiki can never lock out its
administrators. Until a term's roster is configured (operations_initialized_at
is empty) existing staff (members.role='officer') keep access, the same
transition rule operations.Operations.can uses. Every other member gets the
same 404 as for a missing document.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import logging
import re
import unicodedata
from minipc_security import LOGIN_PROVIDERS, has_login_identity, session_login_current

OFFICER_PREFIX = '운영진:'
log = logging.getLogger(__name__)


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


def _term_officer(db, member, term):
    if not term.get('operations_initialized_at'):
        return member.get('role') == 'officer'
    try:
        rows = db.table('term_officers').select('role_id').eq(
            'term_id', term['id']).eq('member_id', member['id']).execute().data or []
        role_ids = list({r['role_id'] for r in rows if r.get('role_id')})
        if not role_ids:
            return False
        roles = db.table('operation_roles').select('id,is_active').in_('id', role_ids).execute().data or []
    except Exception:
        # Officer pages fail closed; ordinary wiki reading keeps working.
        log.exception('Wiki officer roster lookup failed')
        return False
    return any(r.get('is_active', True) is not False for r in roles)


def wiki_access(db, identity, today=None):
    if identity.get('auth_provider') not in LOGIN_PROVIDERS or not identity.get('user_id'):
        return None
    members = db.table('members').select(
        'id,social_id,account_status,member_status,role,is_active,auth_provider,auth_session_version'
    ).eq('id', identity['user_id']).limit(1).execute().data or []
    member = members[0] if members else None
    if (not member or not has_login_identity(member, identity) or not session_login_current(member, identity)
            or member.get('account_status') != 'active'
            or member.get('member_status') in ('inactive', 'blocked', 'pending')):
        return None
    active_account = member.get('is_active') is not False
    is_officer = active_account and member.get('role') == 'admin'
    today = today or datetime.now(timezone(timedelta(hours=9))).date()
    terms = db.table('seminar_terms').select(
        'id,name,start_date,end_date,is_active,roster_initialized_at,operations_initialized_at'
    ).eq('is_active', True).lte('start_date', today.isoformat()).gte('end_date', today.isoformat()).limit(2).execute().data or []
    if len(terms) != 1:
        return WikiAccess(member['id'], False, '', '편집할 학기 확인이 필요합니다. 읽기는 가능하며, 편집하려면 운영진에게 문의해 주세요.', is_officer)
    term = terms[0]
    if active_account and not is_officer:
        is_officer = _term_officer(db, member, term)
    if not term.get('roster_initialized_at'):
        return WikiAccess(member['id'], False, term['name'], '이번 학기 활동 명단이 확정되면 편집할 수 있습니다.', is_officer)
    rows = db.table('seminar_term_members').select('status').eq(
        'term_id', term['id']).eq('member_id', member['id']).limit(2).execute().data or []
    can_edit = len(rows) == 1 and rows[0].get('status') == 'active'
    return WikiAccess(member['id'], can_edit, term['name'],
                      '이번 학기 활동 회원으로 문서를 편집할 수 있습니다.' if can_edit
                      else '이번 학기 활동 회원만 편집할 수 있습니다. 현재는 읽기 전용입니다.', is_officer)
