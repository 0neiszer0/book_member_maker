import re


def normalize_member_student_id(value):
    """Normalize member student IDs without changing their digits."""
    return re.sub(r"\s+", "", str(value or ""))


def valid_member_student_id(value):
    normalized = normalize_member_student_id(value)
    return not normalized or bool(re.fullmatch(r"[0-9]{4,20}", normalized))


def duplicate_student_id_values(members):
    counts = {}
    for member in members or []:
        student_id = normalize_member_student_id(member.get("student_id"))
        if student_id:
            counts[student_id] = counts.get(student_id, 0) + 1
    return {student_id for student_id, count in counts.items() if count > 1}


def member_student_id_conflicts(members, proposed_student_id, exclude_member_id=None):
    proposed = normalize_member_student_id(proposed_student_id)
    if not proposed:
        return False
    for member in members or []:
        if exclude_member_id is not None and str(member.get("id")) == str(exclude_member_id):
            continue
        if normalize_member_student_id(member.get("student_id")) == proposed:
            return True
    return False
