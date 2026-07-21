"""발제문 Word 출력에 쓰는 작성자 표시값 생성."""


def _text(value):
    return str(value or '').strip()


def admission_year_short(submission):
    """입학연도를 두 자리로 정규화하고, 없으면 학번에서 추정한다."""
    year = _text(submission.get('admission_year'))
    if not year:
        student_id = _text(submission.get('student_id'))
        if len(student_id) >= 4 and student_id[:4].isdigit():
            year = student_id[2:4]
    if len(year) == 4 and year.isdigit():
        year = year[2:]
    return year


def topic_submitter_identity(submission):
    """템플릿용 학과 표시와 전체 작성자 표시를 반환한다."""
    department = _text(submission.get('department'))
    year = admission_year_short(submission)
    author_name = _text(submission.get('author_name'))
    department_and_year = ' '.join(part for part in (department, year) if part)
    full_label = ' '.join(part for part in (department, year, author_name) if part)
    return {
        'department_and_year': department_and_year,
        'author_name': author_name,
        'full_label': full_label,
    }
