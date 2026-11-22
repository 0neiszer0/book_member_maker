import re
from io import BytesIO
from pathlib import Path
from zipfile import BadZipFile, ZipFile


VALID_RESULT_STATUSES = ("pending", "accepted", "waitlisted", "rejected")
RESULT_STATUS_LABELS = {
    "pending": "발표 전",
    "accepted": "합격",
    "waitlisted": "예비",
    "rejected": "불합격",
}
RESULT_STATUS_ALIASES = {
    "": "pending",
    "pending": "pending",
    "발표전": "pending",
    "미정": "pending",
    "accepted": "accepted",
    "합격": "accepted",
    "waitlisted": "waitlisted",
    "waitlist": "waitlisted",
    "예비": "waitlisted",
    "예비합격": "waitlisted",
    "rejected": "rejected",
    "불합격": "rejected",
}


def normalize_applicant_name(value):
    """Match names case-insensitively while ignoring all whitespace."""
    return re.sub(r"\s+", "", str(value or "")).casefold()


def normalize_student_id(value):
    return re.sub(r"\s+", "", str(value or ""))


def normalize_result_status(value):
    key = re.sub(r"\s+", "", str(value or "")).casefold()
    return RESULT_STATUS_ALIASES.get(key)


def parse_applicant_rows(raw_text, max_rows=500):
    """Parse rows pasted from Excel: name, student id, optional status/message."""
    parsed = []
    errors = []
    seen_student_ids = set()
    lines = str(raw_text or "").splitlines()
    non_empty_lines = [line for line in lines if line.strip()]
    if len(non_empty_lines) > max_rows:
        return [], [f"한 번에 최대 {max_rows}명까지 입력할 수 있습니다."]

    for line_number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        parts = line.split("\t") if "\t" in line else line.split(",")
        parts = [part.strip() for part in parts]
        if len(parts) < 2:
            errors.append(f"{line_number}행: 이름과 학번이 필요합니다.")
            continue
        if not parsed and parts[0].replace(" ", "") in ("이름", "성명") and parts[1].replace(" ", "") in ("학번", "학생번호"):
            continue
        name = parts[0]
        student_id = normalize_student_id(parts[1])
        status_provided = len(parts) > 2 and bool(parts[2].strip())
        message_provided = len(parts) > 3
        status = normalize_result_status(parts[2] if status_provided else "")
        personal_message = ",".join(parts[3:]).strip() if "\t" not in line else "\t".join(parts[3:]).strip()
        duplicate_student_id = student_id in seen_student_ids
        if re.fullmatch(r"[0-9]{4,20}", student_id):
            seen_student_ids.add(student_id)
        if not normalize_applicant_name(name):
            errors.append(f"{line_number}행: 이름을 확인해주세요.")
        elif not re.fullmatch(r"[0-9]{4,20}", student_id):
            errors.append(f"{line_number}행: 학번은 4~20자리 숫자여야 합니다.")
        elif duplicate_student_id:
            errors.append(f"{line_number}행: 같은 학번이 입력 안에 중복되어 있습니다.")
        elif status is None:
            errors.append(f"{line_number}행: 결과는 발표 전·합격·예비·불합격 중 하나여야 합니다.")
        elif len(personal_message) > 3000:
            errors.append(f"{line_number}행: 개인 안내는 3,000자 이하여야 합니다.")
        else:
            parsed.append({
                "name": name,
                "name_key": normalize_applicant_name(name),
                "student_id": student_id,
                "result_status": status,
                "personal_message": personal_message or None,
                "_status_provided": status_provided,
                "_message_provided": message_provided,
            })
    return parsed, errors


def _excel_cell_text(value):
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def parse_applicant_file(filename, content, max_rows=500, max_bytes=2 * 1024 * 1024):
    """Parse a small .xlsx or .csv applicant list without writing it to disk."""
    suffix = Path(str(filename or "")).suffix.lower()
    raw = bytes(content or b"")
    if not raw:
        return [], ["업로드한 파일이 비어 있습니다."]
    if len(raw) > max_bytes:
        return [], ["명단 파일은 2MB 이하만 업로드할 수 있습니다."]
    if suffix == ".csv":
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            try:
                text = raw.decode("cp949")
            except UnicodeDecodeError:
                return [], ["CSV 파일은 UTF-8 또는 한글 Excel 형식으로 저장해주세요."]
        return parse_applicant_rows(text, max_rows=max_rows)
    if suffix != ".xlsx":
        return [], ["Excel(.xlsx) 또는 CSV(.csv) 파일만 업로드할 수 있습니다."]

    try:
        with ZipFile(BytesIO(raw)) as archive:
            if sum(item.file_size for item in archive.infolist()) > 20 * 1024 * 1024:
                return [], ["압축을 푼 명단 파일이 너무 큽니다."]
        from openpyxl import load_workbook
        workbook = load_workbook(BytesIO(raw), read_only=True, data_only=True)
        sheet = workbook.active
        lines = []
        for values in sheet.iter_rows(values_only=True):
            cells = [_excel_cell_text(value) for value in values[:4]]
            if any(cells):
                lines.append("\t".join(cells))
                if len(lines) > max_rows + 1:
                    workbook.close()
                    return [], [f"한 번에 최대 {max_rows}명까지 입력할 수 있습니다."]
        workbook.close()
    except (BadZipFile, OSError, ValueError):
        return [], ["Excel 파일을 읽을 수 없습니다. 손상되지 않은 .xlsx 파일인지 확인해주세요."]
    except Exception:
        return [], ["Excel 파일 형식을 확인해주세요."]
    return parse_applicant_rows("\n".join(lines), max_rows=max_rows)


