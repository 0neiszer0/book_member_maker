"""발제문 제출 화면에 노출할 익명 미리보기 생성."""


def anonymous_topic_previews(submission_rows, limit=100):
    """제출 행에서 개인정보를 버리고 공개 가능한 발제 필드만 반환한다."""
    previews = []
    for row in submission_rows or []:
        topics = row.get('topics') if isinstance(row, dict) else None
        if not isinstance(topics, list):
            continue
        for item in topics:
            if not isinstance(item, dict):
                continue
            topic = str(item.get('topic') or '').strip()
            if not topic:
                continue
            previews.append({
                'topic': topic[:5000],
                'page': str(item.get('page') or '').strip()[:200],
                'reference': str(item.get('reference') or '').strip()[:5000],
            })
            if len(previews) >= limit:
                return previews
    return previews
