"""세미나 불참 일괄 입력값 검증."""


def normalize_member_ids(payload, max_items=200):
    """단일/복수 회원 입력을 중복 없는 양의 정수 목록으로 정규화한다."""
    raw_ids = payload.get('member_ids')
    if raw_ids is None:
        raw_ids = [payload.get('member_id')]
    if not isinstance(raw_ids, list):
        raise ValueError('회원 목록 형식이 올바르지 않습니다.')

    member_ids = []
    seen = set()
    for raw_id in raw_ids:
        try:
            member_id = int(raw_id)
        except (TypeError, ValueError):
            raise ValueError('회원을 다시 선택해주세요.')
        if member_id <= 0:
            raise ValueError('회원을 다시 선택해주세요.')
        if member_id not in seen:
            seen.add(member_id)
            member_ids.append(member_id)

    if not member_ids:
        raise ValueError('한 명 이상 선택해주세요.')
    if len(member_ids) > max_items:
        raise ValueError(f'한 번에 최대 {max_items}명까지 선택할 수 있습니다.')
    return member_ids