DEFAULT_APPLICATION_QUESTIONS = [
    {"id": "motivation", "label": "동아리 지원 동기 및 기대하는 점", "placeholder": "책을 읽고 함께 나누고 싶은 이유와 동아리에서 기대하는 점을 구체적으로 적어주세요. (최소 200자 이상)", "required": True, "min_length": 200, "max_length": 1500},
    {"id": "favorite_book", "label": "인상 깊게 읽었거나 함께 나누고 싶은 책", "placeholder": "책 제목과 인상 깊었던 이유를 자유롭게 적어주세요. (최소 200자 이상)", "required": True, "min_length": 200, "max_length": 1500},
    {"id": "intro", "label": "정기 세미나 외에 해보고 싶은 활동이나 자기소개", "placeholder": "평소 독서 스타일, 관심 분야, 소모임 아이디어 등을 자유롭게 적어주세요.", "required": False, "min_length": 0, "max_length": 1500},
]


def _int_in_range(value, low, high, default):
    if value is None or value == '':
        return default
    if isinstance(value, bool):
        raise ValueError("글자수 제한 형식을 확인해주세요.")
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ValueError("글자수 제한 형식을 확인해주세요.")
    if not low <= number <= high:
        raise ValueError(f"글자수 제한은 {low}~{high} 범위로 입력해주세요.")
    return number


