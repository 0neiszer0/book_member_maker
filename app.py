# app.py
# 모든 기능이 통합된 최종 버전의 Flask 애플리케이션 코드입니다.

# --- 1. 기본 라이브러리 및 설정 ---
import os
import itertools
import random
import math
from dotenv import load_dotenv
from flask import Flask, render_template, request, jsonify, session, redirect, url_for, flash
from supabase import create_client, Client
from datetime import datetime, timedelta, time, timezone
from functools import wraps
import requests

# .env 파일에서 환경 변수 로드
load_dotenv()

# Flask 앱 초기화 및 시크릿 키 설정
app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY")
if not app.secret_key:
    raise ValueError("FLASK_SECRET_KEY가 .env 파일에 설정되지 않았습니다.")

# Supabase 클라이언트 초기화
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("Supabase URL과 Key가 .env 파일에 설정되지 않았습니다.")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)


# ==============================================================================
# --- 2. 헬퍼 함수 및 공용 시스템 ---
# ==============================================================================

# Jinja2 템플릿에서 날짜 형식을 예쁘게 보여주기 위한 필터
def format_datetime_filter(value, format_str="%Y년 %m월 %d일 %p %I:%M"):
    """
    [최종 수정] 시간대(timezone)를 올바르게 '변환'하여 KST로 표시하는 함수.
    astimezone()을 사용하여 모든 시간 관련 오류를 해결합니다.
    """
    if not value: return ""
    try:
        # 한국 시간대(KST, UTC+9)를 명확하게 정의합니다.
        KST = timezone(timedelta(hours=9))

        # 데이터베이스의 UTC 시간 문자열을 UTC-aware datetime 객체로 변환합니다.
        utc_dt = datetime.fromisoformat(value.replace('Z', '+00:00'))

        # astimezone()을 사용하여 UTC 시간을 KST 시간으로 정확하게 변환합니다.
        kst_dt = utc_dt.astimezone(KST)

        # 변환된 KST 시간을 원하는 형식의 문자열로 만듭니다.
        return kst_dt.strftime(format_str).replace("AM", "오전").replace("PM", "오후")
    except (ValueError, TypeError):
        # 혹시 모를 오류 발생 시, 원래 값을 그대로 보여줍니다.
        return value


app.jinja_env.filters['datetime'] = format_datetime_filter


# 로그인 여부 및 역할 확인을 위한 데코레이터 (문지기 함수)
def login_required(role="ANY"):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if "user_role" not in session:
                flash("로그인이 필요합니다.", "warning")
                return redirect(url_for('login'))
            if role != "ANY" and session["user_role"] != role:
                flash("이 페이지에 접근할 권한이 없습니다.", "danger")
                return redirect(url_for('main_index'))
            return f(*args, **kwargs)

        return decorated_function

    return decorator


def send_telegram_notification(message):
    """[수정] 여러 관리자에게 텔레그램 메시지를 발송합니다."""
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    # [수정] 쉼표로 구분된 여러 채팅 ID를 불러옵니다.
    chat_ids_str = os.environ.get("TELEGRAM_CHAT_IDS")

    if not bot_token or not chat_ids_str:
        app.logger.error("텔레그램 봇 토큰 또는 관리자 채팅 ID가 설정되지 않았습니다.")
        return

    # 쉼표로 구분된 문자열을 개별 ID 리스트로 변환합니다.
    chat_ids = [chat_id.strip() for chat_id in chat_ids_str.split(',')]

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

    # 각 채팅 ID에 대해 메시지를 발송합니다.
    for chat_id in chat_ids:
        params = {
            'chat_id': chat_id,
            'text': message,
            'parse_mode': 'Markdown'
        }
        try:
            response = requests.get(url, params=params)
            response.raise_for_status()  # 오류 발생 시 예외 발생
            app.logger.info(f"{chat_id}로 텔레그램 알림이 성공적으로 발송되었습니다.")
        except Exception as e:
            app.logger.error(f"{chat_id}로 텔레그램 알림 발송 실패: {e}")


