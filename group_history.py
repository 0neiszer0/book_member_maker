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
        for group in row.get('groups') or []:
            if not isinstance(group, list):
                continue
            names = [str(name).strip() for name in group if str(name).strip()]
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
