"""조 편성 이력에서 만남 매트릭스를 계산하는 순수 함수."""

import itertools


def canonical_pair_key(a, b):
    names = sorted([str(a).strip(), str(b).strip()])
    return '-'.join(names)


def pair_keys_from_groups(groups):
    keys = set()
    for group in groups or []:
        if not isinstance(group, list):
            continue
        names = [str(name).strip() for name in group if str(name).strip()]
        for a, b in itertools.combinations(names, 2):
            if a != b:
                keys.add(canonical_pair_key(a, b))
    return keys


def matrix_rows_from_history(history_rows, only_keys=None):
    only_keys = set(only_keys) if only_keys is not None else None
    stats = {}
    for row in history_rows or []:
        meeting_date = str(row.get('date') or '').strip()
        excluded_names = {
            str(name).strip() for name in (row.get('excluded_names') or [])
            if str(name).strip()
        }
        for group in row.get('groups') or []:
            if not isinstance(group, list):
                continue
            names = [
                str(name).strip() for name in group
                if str(name).strip() and str(name).strip() not in excluded_names
            ]
            for a, b in itertools.combinations(names, 2):
                if a == b:
                    continue
                key = canonical_pair_key(a, b)
                if only_keys is not None and key not in only_keys:
                    continue
                item = stats.setdefault(key, {'pair_key': key, 'count': 0, 'last_met': None})
                item['count'] += 1
                if meeting_date and (not item['last_met'] or meeting_date > item['last_met']):
                    item['last_met'] = meeting_date
    return stats


def meeting_details_from_history(history_rows, before_date=None, exclude_history_id=None):
    """Return pair meeting counts and every recorded date for result previews."""
    stats = {}
    for row in history_rows or []:
        meeting_date = str(row.get('date') or '').strip()
        if exclude_history_id is not None and str(row.get('id')) == str(exclude_history_id):
            continue
        if before_date and (not meeting_date or meeting_date >= str(before_date)):
            continue
        excluded_names = {
            str(name).strip() for name in (row.get('excluded_names') or [])
            if str(name).strip()
        }
        for group in row.get('groups') or []:
            if not isinstance(group, list):
                continue
            names = [
                str(name).strip() for name in group
                if str(name).strip() and str(name).strip() not in excluded_names
            ]
            for a, b in itertools.combinations(names, 2):
                if a == b:
                    continue
                key = canonical_pair_key(a, b)
                item = stats.setdefault(key, {
                    'count': 0,
                    'last_met': None,
                    'dates': [],
                })
                item['count'] += 1
                if meeting_date:
                    if meeting_date not in item['dates']:
                        item['dates'].append(meeting_date)
                    if not item['last_met'] or meeting_date > item['last_met']:
                        item['last_met'] = meeting_date
    for item in stats.values():
        item['dates'].sort(reverse=True)
    return stats


def normalize_group_editor_payload(groups, editor_state=None):
    """Validate a complete seating chart without changing actual attendance."""
    if not isinstance(groups, list) or not groups or not all(isinstance(group, list) for group in groups):
        raise ValueError('한 명 이상 배정된 조가 필요합니다.')
    cleaned = []
    seen = set()
    for group in groups:
        if not group:
            raise ValueError('빈 조를 삭제하거나 참여자를 배정해주세요.')
        names = []
        for name in group:
            if not isinstance(name, str) or not name.strip() or len(name.strip()) > 100:
                raise ValueError('참여자 이름을 확인해주세요.')
            name = name.strip()
            if name in seen:
                raise ValueError('같은 사람이 여러 번 배정되어 있습니다. 중복 배정을 확인해주세요.')
            seen.add(name)
            names.append(name)
        cleaned.append(names)
    if editor_state is None:
        return cleaned, {'participants': [name for group in cleaned for name in group], 'excluded': [],
                         'group_names': [f'조 {index + 1}' for index in range(len(cleaned))]}
    if not isinstance(editor_state, dict):
        raise ValueError('편집 상태 형식이 올바르지 않습니다.')
    participants = editor_state.get('participants')
    excluded = editor_state.get('excluded', [])
    if not isinstance(participants, list) or not all(isinstance(name, str) and name.strip() for name in participants):
        raise ValueError('참여자 명단 형식이 올바르지 않습니다.')
    participants = [name.strip() for name in participants]
    if len(set(participants)) != len(participants) or any(len(name) > 100 for name in participants):
        raise ValueError('참여자 명단에 중복 또는 잘못된 이름이 있습니다.')
    if not isinstance(excluded, list):
        raise ValueError('편성 제외 명단 형식이 올바르지 않습니다.')
    exclusions = []
    excluded_names = set()
    for item in excluded:
        if not isinstance(item, dict) or not isinstance(item.get('name'), str) or not isinstance(item.get('reason'), str):
            raise ValueError('편성 제외 이름과 사유를 입력해주세요.')
        name, reason = item['name'].strip(), item['reason'].strip()
        if not name or not reason or len(reason) > 200 or name in seen or name in excluded_names:
            raise ValueError('편성 제외 이름·사유 또는 중복 상태를 확인해주세요.')
        excluded_names.add(name)
        exclusions.append({'name': name, 'reason': reason})
    if set(participants) != seen | excluded_names:
        raise ValueError('미배정 참여자를 배정하거나 사유를 입력해 편성에서 제외해주세요.')
    group_names = editor_state.get('group_names')
    if group_names is None:
        group_names = [f'조 {index + 1}' for index in range(len(cleaned))]
    if not isinstance(group_names, list) or len(group_names) != len(cleaned) or any(
        not isinstance(name, str) or not name.strip() or len(name) > 100 for name in group_names
    ):
        raise ValueError('조 이름을 확인해주세요.')
    return cleaned, {'participants': participants, 'excluded': exclusions, 'group_names': group_names}