# ==============================================================================
# --- 3. 로그인, 로그아웃, 메인 페이지 라우트 ---
# ==============================================================================

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        role = request.form.get('role')
        password = request.form.get('password')
        ADMIN_PASS = os.environ.get("ADMIN_PASSWORD")
        INTERVIEWER_PASS = os.environ.get("INTERVIEWER_PASSWORD")
        APPLICANT_PASS = os.environ.get("APPLICANT_PASSWORD")

        if role == 'admin' and password == ADMIN_PASS:
            session.clear()
            session['user_role'] = 'admin'
            session['user_name'] = '관리자'
            flash('관리자님, 환영합니다!', 'success')
            return redirect(url_for('admin_dashboard'))

        elif role == 'interviewer' and password == INTERVIEWER_PASS:
            interviewer_name = request.form.get('name')
            if not interviewer_name:
                flash('면접관 이름을 입력해주세요.', 'danger')
                return redirect(url_for('login'))
            session.clear()
            session['user_role'] = 'interviewer'
            session['user_name'] = interviewer_name
            flash(f"{session['user_name']} 면접관님, 환영합니다!", 'success')
            return redirect(url_for('interviewer_events_list'))

        elif role == 'applicant' and password == APPLICANT_PASS:
            session.clear()
            session['user_role'] = 'applicant'
            session['user_name'] = request.form.get('name')
            session['user_phone'] = request.form.get('phone_number')
            flash(f"{session['user_name']}님, 환영합니다!", 'success')
            return redirect(url_for('interview_index'))

        else:
            flash('입력 정보가 올바르지 않습니다.', 'danger')
            return redirect(url_for('login'))

    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    flash('성공적으로 로그아웃되었습니다.', 'info')
    return redirect(url_for('main_index'))


@app.route('/')
def main_index():
    return render_template('main_index.html')


# ==============================================================================
# --- 4. 관리자 (Admin) 전용 기능 ---
# ==============================================================================

# --- 4.1. 관리자 대시보드 및 이벤트 관리 ---
@app.route('/admin/dashboard')
@login_required(role="admin")
def admin_dashboard():
    try:
        events_res = supabase.table('events').select('*').order('created_at', desc=True).execute()
        interviewers_res = supabase.table('interviewers').select('name').execute()
        members_res = supabase.table('members').select('name').order('name').execute()

        # 현재 면접관인 사람들의 이름만 Set으로 만들어 효율적으로 사용
        interviewer_names = {i['name'] for i in interviewers_res.data}

        return render_template(
            'admin_dashboard.html',
            events=events_res.data,
            all_members=members_res.data,
            interviewer_names=interviewer_names
        )
    except Exception as e:
        flash(f"대시보드 로딩 중 오류 발생: {e}", "danger")
        return render_template('admin_dashboard.html', events=[], all_members=[], interviewer_names=set())