def normalize_application_questions(raw):
    import json
    import hashlib
    if isinstance(raw, str):
        try:
            raw = json.loads(raw) if raw.lstrip().startswith('[') and not raw.lstrip().startswith('[선택]') and not raw.lstrip().startswith('[최소') else raw.splitlines()
        except ValueError:
            raw = raw.splitlines()
    if not isinstance(raw, list) or len(raw) > 15:
        raise ValueError("질문은 최대 15개까지 입력할 수 있습니다.")
    result, ids = [], set()
    for item in raw:
        if isinstance(item, str):
            label = item.strip()
            if not label:
                continue
            required = True
            min_length = 0
            while True:
                if label.startswith('[선택]'):
                    required, label = False, label[4:].strip()
                    continue
                tag = re.match(r'\[최소\s*(\d{1,4})\s*자\]\s*', label)
                if tag:
                    min_length, label = int(tag.group(1)), label[tag.end():].strip()
                    continue
                break
            item = {"id": "q_" + hashlib.sha256(label.encode('utf-8')).hexdigest()[:16], "label": label, "placeholder": "", "required": required, "min_length": min_length}
        if not isinstance(item, dict):
            raise ValueError("질문 형식을 확인해주세요.")
        ident, label = item.get('id'), item.get('label')
        placeholder, required = item.get('placeholder', ''), item.get('required')
        if not isinstance(ident, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', ident) or ident in ids or not isinstance(label, str) or not 1 <= len(label.strip()) <= 200 or not isinstance(placeholder, str) or len(placeholder) > 200 or not isinstance(required, bool):
            raise ValueError("질문 ID, 내용 또는 필수 여부를 확인해주세요.")
        min_length = _int_in_range(item.get('min_length'), 0, 2000, 0)
        max_length = _int_in_range(item.get('max_length'), 50, 3000, 3000)
        if min_length > max_length:
            raise ValueError(f"'{label.strip()}' 항목의 최소 글자수는 최대 글자수보다 클 수 없습니다.")
        ids.add(ident)
        result.append({"id": ident, "label": label.strip(), "placeholder": placeholder, "required": required, "min_length": min_length, "max_length": max_length})
    return result


def normalize_phone(value):
    phone = re.sub(r'[\s]', '', value or '')
    digits = phone.replace('-', '')
    if re.fullmatch(r'010[0-9]{8}', digits):
        return f"{digits[:3]}-{digits[3:7]}-{digits[7:]}"
    return phone


def normalize_interview_slot_options(raw):
    if isinstance(raw, str):
        raw = raw.splitlines()
    if not isinstance(raw, list) or len(raw) > 40 or any(not isinstance(x, str) or len(x.strip()) > 100 for x in raw):
        raise ValueError("면접 시간은 최대 40개, 각각 100자 이하로 입력해주세요.")
    return list(dict.fromkeys(x.strip() for x in raw if x.strip()))


def validate_application_submission(campaign, form):
    name = (form.get('name') or '').strip()
    sid = normalize_student_id(form.get('student_id'))
    department = (form.get('department') or '').strip()
    phone = normalize_phone(form.get('phone'))
    email = (form.get('knu_email') or '').strip().lower()
    note = (form.get('interview_availability_note') or '').strip()
    if form.get('website'):
        raise ValueError('제출을 처리하지 못했습니다.')
    if not 1 <= len(name) <= 80 or not normalize_applicant_name(name) or not re.fullmatch(r'[0-9]{4,20}', sid):
        raise ValueError('이름과 학번을 확인해주세요.')
    if not 1 <= len(department) <= 100 or not re.fullmatch(r'[0-9-]{8,25}', phone):
        raise ValueError('학과와 연락처를 확인해주세요.')
    if email.endswith('@knu.ac.kr'):
        email = email[:-len('@knu.ac.kr')]
    if email and '@' not in email:
        email += '@knu.ac.kr'
    if email and (len(email) > 254 or not re.fullmatch(r'[a-z0-9._%+-]+@knu\.ac\.kr', email)):
        raise ValueError('학교 메일을 확인해주세요.')
    options = normalize_interview_slot_options(campaign.get('interview_slot_options') or [])
    selected = form.getlist('interview_availability') if hasattr(form, 'getlist') else form.get('interview_availability', [])
    if not isinstance(selected, list) or any(x not in options for x in selected) or len(note) > 500:
        raise ValueError('면접 가능 시간을 확인해주세요.')
    answers = {}
    for q in normalize_application_questions(campaign.get('application_questions', DEFAULT_APPLICATION_QUESTIONS)):
        answer = (form.get('answer_' + q['id']) or '').strip()
        max_length, min_length = q.get('max_length') or 3000, q.get('min_length') or 0
        if q['required'] and not answer:
            raise ValueError(f"'{q['label']}' 항목을 입력해주세요.")
        if answer and min_length > 0 and len(answer) < min_length:
            raise ValueError(f"'{q['label']}' 항목은 최소 {min_length}자 이상 작성해주세요. (현재 {len(answer)}자)")
        if len(answer) > max_length:
            raise ValueError(f"'{q['label']}' 항목은 최대 {max_length}자 이하로 작성해주세요.")
        answers[q['id']] = {'label': q['label'], 'answer': answer}
    return {'name': name, 'name_key': normalize_applicant_name(name), 'student_id': sid, 'department': department, 'phone': phone, 'knu_email': email or None, 'interview_availability': list(dict.fromkeys(selected)), 'interview_availability_note': note or None, 'answers': answers}


def build_applicants_workbook(campaign, applicants):
    from openpyxl import Workbook
    from openpyxl.styles import Font
    from openpyxl.utils import get_column_letter
    questions = normalize_application_questions(campaign.get('application_questions', DEFAULT_APPLICATION_QUESTIONS))
    wb = Workbook()
    ws = wb.active
    ws.title = '지원자'
    ws.append(['이름', '학번', '학과', '연락처', '학교메일', '지원일시', '면접가능시간', '배정면접일정', '결과', '회비입금', '운영진메모'] + [q['label'] for q in questions])
    for applicant in applicants:
        answers = applicant.get('answers') or {}
        values = [applicant.get('name'), applicant.get('student_id'), applicant.get('department'), applicant.get('phone'), applicant.get('knu_email'), applicant.get('submitted_at'), ', '.join(applicant.get('interview_availability') or []) + (' / ' + applicant['interview_availability_note'] if applicant.get('interview_availability_note') else ''), applicant.get('interview_slot'), RESULT_STATUS_LABELS.get(applicant.get('result_status'), '발표 전'), '확인' if applicant.get('dues_paid_at') else '', applicant.get('reviewer_note')]
        values += [(answers.get(q['id']) or {}).get('answer', '') if isinstance(answers.get(q['id']), dict) else answers.get(q['id'], '') for q in questions]
        # Force text cells to prevent applicant-supplied formula execution.
        ws.append([str(v or '') for v in values])
        for cell in ws[ws.max_row]:
            cell.data_type = 's'
    for cell in ws[1]:
        cell.font = Font(bold=True)
    ws.freeze_panes = 'A2'
    ws.auto_filter.ref = ws.dimensions
    for i in range(1, ws.max_column + 1):
        ws.column_dimensions[get_column_letter(i)].width = 22
    output = BytesIO()
    wb.save(output)
    output.seek(0)
    return output
