"""Helpers for confidential group-pair restrictions.

The application groups people by name, while restrictions are stored by stable
member IDs.  These helpers keep the ID-to-name translation and final validation
in one small, testable place.
"""


def canonical_name_pair(first, second):
    first = str(first or "").strip()
    second = str(second or "").strip()
    if not first or not second or first == second:
        return None
    return tuple(sorted((first, second)))


def restricted_pairs_from_rows(restriction_rows, member_rows):
    names_by_id = {
        member.get("id"): str(member.get("name") or "").strip()
        for member in (member_rows or [])
    }
    pairs = set()
    for row in restriction_rows or []:
        pair = canonical_name_pair(
            names_by_id.get(row.get("member_a_id")),
            names_by_id.get(row.get("member_b_id")),
        )
        if pair:
            pairs.add(pair)
    return pairs


def find_restriction_conflicts(groups, restricted_pairs):
    restricted = set(restricted_pairs or [])
    conflicts = []
    for group in groups or []:
        names = [str(name or "").strip() for name in group if str(name or "").strip()]
        for left_index, left_name in enumerate(names):
            for right_name in names[left_index + 1:]:
                pair = canonical_name_pair(left_name, right_name)
                if pair and pair in restricted:
                    conflicts.append(pair)
    return conflicts