# 2. 기존의 add_interviewer 와 delete_interviewer 함수 2개를 삭제하고,
#    아래의 새로운 toggle_interviewer 함수 1개로 교체합니다.
@app.route('/api/admin/toggle_interviewer', methods=['POST'])
@login_required(role="admin")
def toggle_interviewer():
    try:
        name_to_toggle = request.json.get('name')
        if not name_to_toggle:
            return jsonify({'status': 'error', 'message': '이름이 필요합니다.'}), 400

        # 해당 이름이 면접관 테이블에 이미 있는지 확인
        existing_interviewer = supabase.table('interviewers').select('id').eq('name', name_to_toggle).execute()

        # 이미 면접관이라면 -> 테이블에서 삭제
        if existing_interviewer.data:
            supabase.table('interviewers').delete().eq('name', name_to_toggle).execute()
            return jsonify({'status': 'removed', 'message': f"'{name_to_toggle}' 님을 면접관에서 제외했습니다."})

        # 면접관이 아니라면 -> 테이블에 추가
        else:
            # [수정] members 테이블에서 contact 정보를 가져오는 로직을 완전히 제거합니다.
            # interviewers 테이블의 contact 필드는 비워둔 채로(null) 추가됩니다.
            supabase.table('interviewers').insert({
                'name': name_to_toggle,
                'contact': None
            }).execute()
            return jsonify({'status': 'added', 'message': f"'{name_to_toggle}' 님을 면접관으로 추가했습니다."})

    except Exception as e:
        app.logger.error(f"Error toggling interviewer: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/admin/events/create', methods=['POST'])
@login_required(role="admin")
def create_event():
    try:
        form = request.form
        supabase.table('events').insert({'event_name': form.get('event_name'), 'start_date': form.get('start_date'),
                                         'end_date': form.get('end_date'),
                                         'is_active': form.get('is_active') == 'on'}).execute()
        flash('새로운 면접 이벤트가 성공적으로 생성되었습니다.', 'success')
    except Exception as e:
        flash(f"이벤트 생성 오류: {e}", "danger")
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/events/<event_id>')
@login_required(role="admin")
def manage_event(event_id):
    """
    [수정] 이벤트 정보와 함께, 이미 생성된 슬롯들의 요약 정보도 함께 불러옵니다.
    """
    try:
        event_res = supabase.table('events').select('*').eq('id', event_id).single().execute()

        # 해당 이벤트에 이미 생성된 슬롯들을 날짜별로 카운트합니다.
        # Supabase에서는 직접적인 GROUP BY와 COUNT를 RPC(DB 함수)로 구현하는 것이 가장 효율적입니다.
        # 여기서는 Python에서 처리하는 간단한 방식을 사용합니다.
        slots_res = supabase.table('time_slots').select('slot_datetime').eq('event_id', event_id).execute()

        slots_summary = {}
        if slots_res.data:
            for slot in slots_res.data:
                # KST 기준으로 날짜 키 생성
                kst_dt = datetime.fromisoformat(slot['slot_datetime'].replace('Z', '+00:00')) + timedelta(hours=9)
                date_key = kst_dt.strftime('%Y-%m-%d')
                slots_summary[date_key] = slots_summary.get(date_key, 0) + 1

        return render_template('admin_event_manage.html', event=event_res.data, slots_summary=slots_summary)
    except Exception as e:
        flash(f"이벤트 정보를 불러오는 중 오류 발생: {e}", "danger")
        return redirect(url_for('admin_dashboard'))


@app.route('/admin/events/<event_id>/timetable')
@login_required(role="admin")
def admin_event_timetable(event_id):
    try:
        event_res = supabase.table('events').select('event_name').eq('id', event_id).single().execute()
        # [추가] 모든 면접관의 목록을 불러옵니다.
        interviewers_res = supabase.table('interviewers').select('id, name').order('name').execute()

        return render_template(
            'timetable_view.html',
            event=event_res.data,
            event_id=event_id,
            user_role=session['user_role'],
            # [추가] 템플릿으로 면접관 목록 전달
            all_interviewers=interviewers_res.data
        )
    except Exception as e:
        flash(f"타임테이블 로딩 오류: {e}", "danger")
        return redirect(url_for('admin_dashboard'))


@app.route('/admin/events/<event_id>/generate_slots', methods=['POST'])
@login_required(role="admin")
def generate_slots(event_id):
    """
    [수정] 주말에도 면접 날짜를 생성할 수 있도록 요일 확인 로직을 제거합니다.
    """
    try:
        form = request.form
        start_date = datetime.strptime(form.get('start_date'), '%Y-%m-%d').date()
        end_date = datetime.strptime(form.get('end_date'), '%Y-%m-%d').date()
        start_time = datetime.strptime(form.get('start_time'), '%H:%M').time()
        end_time = datetime.strptime(form.get('end_time'), '%H:%M').time()

        KST = timezone(timedelta(hours=9))
        slots_to_insert = []
        current_date = start_date

        while current_date <= end_date:
            # [수정] 주말을 확인하는 if 문을 제거하여 모든 요일에 슬롯이 생성되도록 합니다.
            current_dt_naive = datetime.combine(current_date, start_time)
            end_dt_naive = datetime.combine(current_date, end_time)

            while current_dt_naive < end_dt_naive:
                aware_dt_kst = current_dt_naive.replace(tzinfo=KST)
                slots_to_insert.append({
                    'event_id': event_id,
                    'slot_datetime': aware_dt_kst.isoformat()
                })
                current_dt_naive += timedelta(minutes=15)

            current_date += timedelta(days=1)

        if slots_to_insert:
            supabase.table('time_slots').insert(slots_to_insert).execute()
            flash(f"{len(slots_to_insert)}개의 시간 슬롯이 성공적으로 생성되었습니다.", 'success')
        else:
            # [수정] 안내 메시지를 변경했습니다.
            flash("생성된 시간 슬롯이 없습니다. 날짜나 시간을 다시 확인해주세요.", 'warning')

    except Exception as e:
        flash(f"슬롯 생성 중 오류 발생: {e}", "danger")

    return redirect(url_for('manage_event', event_id=event_id))


@app.route('/api/events/<event_id>/timetable_data')
@login_required()
def get_timetable_data(event_id):
    """[수정] 여러 명의 면접관 이름을 모두 가져와서 조합합니다."""
    try:
        slots_res = supabase.table('time_slots').select('*').eq('event_id', event_id).order(
            'slot_datetime').execute().data
        all_interviewer_ids = set()
        for s in slots_res:
            if s.get('interviewer_ids'):
                all_interviewer_ids.update(s['interviewer_ids'])

        booked_slot_ids = [s['id'] for s in slots_res if s['is_booked']]
        reservations_data = supabase.table('reservations').select('slot_id, applicant_id').in_('slot_id',
                                                                                               booked_slot_ids).execute().data if booked_slot_ids else []
        applicant_ids = {r['applicant_id'] for r in reservations_data}
        applicants_data = supabase.table('applicants').select('*').in_('id', list(
            applicant_ids)).execute().data if applicant_ids else []
        interviewers_data = supabase.table('interviewers').select('id, name').in_('id', list(
            all_interviewer_ids)).execute().data if all_interviewer_ids else []
        applicants_map = {a['id']: a for a in applicants_data}
        interviewers_map = {i['id']: i['name'] for i in interviewers_data}
        reservation_map = {r['slot_id']: r['applicant_id'] for r in reservations_data}

        for slot in slots_res:
            if slot.get('slot_datetime'):
                slot['time_display'] = format_datetime_filter(slot['slot_datetime'], format_str="%p %I:%M")
            if slot.get('interviewer_ids'):
                slot['interviewer_names'] = ', '.join(
                    [interviewers_map.get(i_id, "알 수 없음") for i_id in slot['interviewer_ids']])
            if slot['id'] in reservation_map:
                slot['applicant'] = applicants_map.get(reservation_map[slot['id']])
        return jsonify(slots_res)
    except Exception as e:
        app.logger.error(f"Error getting timetable data: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/admin/slots/<slot_id>/toggle_active', methods=['POST'])
@login_required(role="admin")
def toggle_slot_active(slot_id):
    try:
        is_active = request.json.get('is_active')
        supabase.table('time_slots').update({'is_active': is_active}).eq('id', slot_id).execute()
        return jsonify({'status': 'success', 'message': '상태가 변경되었습니다.'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/admin/reservations/<slot_id>/cancel', methods=['POST'])
@login_required(role="admin")
def cancel_reservation(slot_id):
    """관리자가 예약을 취소하는 API"""
    try:
        # 예약 테이블에서 해당 슬롯 ID의 예약을 삭제합니다.
        supabase.table('reservations').delete().eq('slot_id', slot_id).execute()
        # 시간 슬롯 테이블에서 is_booked 상태를 false로 되돌립니다.
        supabase.table('time_slots').update({'is_booked': False}).eq('id', slot_id).execute()

        return jsonify({'status': 'success', 'message': '예약이 성공적으로 취소되었습니다.'})
    except Exception as e:
        app.logger.error(f"Error canceling reservation: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/admin/slots/<slot_id>/update_interviewers', methods=['POST'])
@login_required(role="admin")
def admin_update_interviewers(slot_id):
    """[신규] 관리자가 특정 슬롯의 면접관 목록 전체를 업데이트하는 API"""
    try:
        interviewer_ids = request.json.get('interviewer_ids', [])
        update_data = {'interviewer_ids': interviewer_ids if interviewer_ids else None}
        supabase.table('time_slots').update(update_data).eq('id', slot_id).execute()
        return jsonify({'status': 'success', 'message': '면접관이 성공적으로 업데이트되었습니다.'})
    except Exception as e:
        app.logger.error(f"Error updating interviewers by admin: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/admin/events/<event_id>/toggle_active', methods=['POST'])
@login_required(role="admin")
def toggle_event_active(event_id):
    """관리자가 이벤트의 활성/비활성 상태를 변경하는 API"""
    try:
        is_active = request.json.get('is_active')
        supabase.table('events').update({'is_active': is_active}).eq('id', event_id).execute()
        return jsonify({'status': 'success', 'message': '이벤트 상태가 변경되었습니다.'})
    except Exception as e:
        app.logger.error(f"Error toggling event active status: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/admin/events/<event_id>/delete', methods=['POST'])
@login_required(role="admin")
def delete_event(event_id):
    """관리자가 이벤트를 삭제하는 API"""
    try:
        # 이벤트에 속한 슬롯들을 먼저 조회합니다.
        slots_to_delete_res = supabase.table('time_slots').select('id').eq('event_id', event_id).execute()

        # 슬롯이 존재하면, 해당 슬롯들과 연결된 예약들을 먼저 삭제합니다.
        if slots_to_delete_res.data:
            slot_ids = [slot['id'] for slot in slots_to_delete_res.data]
            supabase.table('reservations').delete().in_('slot_id', slot_ids).execute()

        # 이제 이벤트를 삭제합니다. DB 설정(ON DELETE CASCADE)에 따라 관련 슬롯들도 함께 삭제됩니다.
        supabase.table('events').delete().eq('id', event_id).execute()

        return jsonify({'status': 'success', 'message': '이벤트가 성공적으로 삭제되었습니다.'})
    except Exception as e:
        app.logger.error(f"Error deleting event: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


# --- 4.2. 독서 모임 조 편성 (관리자 전용) ---
def gender_balance_score(group, members):
    m = sum(1 for name in group if members.get(name, {}).get('gender') == 'M')
    f = sum(1 for name in group if members.get(name, {}).get('gender') == 'F')
    return -abs(m - f)


def preference_score(group, members):
    score = 0
    for a, b in itertools.permutations(group, 2):
        preferred_list = members.get(a, {}).get('preferred') or []
        avoided_list = members.get(a, {}).get('avoided') or []
        if b in preferred_list: score += 2
        if b in avoided_list: score -= 3
    return score


def history_score(group, co_matrix):
    score = 0
    for a, b in itertools.combinations(group, 2):
        key = '-'.join(sorted([a, b]))
        entry = co_matrix.get(key)
        if entry: score -= entry['count']
    return score


def generate_groups(participants, facilitators, members, co_matrix, group_count_override=None, group_size_range=(3, 5),
                    top_n=5):
    total = len(participants := participants.copy())
    min_size, max_size = group_size_range
    if total == 0: return []
    min_groups = math.ceil(total / max_size) if max_size > 0 else 1
    max_groups = total // min_size if min_size > 0 else 1
    if group_count_override is not None:
        group_count = group_count_override
    else:
        group_count = min(max(min_groups, len(facilitators)), max_groups)
    if group_count <= 0: group_count = min_groups if min_groups > 0 else 1
    if group_count == 0: return []
    base, extra = divmod(total, group_count)
    sizes = [base + 1] * extra + [base] * (group_count - extra)
    suggestions = []
    for _ in range(top_n * 2):
        random.shuffle(participants)
        groups = [[] for _ in range(group_count)]
        [groups[i].append(fac) for i, fac in enumerate(facilitators) if i < group_count]
        remaining = [p for p in participants if p not in facilitators]
        for person in remaining:
            best_inc, best_i = None, None
            for i, grp in enumerate(groups):
                if len(grp) < sizes[i]:
                    curr = (gender_balance_score(grp, members) + preference_score(grp, members) + history_score(grp,
                                                                                                                co_matrix))
                    new_grp = grp + [person]
                    new = (gender_balance_score(new_grp, members) + preference_score(new_grp, members) + history_score(
                        new_grp, co_matrix))
                    inc = new - curr
                    if best_inc is None or inc > best_inc: best_inc, best_i = inc, i
            if best_i is None:
                for i, grp in enumerate(groups):
                    if len(grp) < sizes[i]: best_i = i; break
                if best_i is None: best_i = 0
            groups[best_i].append(person)
        total_score = sum(
            gender_balance_score(g, members) + preference_score(g, members) + history_score(g, co_matrix) for g in
            groups)
        suggestions.append((total_score, groups))
    suggestions.sort(key=lambda x: x[0], reverse=True)
    return [g for _, g in suggestions[:top_n]]


@app.route('/making_team', methods=['GET', 'POST'])
@login_required(role="admin")
def bookclub_index():
    try:
        members_response = supabase.table("members").select("*").order("name").execute()
        members_list = members_response.data
    except Exception as e:
        app.logger.error(f"Error fetching members: {e}")
        return "<h3>회원 정보를 불러오는 중 오류가 발생했습니다.</h3>", 500
    if request.method == 'POST':
        present = request.form.getlist('present')
        facilitators = request.form.getlist('facilitators')
        raw = (request.form.get('group_count') or '').strip()
        try:
            gc = int(raw)
            group_count_override = gc if gc > 0 else None
        except ValueError:
            group_count_override = None
        raw_names = request.form.get('group_names') or ''
        group_names = [n.strip() for n in raw_names.split(',') if n.strip()]
        members_dict = {m['name']: m for m in members_list}
        try:
            co_matrix_response = supabase.table("bookclub_co_matrix").select("*").execute()
            co_matrix = {item['pair_key']: item for item in co_matrix_response.data}
        except Exception as e:
            app.logger.error(f"Error fetching co_matrix: {e}")
            co_matrix = {}
        suggestions = generate_groups(present, facilitators, members_dict, co_matrix,
                                      group_count_override=group_count_override)
        return render_template('bookclub_results.html', suggestions=suggestions, present=present,
                               facilitators=facilitators, group_names=group_names)
    return render_template('bookclub_index.html', members=members_list)


@app.route('/api/bookclub/save', methods=['POST'])
@login_required(role="admin")
def bookclub_save():
    data = request.json
    try:
        record = {"date": data["date"], "present": data["present"], "facilitators": data["facilitators"],
                  "groups": data["groups"]}
        supabase.table("history").insert(record).execute()
        today = data['date']
        keys_to_update = {}
        for g in data['groups']:
            for a, b in itertools.combinations(g, 2):
                key = '-'.join(sorted([a, b]))
                keys_to_update[key] = keys_to_update.get(key, 0) + 1
        if keys_to_update:
            keys_to_fetch = list(keys_to_update.keys())
            matrix_res = supabase.table('bookclub_co_matrix').select('pair_key, count').in_('pair_key',
                                                                                            keys_to_fetch).execute()
            current_counts = {item['pair_key']: item['count'] for item in matrix_res.data}
            final_upsert_data = []
            for key, increment in keys_to_update.items():
                current_count = current_counts.get(key, 0)
                final_upsert_data.append({"pair_key": key, "count": current_count + increment, "last_met": today})
            supabase.table("bookclub_co_matrix").upsert(final_upsert_data).execute()
        return jsonify({'status': 'ok'})
    except Exception as e:
        app.logger.error(f"Error saving bookclub data: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/bookclub/history', methods=['GET'])
@login_required(role="admin")
def bookclub_api_get_history():
    response = supabase.table("history").select("*").order("date", desc=True).execute()
    return jsonify(response.data)


@app.route('/api/bookclub/history/delete', methods=['POST'])
@login_required(role="admin")
def bookclub_api_delete_history():
    idx = request.json.get("index")
    response = supabase.table("history").select("id").order("date", desc=True).execute()
    records = response.data
    if isinstance(idx, int) and 0 <= idx < len(records):
        record_id = records[idx]["id"]
        supabase.table("history").delete().eq("id", record_id).execute()
        return jsonify({"status": "ok"})
    return jsonify({"status": "error", "message": "Invalid index"}), 400


# ==============================================================================
# --- 5. 면접관 (Interviewer) 전용 기능 ---
# ==============================================================================
@app.route('/interviewer/events')
@login_required(role="interviewer")
def interviewer_events_list():
    try:
        events_res = supabase.table('events').select('*').eq('is_active', True).order('created_at', desc=True).execute()
        return render_template('interviewer_events_list.html', events=events_res.data)
    except Exception as e:
        flash(f"이벤트 목록 로딩 오류: {e}", "danger")
        return render_template('interviewer_events_list.html', events=[])


@app.route('/interviewer/events/<event_id>/timetable')
@login_required(role="interviewer")
def interviewer_event_timetable(event_id):
    try:
        event_res = supabase.table('events').select('event_name').eq('id', event_id).single().execute()
        return render_template('timetable_view.html', event=event_res.data, event_id=event_id,
                               user_role=session['user_role'])
    except Exception as e:
        flash(f"타임테이블 로딩 오류: {e}", "danger")
        return redirect(url_for('interviewer_events_list'))


@app.route('/api/interviewer/slots/<slot_id>/assign', methods=['POST'])
@login_required(role="interviewer")
def assign_interviewer_to_slot(slot_id):
    """[수정] 한 슬롯에 여러 면접관이 참여할 수 있도록, 배열에 자신의 ID를 추가합니다."""
    try:
        interviewer_name = session.get('user_name')
        interviewer_res = supabase.table('interviewers').select('id').eq('name', interviewer_name).execute()
        if not interviewer_res.data:
            return jsonify({'status': 'error', 'message': '등록된 면접관 정보가 없습니다.'}), 404

        interviewer_id = interviewer_res.data[0]['id']

        slot_res = supabase.table('time_slots').select('interviewer_ids').eq('id', slot_id).single().execute()
        current_ids = slot_res.data.get('interviewer_ids') or []

        if interviewer_id in current_ids:
            return jsonify({'status': 'error', 'message': '이미 이 시간에 배정되어 있습니다.'}), 409

        new_ids = current_ids + [interviewer_id]
        supabase.table('time_slots').update({'interviewer_ids': new_ids}).eq('id', slot_id).execute()
        return jsonify({'status': 'success', 'message': '성공적으로 배정되었습니다.'})
    except Exception as e:
        app.logger.error(f"Error assigning interviewer: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


# ==============================================================================
# --- 6. 면접자 (Applicant) 전용 기능 ---
# ==============================================================================
@app.route('/interview')
@login_required(role="applicant")
def interview_index():
    """
    [수정] 활성화된 이벤트가 없어도 오류 없이 페이지를 보여주고,
    템플릿 내에서 이벤트 존재 여부를 판단하도록 변경합니다.
    """
    try:
        active_events = supabase.table('events').select('id, event_name').eq('is_active', True).order(
            'start_date').execute().data

        # 활성화된 이벤트가 있으면 첫 번째 이벤트를, 없으면 None을 전달합니다.
        event = active_events[0] if active_events else None

        return render_template('interview_applicant_view.html', event=event, user_name=session.get('user_name'),
                               user_phone=session.get('user_phone'))
    except Exception as e:
        app.logger.error(f"Error fetching event for applicant: {e}")
        flash(f"페이지 로딩 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요.", "danger")
        # 오류 발생 시에도 템플릿은 렌더링하되, event는 None으로 전달하여 오류 메시지를 표시하게 합니다.
        return render_template('interview_applicant_view.html', event=None, user_name=session.get('user_name'),
                               user_phone=session.get('user_phone'))


@app.route('/api/interview/events/<event_id>/slots', methods=['GET'])
@login_required()
def interview_get_slots(event_id):
    """
    [최종 수정] 면접자 페이지의 시간 표시 오류를 해결하기 위해,
    잘못된 시간 계산(+ timedelta) 대신 올바른 시간대 변환(astimezone)을 사용합니다.
    """
    try:
        response = supabase.table('time_slots').select('*').eq('event_id', event_id).eq('is_active', True).order(
            'slot_datetime', desc=False).execute()

        # supabase-py v1, v2 라이브러리 호환성 확보
        slots_data = response.data if hasattr(response, 'data') else response

        slots_by_date = {}

        # 한국 시간대(KST, UTC+9)를 명확하게 정의합니다.
        KST = timezone(timedelta(hours=9))

        for slot in slots_data:
            if not slot.get('slot_datetime'):
                continue

            # 데이터베이스에서 가져온 UTC 시간 문자열을 datetime 객체로 변환
            utc_dt = datetime.fromisoformat(slot['slot_datetime'].replace('Z', '+00:00'))

            # UTC 시간을 KST 시간으로 정확하게 변환
            kst_dt = utc_dt.astimezone(KST)

            # [핵심] 표시용 시간과 날짜 키를 모두 KST 기준으로 생성합니다.
            slot['time_display'] = kst_dt.strftime("%p %I:%M").replace("AM", "오전").replace("PM", "오후")
            date_key = kst_dt.strftime("%Y-%m-%d")

            if date_key not in slots_by_date:
                slots_by_date[date_key] = []

            slots_by_date[date_key].append(slot)

        return jsonify(slots_by_date)
    except Exception as e:
        app.logger.error(f"Error fetching slots for applicant: {e}")
        return jsonify({"error": "슬롯 정보를 가져오는 중 서버 오류가 발생했습니다."}), 500


@app.route('/api/interview/reservations', methods=['POST'])
@login_required(role="applicant")
def interview_create_reservation():
    data = request.get_json()
    name, phone, slot_id = data.get('name'), data.get('phone_number'), data.get('slot_id')
    if not all([name, phone, slot_id]): return jsonify({"error": "필수 정보가 누락되었습니다."}), 400

    try:
        # 예약 처리를 위한 정보 조회
        slot_response = supabase.table('time_slots').select('is_booked, is_active, slot_datetime, event_id').eq('id',
                                                                                                                slot_id).single().execute().data
        if not slot_response.get('is_active'): return jsonify({"error": "선택한 시간은 예약이 불가능합니다."}), 409
        if slot_response.get('is_booked'): return jsonify({"error": "다른 사용자가 방금 예약했습니다."}), 409

        applicant_res = supabase.table('applicants').select('id').eq('phone_number', phone).execute().data
        if applicant_res:
            applicant_id = applicant_res[0]['id']
            existing_reservation = supabase.table('reservations').select('id').eq('applicant_id', applicant_id).eq(
                'is_cancelled', False).execute().data
            if existing_reservation:
                return jsonify({"error": "이미 예약된 면접이 있습니다. 변경하시려면 관리자에게 문의해주세요."}), 409
            supabase.table('applicants').update({'name': name}).eq('id', applicant_id).execute()
        else:
            applicant_id = supabase.table('applicants').insert({'name': name, 'phone_number': phone}).execute().data[0][
                'id']

        supabase.table('reservations').insert({'slot_id': slot_id, 'applicant_id': applicant_id}).execute()
        supabase.table('time_slots').update({'is_booked': True}).eq('id', slot_id).execute()

        # [추가] 예약 성공 후 관리자에게 텔레그램 알림 발송
        try:
            event_res = supabase.table('events').select('event_name').eq('id', slot_response[
                'event_id']).single().execute().data
            event_name = event_res['event_name']
            reserved_time_str = format_datetime_filter(slot_response['slot_datetime'])

            # 텔레그램 메시지 내용 구성
            message = (
                f"🔔 *신규 면접 예약 알림*\n\n"
                f"새로운 면접 예약이 등록되었습니다.\n\n"
                f"*{event_name}*\n"
                f"--------------------\n"
                f"▪️ *예약자*: {name}\n"
                f"▪️ *연락처*: {phone}\n"
                f"▪️ *예약시간*: {reserved_time_str}"
            )
            send_telegram_notification(message)

        except Exception as e:
            app.logger.error(f"예약 후 텔레그램 알림 발송 중 오류 발생: {e}")

        return jsonify({"message": "예약이 성공적으로 완료되었습니다."}), 201

    except Exception as e:
        app.logger.error(f"Error creating reservation: {e}")
        return jsonify({"error": "예약 처리 중 오류가 발생했습니다."}), 500


@app.route('/api/interview/reservations/check', methods=['GET'])
@login_required(role="applicant")
def interview_check_reservation():
    phone = request.args.get('phone_number')
    if not phone:
        return jsonify({"error": "연락처가 필요합니다."}), 400

    try:
        # 1. 연락처로 applicant 찾기
        applicant_res = supabase.table('applicants').select('id, name').eq('phone_number', phone).single().execute()

        applicant_id = applicant_res.data['id']
        applicant_name = applicant_res.data['name']

        # 2. applicant_id로 예약 정보 찾기 (취소되지 않은 것)
        reservation_res = supabase.table('reservations').select('slot_id').eq('applicant_id', applicant_id).eq(
            'is_cancelled', False).single().execute()

        slot_id = reservation_res.data['slot_id']

        # 3. slot_id로 시간 정보와 이벤트 ID 찾기
        slot_res = supabase.table('time_slots').select('slot_datetime, event_id').eq('id', slot_id).single().execute()

        # 4. event_id로 이벤트 이름 찾기
        event_res = supabase.table('events').select('event_name').eq('id', slot_res.data['event_id']).single().execute()

        result = {
            "applicant_name": applicant_name,
            "event_name": event_res.data['event_name'],
            "slot_datetime": slot_res.data['slot_datetime']
        }

        return jsonify(result)
    except Exception as e:
        # .single()은 결과가 없으면 오류를 발생시키므로, 이는 예약이 없다는 자연스러운 상태입니다.
        app.logger.debug(f"Reservation check for {phone} found no data: {e}")
        return jsonify({"error": "예약 정보를 찾을 수 없습니다."}), 404

# ==============================================================================
# --- 7. 서버 실행 ---
# ==============================================================================
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
