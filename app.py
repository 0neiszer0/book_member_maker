# app.py
# 모든 기능이 통합된 최종 버전의 Flask 애플리케이션 코드입니다.

# --- 1. 기본 라이브러리 및 설정 ---
import os
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'
import itertools
import random
import math
from dotenv import load_dotenv
from flask import Flask, render_template, request, jsonify, session, redirect, url_for, flash, Response
import json
from supabase import create_client, Client
from datetime import datetime, timedelta, timezone
from functools import wraps
import requests
import re
import pandas as pd
import numpy as np
from deap import base, creator, tools, algorithms
import uuid
import mwparserfromhell
import bleach

# .env 파일에서 환경 변수 로드
load_dotenv()

# Flask 앱 초기화 및 시크릿 키 설정
app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY")
if not app.secret_key:
    raise ValueError("FLASK_SECRET_KEY가 .env 파일에 설정되지 않았습니다.")

# Supabase 클라이언트 초기화
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY")
if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("Supabase URL과 Key가 .env 파일에 설정되지 않았습니다.")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)


# ==============================================================================
# --- 2. 헬퍼 함수 및 공용 시스템 ---
# ==============================================================================

# app.py 의 wiki_parser 함수를 아래 코드로 교체

def wiki_parser(wiki_text):
    """
    mwparserfromhell 라이브러리를 사용해 위키 텍스트를 안전한 HTML로 변환합니다.
    """
    if not wiki_text:
        return ""

    # 1. mwparserfromhell을 사용해 위키 텍스트를 파싱합니다.
    wikicode = mwparserfromhell.parse(wiki_text)

    # 2. 파싱된 코드를 HTML로 변환합니다.
    #    (strip_code는 태그 등을 제거하지만, 기본 HTML 변환에 사용될 수 있습니다.
    #     또는 to_html과 같은 커스텀 변환기를 만들 수도 있습니다.)
    #    여기서는 간단하게 문자열로 변환하여 기본 태그를 유지합니다.
    html = str(wikicode)

    # mwparserfromhell은 [[링크]] 등을 <wikilink> 같은 커스텀 태그로 만들 수 있으나,
    # 여기서는 간단한 문자열 치환으로 링크를 변환합니다.
    # (더 복잡한 변환은 mwparserfromhell의 node 탐색 기능을 사용해야 합니다)

    # 간단한 정규식으로 링크와 강조 등 기본 문법을 HTML 태그로 변환
    # (mwparserfromhell이 구조를 잡아주고, 세부 렌더링은 정규식으로 보완)
    html = re.sub(r"'''(.*?)'''", r'<strong>\1</strong>', html)
    html = re.sub(r"''(.*?)''", r'<em>\1</em>', html)
    html = re.sub(r'\[\[([^\]|]+?)\|([^\]]+?)\]\]', r'<a href="/docs/\1" class="wiki-link">\2</a>', html)
    html = re.sub(r'\[\[([^\]]+?)\]\]', r'<a href="/docs/\1" class="wiki-link">\1</a>', html)
    html = re.sub(r'\[(https?://\S+?)\s+([^\]]+?)\]', r'<a href="\1" target="_blank" rel="noopener noreferrer">\2</a>',
                  html)
    html = re.sub(r'==\s*(.*?)\s*==', r'<h2>\1</h2>', html, flags=re.MULTILINE)

    # 3. 보안을 위해 허용할 태그와 속성을 지정하여 Sanitize 처리
    allowed_tags = {
        'p', 'br', 'strong', 'em', 's', 'blockquote', 'hr',
        'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
        'ul', 'ol', 'li',
        'table', 'thead', 'tbody', 'tr', 'th', 'td',
        'pre', 'code', 'img', 'a', 'div'
    }
    allowed_attrs = {
        '*': ['class', 'align'],
        'img': ['src', 'alt', 'title'],
        'a': ['href', 'title', 'target', 'rel', 'class'],
    }

    safe_html = bleach.clean(html, tags=allowed_tags, attributes=allowed_attrs, strip=True)
    return safe_html


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

# 2. 생성한 함수를 Jinja2 필터로 등록
app.jinja_env.filters['wiki_to_html'] = wiki_parser
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

def get_next_monday():
    """오늘을 기준으로 다음 돌아오는 월요일의 날짜를 계산합니다."""
    today = datetime.now(timezone(timedelta(hours=9))).date()
    # today.weekday()는 월요일=0, 일요일=6
    days_until_monday = (0 - today.weekday() + 7) % 7
    if days_until_monday == 0: # 오늘이 월요일이면 다음 주 월요일을 대상으로 함
        days_until_monday = 7
    return today + timedelta(days=days_until_monday)


# ==============================================================================
# --- 3. 로그인, 로그아웃, 메인 페이지 라우트 ---
# ==============================================================================

# [신규] 가장 기본이 되는 메인 페이지 라우트를 추가합니다.
@app.route('/')
def main_index():
    # --- [수정] D-데이 계산 로직 추가 ---
    try:
        # 모집 마감일을 설정합니다. (년, 월, 일)
        end_date_str = "2025-08-31"
        # templates/main_index.html 파일의 모집 기간 마지막 날짜와 일치시킵니다.
        end_date = datetime.strptime(end_date_str, "%Y-%m-%d")

        # 오늘 날짜를 가져옵니다.
        today = datetime.now()

        # 남은 날짜(D-데이)를 계산합니다.
        # 날짜만 비교하기 위해 .date()를 사용합니다.
        delta = end_date.date() - today.date()
        d_day = delta.days
    except Exception as e:
        app.logger.error(f"D-day calculation error: {e}")
        d_day = -1  # 오류 발생 시 기간이 지난 것으로 처리

    # 계산된 d_day 값을 템플릿으로 전달합니다.
    return render_template('main_index.html', d_day=d_day)


class KakaoOauth:
    def __init__(self):
        self.client_id = os.environ.get("KAKAO_OAUTH_CLIENT_ID")
        self.redirect_uri = os.environ.get("KAKAO_REDIRECT_URI")
        self.token_url = "https://kauth.kakao.com/oauth/token"
        self.user_info_url = "https://kapi.kakao.com/v2/user/me"

    def get_token(self, code):
        """인가 코드로 Access Token을 요청합니다."""
        data = {
            "grant_type": "authorization_code",
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "code": code,
        }
        # [수정] Client Secret을 활성화했으므로, 이 줄의 주석을 반드시 해제하고 값을 추가합니다.
        if os.environ.get("KAKAO_OAUTH_CLIENT_SECRET"):
            data["client_secret"] = os.environ.get("KAKAO_OAUTH_CLIENT_SECRET")

        response = requests.post(self.token_url, data=data)
        response.raise_for_status()  # 오류 발생 시 예외 발생
        return response.json()

    def get_user_info(self, access_token):
        """Access Token으로 사용자 정보를 요청합니다."""
        headers = {"Authorization": f"Bearer {access_token}"}
        response = requests.post(self.user_info_url, headers=headers)
        response.raise_for_status()
        return response.json()


# --- 기존 로그인 라우트들을 아래 코드로 교체합니다 ---

@app.route('/login')
def login():
    # 이 페이지는 이제 카카오 로그인 버튼만 보여줍니다.
    return render_template('login.html')


# 1. 로그인 시작 라우트
@app.route('/login/kakao')
def kakao_login():
    kakao_oauth = KakaoOauth()
    # 사용자를 카카오 인증 페이지로 리디렉션합니다.
    login_url = f"https://kauth.kakao.com/oauth/authorize?client_id={kakao_oauth.client_id}&redirect_uri={kakao_oauth.redirect_uri}&response_type=code"

    # [수정] 로그인 후 돌아올 목적지를 세션에 저장합니다.
    session['next_url'] = request.args.get('next')

    return redirect(login_url)


# 2. 로그인 후 콜백을 처리할 라우트
@app.route('/login/kakao/callback')
def kakao_callback():
    try:
        code = request.args.get("code")
        if not code:
            flash("인증 코드를 받는데 실패했습니다.", "danger")
            return redirect(url_for("login"))

        kakao_oauth = KakaoOauth()
        # 인가 코드로 토큰 발급
        token_info = kakao_oauth.get_token(code)
        access_token = token_info.get("access_token")

        # 토큰으로 사용자 정보 조회
        user_info = kakao_oauth.get_user_info(access_token)

        social_id = str(user_info["id"])
        kakao_account = user_info.get("kakao_account", {})
        profile = kakao_account.get("profile", {})
        email = kakao_account.get("email")

        # 기존 회원인지 확인
        member_res = supabase.table("members").select("*").eq("social_id", social_id).execute()
        member = member_res.data[0] if member_res.data else None

        if member:
            # [추가] 계정 상태 확인
            if member.get('account_status') != 'active':
                flash("아직 관리자의 승인을 받지 않은 계정입니다.", "warning")
                return redirect(url_for('login'))

            if not member.get('is_active', True):  # is_active가 false이면
                flash("비활성화된 계정입니다. 관리자에게 문의하세요.", "danger")
                return redirect(url_for('login'))  # 세션을 만들지 않고 로그인 페이지로 돌려보냄
            # 아래는 기존의 세션 설정 및 리디렉션 로직
            pass
        else:
            # 연동되지 않았으면, '계정 연결' 페이지로 보낼 정보 준비
            social_data = {
                "social_id": social_id, "email": email,
                "social_name": profile.get("nickname"), "profile_pic": profile.get("profile_image_url")
            }
            session['temp_social_data'] = social_data
            return redirect(url_for('link_account_page'))

        # 세션 설정
        session["user_id"] = member["id"]
        session["user_role"] = member["role"]
        session["user_name"] = member["name"]
        flash(f"{member['name']}님, 환영합니다!", "success")

        # 원래 가려던 목적지로 리디렉션
        next_url = session.pop('next_url', None)
        if next_url:
            return redirect(next_url)
        if member["role"] == "admin":
            return redirect(url_for("admin_dashboard"))
        return redirect(url_for("main_index"))

    except Exception as e:
        flash("카카오 로그인 중 오류가 발생했습니다.", "danger")
        app.logger.error(f"Kakao callback error: {e}", exc_info=True)
        return redirect(url_for("login"))


@app.route('/link_account')
def link_account_page():
    # kakao_callback에서 임시 저장한 소셜 데이터가 없으면 로그인 페이지로
    if 'temp_social_data' not in session:
        return redirect(url_for('login'))
    return render_template('link_account.html', **session['temp_social_data'])


@app.route('/link_account', methods=['POST'])
def link_account_submit():
    if 'temp_social_data' not in session:
        return redirect(url_for('login'))

    form = request.form
    action = form.get('action')
    social_info = session['temp_social_data']

    member = None
    if action == 'link':
        existing_name = form.get('existing_name')
        if not existing_name:
            flash("기존 활동명을 입력해주세요.", "danger")
            return redirect(url_for('link_account_page'))

        member_res = supabase.table("members").select("*").eq("name", existing_name).is_("social_id", None).execute()
        member_to_link = member_res.data[0] if member_res.data else None

        if member_to_link:
            update_data = {
                "social_id": social_info['social_id'],
                "email": social_info['email'],
                "profile_pic": social_info['profile_pic'],
                "account_status": 'pending'
            }
            # [수정] .update() 뒤에 .select()를 제거하고, 실행 결과에서 바로 .data를 사용합니다.
            updated_member_response = supabase.table("members").update(update_data).eq("id",
                                                                                       member_to_link['id']).execute()
            member = updated_member_response.data[0]

            # notifications 테이블에 알림 생성
            supabase.table('notifications').insert({
                'type': 'account_link_request',
                'related_member_id': member['id'],
                'details': {
                    'original_name': member['name'],
                    'social_name': social_info['social_name'],
                    'social_email': social_info['email']
                }
            }).execute()

            flash("기존 계정 연결 요청이 완료되었습니다. 관리자 승인 후 로그인 가능합니다.", "success")
            return redirect(url_for('login'))
        else:
            flash("해당 이름의 기존 계정을 찾을 수 없습니다. 신규 회원으로 가입해주세요.", "danger")
            return redirect(url_for('link_account_page'))

    elif action == 'create':
        new_member_data = {
            "name": social_info['social_name'],
            "email": social_info['email'],
            "social_id": social_info['social_id'],
            "profile_pic": social_info['profile_pic'],
            "role": "member",
            "account_status": 'pending'
        }
        # [수정] .insert() 뒤에 .select()를 제거하고, 실행 결과에서 바로 .data를 사용합니다.
        new_member_response = supabase.table("members").insert(new_member_data).execute()
        member = new_member_response.data[0]

        # notifications 테이블에 알림 생성
        supabase.table('notifications').insert({
            'type': 'new_user_request',
            'related_member_id': member['id'],
            'details': {
                'name': member['name'],
                'email': member['email']
            }
        }).execute()

        flash("회원가입 요청이 완료되었습니다. 관리자 승인 후 활동 가능합니다.", "success")
        return redirect(url_for('login'))


# @app.route('/login', methods=['GET', 'POST'])
# def login():
#     if request.method == 'POST':
#         role = request.form.get('role')
#         password = request.form.get('password')
#         ADMIN_PASS = os.environ.get("ADMIN_PASSWORD")
#         INTERVIEWER_PASS = os.environ.get("INTERVIEWER_PASSWORD")
#         APPLICANT_PASS = os.environ.get("APPLICANT_PASSWORD")
#
#         # 역할 1: 관리자 로그인 (기존과 동일)
#         if role == 'admin' and password == ADMIN_PASS:
#             session.clear()
#             session['user_role'] = 'admin'
#             session['user_name'] = '관리자'
#             flash('관리자님, 환영합니다!', 'success')
#             return redirect(url_for('admin_dashboard'))
#
#         # 역할 2: 면접관 로그인
#         elif role == 'interviewer' and password == INTERVIEWER_PASS:
#             interviewer_name = request.form.get('name')
#             if not interviewer_name:
#                 flash('면접관 이름을 입력해주세요.', 'danger')
#                 return redirect(url_for('login'))
#
#             # [추가] 입력한 이름이 'members' 테이블에 존재하는지 확인합니다.
#             try:
#                 member_res = supabase.table('members').select('name').eq('name', interviewer_name).execute()
#                 if not member_res.data:
#                     flash('등록된 모임원이 아닙니다. 관리자에게 문의하세요.', 'danger')
#                     return redirect(url_for('login'))
#             except Exception as e:
#                 flash('사용자 확인 중 오류가 발생했습니다.', 'danger')
#                 app.logger.error(f"Error checking member: {e}")
#                 return redirect(url_for('login'))
#
#             session.clear()
#             session['user_role'] = 'interviewer'
#             session['user_name'] = interviewer_name
#             flash(f"{session['user_name']} 면접관님, 환영합니다!", 'success')
#             return redirect(url_for('interviewer_events_list'))
#
#         # 역할 3: 면접자 로그인
#         elif role == 'applicant' and password == APPLICANT_PASS:
#             name = request.form.get('name')
#             phone = request.form.get('phone_number')
#
#             # [추가] 이름과 전화번호 형식 유효성 검사
#             if not (name and phone):
#                 flash('이름과 연락처를 모두 입력해주세요.', 'danger')
#                 return redirect(url_for('login'))
#
#             if not re.match(r'^[가-힣]{2,4}$', name):
#                 flash('이름은 2~4자의 한글로 입력해주세요.', 'danger')
#                 return redirect(url_for('login'))
#
#             if not re.match(r'^\d{11}$', phone):
#                 flash('연락처는 11자리 숫자로 입력해주세요. (예: 01012345678)', 'danger')
#                 return redirect(url_for('login'))
#
#             session.clear()
#             session['user_role'] = 'applicant'
#             session['user_name'] = name
#             session['user_phone'] = phone
#             flash(f"{session['user_name']}님, 환영합니다!", 'success')
#             return redirect(url_for('interview_index'))
#
#         else:
#             flash('입력 정보가 올바르지 않습니다.', 'danger')
#
#     return render_template('login.html')


# --- [신규] 접근 키가 포함된 링크를 처리하는 라우트 ---
@app.route('/entry')
def quick_entry():
    # URL에서 key 파라미터 값을 가져옴 (예: /entry?key=hobanu-interview-2025-summer)
    access_key = request.args.get('key')

    # .env 파일에 저장된 키와 비교
    expected_key = os.environ.get('APPLICANT_ACCESS_KEY')

    if access_key == expected_key:
        # 키가 일치하면, 이름과 연락처만 입력하는 전용 페이지를 보여줌
        return render_template('applicant_entry.html')
    else:
        # 키가 없거나 일치하지 않으면, 일반 로그인 페이지로 리다이렉트
        flash('유효하지 않은 접근 링크입니다.', 'danger')
        return redirect(url_for('login'))


# --- [신규] 전용 입장 페이지에서 이름/연락처를 받아 처리하는 라우트 ---
@app.route('/process_entry', methods=['POST'])
def process_quick_entry():
    name = request.form.get('name')
    phone = request.form.get('phone_number')

    # 유효성 검사 (기존 로그인 로직과 동일)
    if not (name and phone):
        flash('이름과 연락처를 모두 입력해주세요.', 'danger')
        return redirect(url_for('quick_entry'))  # 오류 시 다시 입력 페이지로

    if not re.match(r'^[가-힣]{2,4}$', name) or not re.match(r'^\d{11}$', phone):
        flash('이름 또는 연락처 형식이 올바르지 않습니다.', 'danger')
        return redirect(url_for('quick_entry'))

    # 비밀번호 확인 없이 바로 세션에 정보 저장 (로그인 처리)
    session.clear()
    session['user_role'] = 'applicant'
    session['user_name'] = name
    session['user_phone'] = phone

    flash(f"{session['user_name']}님, 환영합니다!", 'success')
    return redirect(url_for('interview_index'))


# --- [신규] 관리자가 이벤트 공유 링크를 생성하는 API ---
@app.route('/api/admin/events/<event_id>/generate_share_link', methods=['POST'])
@login_required(role="admin")
def generate_share_link(event_id):
    try:
        # 1. 추측 불가능한 고유 토큰 생성
        token = str(uuid.uuid4())

        # 2. DB의 해당 이벤트에 토큰 저장
        supabase.table('events').update({'share_token': token}).eq('id', event_id).execute()

        # 3. 완성된 공유 링크를 반환
        link = f"{request.host_url}shared_timetable?token={token}"
        return jsonify({'status': 'success', 'link': link})
    except Exception as e:
        app.logger.error(f"Error generating share link for event {event_id}: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


# --- [신규] 로그인 없이 공유 링크로 타임테이블을 보는 라우트 ---
@app.route('/shared_timetable')
def view_shared_timetable():
    token = request.args.get('token')
    if not token:
        return "잘못된 접근입니다.", 400

    try:
        # 1. 토큰으로 이벤트를 검색
        res = supabase.table('events').select('id, event_name').eq('share_token', token).single().execute()
        event_data = res.data

        # 2. '읽기 전용' 모드임을 템플릿에 전달
        return render_template(
            'timetable_view.html',
            event=event_data,
            event_id=event_data['id'],
            user_role='guest',  # 사용자가 게스트임을 명시
            is_shared_view=True  # 읽기 전용 뷰임을 나타내는 플래그
        )
    except Exception as e:
        app.logger.error(f"Failed to load shared timetable with token {token}: {e}")
        return "유효하지 않은 링크이거나 만료되었습니다.", 404

@app.route('/logout')
def logout():
    session.clear()
    flash('성공적으로 로그아웃되었습니다.', 'info')
    return redirect(url_for('main_index'))


@app.route('/board')
@login_required(role="ANY")
def member_board():
    user_id = session.get('user_id')
    next_monday = get_next_monday()
    try:
        # [수정] status, drink_order 대신 attending_seminar, attending_afterparty 조회
        my_attendance_res = supabase.table('attendance').select('attending_seminar, attending_afterparty') \
            .eq('user_id', user_id).eq('meeting_date', next_monday.isoformat()).execute()
        my_attendance = my_attendance_res.data[0] if my_attendance_res.data else None

        questions_res = supabase.table('questions').select('*, members(name)').eq('meeting_date',
                                                                                  next_monday.isoformat()).order(
            'created_at').execute()
        all_questions = questions_res.data if questions_res.data else []

        # [수정] 세미나 참석자 명단만 조회 (뒷풀이 참석 여부도 함께 가져옴)
        attendees_res = supabase.table('attendance').select('user_id, attending_afterparty, members(name)') \
            .eq('meeting_date', next_monday.isoformat()).eq('attending_seminar', True).execute()
        attendees = attendees_res.data if attendees_res.data else []

    except Exception as e:
        flash(f"데이터를 불러오는 중 오류 발생: {e}", "danger")
        my_attendance, all_questions, attendees = None, [], []

    return render_template(
        'member_board.html',
        meeting_date=next_monday,
        my_attendance=my_attendance,
        questions=all_questions,
        attendees=attendees
    )


@app.route('/api/attendance', methods=['POST'])
@login_required(role="ANY")
def update_attendance():
    data = request.json
    user_id = session.get('user_id')
    next_monday = get_next_monday().isoformat()
    try:
        # [수정] status, drink_order 대신 attending_seminar, attending_afterparty 를 upsert
        supabase.table('attendance').upsert({
            'user_id': user_id,
            'meeting_date': next_monday,
            'attending_seminar': data.get('attending_seminar'),
            'attending_afterparty': data.get('attending_afterparty')
        }, on_conflict='user_id, meeting_date').execute()
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/questions', methods=['POST'])
@login_required(role="ANY")
def create_question():
    """JavaScript(fetch) 요청을 처리하는 API 라우트"""
    data = request.json
    user_id = session.get('user_id')
    try:
        new_question = supabase.table('questions').insert({
            'user_id': user_id,
            'meeting_date': get_next_monday().isoformat(),
            'content': data.get('content')
        }).execute().data[0]

        member_res = supabase.table('members').select('name').eq('id', user_id).execute().data[0]
        new_question['members'] = member_res

        return jsonify({"status": "success", "question": new_question})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/questions/<int:question_id>', methods=['PUT', 'DELETE'])
@login_required(role="ANY")
def manage_question(question_id):
    """JavaScript(fetch) 요청을 처리하는 API 라우트"""
    user_id = session.get('user_id')
    try:
        question_res = supabase.table('questions').select('user_id').eq('id', question_id).single().execute()
        if not question_res.data or question_res.data['user_id'] != user_id:
            return jsonify({"status": "error", "message": "권한이 없습니다."}), 403

        if request.method == 'PUT':
            content = request.json.get('content')
            supabase.table('questions').update({'content': content}).eq('id', question_id).execute()
            return jsonify({"status": "success", "message": "질문이 수정되었습니다."})
        elif request.method == 'DELETE':
            supabase.table('questions').delete().eq('id', question_id).execute()
            return jsonify({"status": "success", "message": "질문이 삭제되었습니다."})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/profiles')
@login_required(role="ANY")
def profiles_page():
    """모든 멤버의 프로필 목록을 보여주는 페이지"""
    try:
        all_members = supabase.table('members').select('*').eq('is_active', True).order('name').execute().data
    except Exception as e:
        flash(f"프로필 로딩 중 오류: {e}", "danger")
        all_members = []
    return render_template('profiles.html', all_members=all_members)


@app.route('/api/profiles/update', methods=['POST'])
@login_required(role="ANY")
def update_profile():
    """프로필의 '한 줄 소개'와 '상세 프로필(BBCode)'을 업데이트합니다."""
    user_id = session.get('user_id')
    data = request.json

    try:
        # 1. 클라이언트로부터 필요한 데이터만 추출합니다.
        update_data = {
            'profile_intro': data.get('intro'),
            'profile_content': data.get('content')  # BBCode 원문을 그대로 저장
        }

        # 2. 값이 없는 필드는 업데이트 대상에서 제외합니다.
        update_data = {k: v for k, v in update_data.items() if v is not None}

        # 3. 업데이트할 데이터가 없으면 오류를 반환합니다.
        if not update_data:
            return jsonify({"status": "error", "message": "전송된 데이터가 없습니다."}), 400

        # 4. 데이터베이스를 업데이트합니다.
        supabase.table('members').update(update_data).eq('id', user_id).execute()

        # 5. 프론트엔드가 페이지를 새로고침하므로 간단한 성공 메시지만 반환합니다.
        return jsonify({"status": "success", "message": "프로필이 저장되었습니다."})

    except Exception as e:
        app.logger.error(f"Profile update error: {e}", exc_info=True)
        return jsonify({"status": "error", "message": "프로필 저장 중 서버 오류가 발생했습니다."}), 500


@app.route('/profile/<int:member_id>')
@login_required(role="ANY")
def profile_detail_page(member_id):
    """특정 멤버의 상세 프로필 페이지를 보여줍니다."""
    try:
        # DB에서 요청된 ID의 멤버 정보를 조회합니다.
        member_res = supabase.table('members').select('*').eq('id', member_id).single().execute()
        member_data = member_res.data
        if not member_data:
            flash("존재하지 않는 회원입니다.", "danger")
            return redirect(url_for('profiles_page'))

    except Exception as e:
        flash(f"프로필 로딩 중 오류: {e}", "danger")
        return redirect(url_for('profiles_page'))

    # 새로 만들 profile_detail.html 템플릿으로 데이터를 전달합니다.
    return render_template('profile_detail.html', member=member_data)

# ==============================================================================
# <editor-fold desc="4. 관리자 (Admin) 전용 기능">
# --- 4.1. 관리자 대시보드 및 이벤트 관리 ---
@app.route('/admin/dashboard')
@login_required(role="admin")
def admin_dashboard():
    try:
        events_res = supabase.table('events').select('*').order('created_at', desc=True).execute().data

        # [수정] interviewer 목록과 별개로, 모든 멤버의 id, name, is_active 상태를 가져옵니다.
        all_members_res = supabase.table('members').select('id, name, is_active').order('name').execute().data

        interviewers_res = supabase.table('interviewers').select('name').execute().data
        interviewer_names = {i['name'] for i in interviewers_res}
        next_monday = get_next_monday()

    except Exception as e:
        flash(f"대시보드 로딩 중 오류 발생: {e}", "danger")
        events_res, all_members_res, interviewer_names = [], [], set()

    return render_template(
        'admin_dashboard.html',
        events=events_res,
        # [수정] 기존 all_members 대신 모든 멤버 정보를 전달합니다.
        all_members=all_members_res,
        interviewer_names=interviewer_names,
        meeting_date=next_monday
    )


@app.route('/api/admin/members/<int:member_id>/toggle_active', methods=['POST'])
@login_required(role="admin")
def toggle_member_active(member_id):
    """관리자가 특정 멤버의 활성/비활성 상태를 변경합니다."""
    data = request.json
    new_status = data.get('is_active')

    if new_status is None:
        return jsonify({"status": "error", "message": "is_active 값이 필요합니다."}), 400

    try:
        # 자기 자신을 비활성화하지 못하도록 방지
        if member_id == session.get('user_id') and not new_status:
            return jsonify({"status": "error", "message": "자기 자신을 비활성화할 수 없습니다."}), 403

        supabase.table('members').update({
            'is_active': new_status
        }).eq('id', member_id).execute()

        return jsonify({"status": "success", "message": "멤버 상태가 변경되었습니다."})

    except Exception as e:
        app.logger.error(f"Error toggling active status for member {member_id}: {e}")
        return jsonify({"status": "error", "message": "상태 변경 중 오류 발생"}), 500

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
    [수정] 이벤트 정보와 함께, 생성된 모든 슬롯의 상세 목록도 함께 불러옵니다.
    """
    try:
        event_res = supabase.table('events').select('*').eq('id', event_id).single().execute()
        event_data = event_res.data

        # 해당 이벤트의 모든 슬롯을 시간순으로 정렬하여 가져옵니다.
        # 예약자 정보를 함께 표시하기 위해 관련 데이터도 조회합니다.
        slots_res = supabase.table('time_slots').select('*, reservations(applicants(*))').eq('event_id', event_id).order('slot_datetime').execute()
        slots_data = slots_res.data

        # 날짜별 슬롯 요약 (기존 기능 유지)
        slots_summary = {}
        KST = timezone(timedelta(hours=9))
        for slot in slots_data:
            utc_dt = datetime.fromisoformat(slot['slot_datetime'].replace('Z', '+00:00'))
            kst_dt = utc_dt.astimezone(KST)
            date_key = kst_dt.strftime('%Y-%m-%d')
            slots_summary[date_key] = slots_summary.get(date_key, 0) + 1

        return render_template(
            'admin_event_manage.html',
            event=event_data,
            slots_summary=slots_summary,
            all_slots=slots_data  # 상세 슬롯 목록을 템플릿으로 전달
        )
    except Exception as e:
        flash(f"이벤트 정보를 불러오는 중 오류 발생: {e}", "danger")
        return redirect(url_for('admin_dashboard'))


@app.route('/api/admin/slots/<slot_id>/delete', methods=['POST'])
@login_required(role="admin")
def delete_single_slot(slot_id):
    """관리자가 특정 시간 슬롯 하나를 삭제합니다."""
    try:
        # 슬롯이 예약되어 있는지 확인하고, 예약되어 있다면 예약을 먼저 삭제합니다.
        supabase.table('reservations').delete().eq('slot_id', slot_id).execute()

        # 이제 시간 슬롯을 삭제합니다.
        result = supabase.table('time_slots').delete().eq('id', slot_id).execute()

        if not result.data:
            return jsonify({'status': 'error', 'message': '삭제할 슬롯을 찾을 수 없습니다.'}), 404

        return jsonify({'status': 'success', 'message': '슬롯이 성공적으로 삭제되었습니다.'})
    except Exception as e:
        app.logger.error(f"Error deleting slot {slot_id}: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


# app.py

@app.route('/admin/events/<event_id>/timetable')
@login_required(role="admin")
def admin_event_timetable(event_id):
    app.logger.info("--- admin_event_timetable 함수 실행 시작 ---")
    try:
        # 1. 이벤트 정보 조회
        app.logger.info(f"이벤트 조회 시도: ID = {event_id}")
        event_res = supabase.table('events').select('id, event_name').eq('id', event_id).execute()

        # 데이터가 있는지 확인
        if not hasattr(event_res, 'data') or not event_res.data:
            flash('해당 이벤트를 찾을 수 없습니다.', 'danger')
            app.logger.warning(f"이벤트를 찾지 못함: ID = {event_id}")
            return redirect(url_for('admin_dashboard'))

        event_data = event_res.data[0]
        app.logger.info(f"이벤트 조회 성공: {event_data}")

        # 2. 면접관 목록 조회
        app.logger.info("면접관 목록 조회 시도...")
        interviewers_res = supabase.table('interviewers').select('id, name').order('name').execute()

        # 데이터가 있는지 확인 (가장 확실한 방법)
        interviewers_data = interviewers_res.data if hasattr(interviewers_res, 'data') else []
        app.logger.info(f"면접관 목록 조회 성공: {len(interviewers_data)}명")

        # 3. 템플릿 렌더링 시도
        app.logger.info("render_template 호출 직전...")
        app.logger.info(
            f"전달할 데이터: event={event_data}, event_id={event_data['id']}, all_interviewers={interviewers_data}")

        return render_template(
            'timetable_view.html',
            event=event_data,
            event_id=event_data['id'],
            user_role=session['user_role'],
            all_interviewers=interviewers_data,
            is_shared_view=False  # [수정] 이 값을 명시적으로 전달
        )

    except Exception as e:
        # [중요] 오류 발생 시, 상세한 전체 오류 내용을 로그에 기록
        app.logger.error("!!! admin_event_timetable 함수에서 예외 발생 !!!", exc_info=True)
        flash(f"타임테이블 로딩 중 예측하지 못한 오류 발생: {e}", "danger")
        return redirect(url_for('admin_dashboard'))


@app.route('/admin/events/<event_id>/generate_slots', methods=['POST'])
@login_required(role="admin")
def generate_slots(event_id):
    """
    [수정] 선택된 요일에만 면접 슬롯이 생성되도록 로직을 변경합니다.
    """
    try:
        form = request.form
        start_date = datetime.strptime(form.get('start_date'), '%Y-%m-%d').date()
        end_date = datetime.strptime(form.get('end_date'), '%Y-%m-%d').date()
        start_time = datetime.strptime(form.get('start_time'), '%H:%M').time()
        end_time = datetime.strptime(form.get('end_time'), '%H:%M').time()
        # 요일 정보를 리스트로 받습니다. (월요일=0, 화요일=1, ..., 일요일=6)
        selected_days = request.form.getlist('days')
        if not selected_days:
            flash("슬롯을 생성할 요일을 하나 이상 선택해주세요.", "warning")
            return redirect(url_for('manage_event', event_id=event_id))

        KST = timezone(timedelta(hours=9))
        slots_to_insert = []
        current_date = start_date

        while current_date <= end_date:
            # 현재 날짜의 요일이 선택된 요일 리스트에 있는지 확인
            # str()로 감싸는 이유는 form에서 온 값들이 문자열이기 때문입니다.
            if str(current_date.weekday()) in selected_days:
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
            flash("선택하신 기간과 요일에 생성할 슬롯이 없습니다. 날짜나 시간을 다시 확인해주세요.", 'warning')

    except Exception as e:
        flash(f"슬롯 생성 중 오류 발생: {e}", "danger")

    return redirect(url_for('manage_event', event_id=event_id))


@app.route('/api/events/<event_id>/timetable_data')
def get_timetable_data(event_id):
    """[수정] 로깅을 추가하여 데이터 흐름을 추적합니다."""
    app.logger.info(f"--- 타임테이블 데이터 요청 시작 (Event ID: {event_id}) ---")
    try:
        # --- 1. 슬롯 정보 조회 ---
        response_slots = supabase.table('time_slots').select('*').eq('event_id', event_id).order(
            'slot_datetime').execute()
        slots_res = response_slots.data if hasattr(response_slots, 'data') and response_slots.data else []
        app.logger.info(f"1. 슬롯 조회 완료: {len(slots_res)}개 슬롯 발견")

        # --- 중간 데이터 확인 (로깅) ---
        # 로깅을 위해 필요한 데이터만 간추려서 확인합니다.
        interviewer_ids_to_fetch = set()
        for s in slots_res:
            if s.get('interviewer_ids'):
                interviewer_ids_to_fetch.update(s['interviewer_ids'])

        booked_slot_ids = [s['id'] for s in slots_res if s['is_booked']]
        app.logger.info(f"2. 예약된 슬롯 ID: {booked_slot_ids}")
        app.logger.info(f"3. 필요한 면접관 ID: {interviewer_ids_to_fetch}")

        # --- 2. 관련 정보 조회 ---
        reservations_data = []
        if booked_slot_ids:
            response_reservations = supabase.table('reservations').select('slot_id, applicant_id').in_('slot_id',
                                                                                                       booked_slot_ids).execute()
            reservations_data = response_reservations.data if hasattr(response_reservations,
                                                                      'data') and response_reservations.data else []
        app.logger.info(f"4. 예약 정보 조회 완료: {len(reservations_data)}개 예약 발견")

        applicant_ids_to_fetch = {r['applicant_id'] for r in reservations_data}
        app.logger.info(f"5. 필요한 지원자 ID: {applicant_ids_to_fetch}")

        applicants_data = []
        if applicant_ids_to_fetch:
            response_applicants = supabase.table('applicants').select('*').in_('id',
                                                                               list(applicant_ids_to_fetch)).execute()
            applicants_data = response_applicants.data if hasattr(response_applicants,
                                                                  'data') and response_applicants.data else []
        app.logger.info(f"6. 지원자 정보 조회 완료: {len(applicants_data)}명 정보 발견")

        interviewers_data = []
        if interviewer_ids_to_fetch:
            response_interviewers = supabase.table('interviewers').select('id, name').in_('id', list(
                interviewer_ids_to_fetch)).execute()
            interviewers_data = response_interviewers.data if hasattr(response_interviewers,
                                                                      'data') and response_interviewers.data else []
        app.logger.info(f"7. 면접관 정보 조회 완료: {len(interviewers_data)}명 정보 발견")

        # --- 3. 데이터 가공 ---
        app.logger.info("8. 데이터 가공 시작...")
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
                applicant_id = reservation_map[slot['id']]
                slot['applicant'] = applicants_map.get(applicant_id)  # .get()은 키가 없으면 None을 반환하여 안전

        app.logger.info("9. 데이터 가공 완료. JSON 변환 시도...")
        app.logger.info(f"최종 데이터: {slots_res}")  # 최종 데이터를 로그로 출력

        return jsonify(slots_res)

    except Exception as e:
        app.logger.error(f"!!! get_timetable_data 함수에서 오류 발생: {e}", exc_info=True)  # exc_info=True로 상세한 오류 위치 추적
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
        # --- [신규] 취소할 슬롯의 event_id를 먼저 가져옴 ---
        slot_res = supabase.table('time_slots').select('event_id').eq('id', slot_id).single().execute()
        event_id = slot_res.data['event_id']
        # 예약 테이블에서 해당 슬롯 ID의 예약을 삭제합니다.
        supabase.table('reservations').delete().eq('slot_id', slot_id).execute()
        # 시간 슬롯 테이블에서 is_booked 상태를 false로 되돌립니다.
        supabase.table('time_slots').update({'is_booked': False}).eq('id', slot_id).execute()
        # --- [신규] 예약 취소 후 슬롯 클러스터링 함수 호출 ---
        update_active_slots_for_clustering(event_id)

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

@app.route('/api/admin/reservations/create', methods=['POST'])
@login_required(role="admin")
def admin_create_reservation():
    """관리자가 타임테이블에서 직접 면접자를 등록하고 예약합니다."""
    data = request.get_json()
    slot_id = data.get('slot_id')
    name = data.get('name')
    phone = data.get('phone_number')

    if not all([slot_id, name, phone]):
        return jsonify({"error": "슬롯 ID, 이름, 연락처는 필수입니다."}), 400

    try:
        # 1. 슬롯 상태 확인
        slot_info = supabase.table('time_slots').select('is_booked').eq('id', slot_id).single().execute().data
        if not slot_info:
            return jsonify({"error": "존재하지 않는 슬롯입니다."}), 404
        if slot_info.get('is_booked'):
            return jsonify({"error": "이미 예약된 슬롯입니다."}), 409

        # 2. 면접자(applicant) 정보 확인 또는 생성
        applicant_res = supabase.table('applicants').select('id').eq('phone_number', phone).execute().data
        if applicant_res:
            applicant_id = applicant_res[0]['id']
            # 이미 있는 지원자 정보 업데이트 (이름이 다를 경우 대비)
            supabase.table('applicants').update({'name': name}).eq('id', applicant_id).execute()
        else:
            # 새로운 지원자 생성
            new_applicant = supabase.table('applicants').insert({'name': name, 'phone_number': phone}).execute().data[0]
            applicant_id = new_applicant['id']

        # 3. 예약(reservation) 생성
        supabase.table('reservations').insert({'slot_id': slot_id, 'applicant_id': applicant_id}).execute()

        # 4. 슬롯 상태를 '예약 완료'로 변경
        supabase.table('time_slots').update({'is_booked': True}).eq('id', slot_id).execute()

        return jsonify({"message": "예약이 성공적으로 등록되었습니다."}), 201

    except Exception as e:
        app.logger.error(f"Error creating reservation by admin: {e}")
        return jsonify({"error": "예약 처리 중 서버 오류가 발생했습니다."}), 500


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

        # 슬롯이 존재하면, 관련된 예약과 슬롯을 명시적으로 삭제합니다.
        if slots_to_delete_res.data:
            slot_ids = [slot['id'] for slot in slots_to_delete_res.data]
            # 1. 예약(reservations)을 먼저 삭제합니다.
            supabase.table('reservations').delete().in_('slot_id', slot_ids).execute()
            # 2. 시간 슬롯(time_slots)을 그 다음 삭제합니다.
            supabase.table('time_slots').delete().eq('event_id', event_id).execute()

        # 3. 이제 관련 데이터가 모두 사라졌으므로 이벤트를 안전하게 삭제합니다.
        supabase.table('events').delete().eq('id', event_id).execute()

        return jsonify({'status': 'success', 'message': '이벤트가 성공적으로 삭제되었습니다.'})
    except Exception as e:
        app.logger.error(f"Error deleting event: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/admin/events/<event_id>/delete_all_slots', methods=['POST'])
@login_required(role="admin")
def delete_all_slots(event_id):
    """특정 이벤트에 속한 모든 시간 슬롯과 예약을 삭제합니다."""
    try:
        # 1. 삭제할 슬롯들의 ID를 먼저 조회합니다.
        slots_to_delete_res = supabase.table('time_slots').select('id').eq('event_id', event_id).execute()
        if not slots_to_delete_res.data:
            return jsonify({'status': 'info', 'message': '삭제할 슬롯이 없습니다.'})

        slot_ids = [slot['id'] for slot in slots_to_delete_res.data]

        # 2. 해당 슬롯들과 연결된 '예약(reservations)'을 먼저 삭제합니다.
        supabase.table('reservations').delete().in_('slot_id', slot_ids).execute()

        # 3. '시간 슬롯(time_slots)'을 삭제합니다.
        supabase.table('time_slots').delete().eq('event_id', event_id).execute()

        return jsonify({'status': 'success', 'message': f'{len(slot_ids)}개의 슬롯과 관련 예약이 모두 삭제되었습니다.'})

    except Exception as e:
        app.logger.error(f"Error deleting all slots for event {event_id}: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/admin/events/<event_id>/update', methods=['POST'])
@login_required(role="admin")
def update_event(event_id):
    """이벤트 정보를 수정합니다."""
    try:
        form_data = request.form
        update_data = {
            'event_name': form_data.get('event_name'),
            'start_date': form_data.get('start_date'),
            'end_date': form_data.get('end_date'),
        }
        supabase.table('events').update(update_data).eq('id', event_id).execute()
        flash('이벤트 정보가 성공적으로 수정되었습니다.', 'success')
    except Exception as e:
        app.logger.error(f"Error updating event {event_id}: {e}")
        flash(f'이벤트 수정 중 오류 발생: {e}', 'danger')

    return redirect(url_for('manage_event', event_id=event_id))

@app.route('/api/admin/applicants/<applicant_id>/update', methods=['POST'])
@login_required(role="admin")
def update_applicant_info(applicant_id):
    """관리자가 예약자의 정보를 수정합니다."""
    try:
        data = request.json
        name = data.get('name')
        phone_number = data.get('phone_number')

        if not name or not phone_number:
            return jsonify({'status': 'error', 'message': '이름과 연락처는 필수입니다.'}), 400

        supabase.table('applicants').update({
            'name': name,
            'phone_number': phone_number
        }).eq('id', applicant_id).execute()

        return jsonify({'status': 'success', 'message': '예약자 정보가 수정되었습니다.'})

    except Exception as e:
        app.logger.error(f"Error updating applicant info for {applicant_id}: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


def update_active_slots_for_clustering(event_id):
    """
    특정 이벤트의 예약 현황을 기반으로 슬롯을 클러스터링(군집화)하도록
    is_active 상태를 동적으로 업데이트하는 함수.
    """
    try:
        # 1. 해당 이벤트의 모든 슬롯 정보를 가져옵니다.
        all_slots_res = supabase.table('time_slots').select('id, slot_datetime, is_booked').eq('event_id',
                                                                                               event_id).order(
            'slot_datetime').execute()
        all_slots = all_slots_res.data
        if not all_slots:
            return  # 슬롯이 없으면 아무것도 하지 않음

        # 2. 예약된 슬롯들의 시간만 추출합니다.
        booked_times = [datetime.fromisoformat(slot['slot_datetime'].replace('Z', '+00:00')) for slot in all_slots if
                        slot['is_booked']]

        # 3. 예약이 하나도 없으면, 모든 슬롯을 활성화 상태로 두고 종료 (관리자가 설정한 초기 상태 유지)
        if not booked_times:
            supabase.table('time_slots').update({'is_active': True}).eq('event_id', event_id).execute()
            app.logger.info(f"Event {event_id}: No bookings found. All slots activated.")
            return

        # 4. 예약된 시간 앞뒤로 활성화할 버퍼(시간 간격)를 설정합니다. (예: 30분)
        buffer = timedelta(minutes=15)

        slots_to_activate = set()
        slots_to_deactivate = set()

        # 5. 모든 슬롯을 순회하며 활성화/비활성화 여부 결정
        for slot in all_slots:
            # 이미 예약된 슬롯은 항상 활성 상태로 둡니다.
            if slot['is_booked']:
                slots_to_activate.add(slot['id'])
                continue

            slot_time = datetime.fromisoformat(slot['slot_datetime'].replace('Z', '+00:00'))
            is_near_booking = False
            # 현재 슬롯이 예약된 시간들의 버퍼 안에 있는지 확인
            for booked_time in booked_times:
                if (booked_time - buffer) <= slot_time <= (booked_time + buffer):
                    is_near_booking = True
                    break

            if is_near_booking:
                slots_to_activate.add(slot['id'])
            else:
                slots_to_deactivate.add(slot['id'])

        # 6. 데이터베이스 업데이트 실행
        if slots_to_activate:
            supabase.table('time_slots').update({'is_active': True}).in_('id', list(slots_to_activate)).execute()
        if slots_to_deactivate:
            supabase.table('time_slots').update({'is_active': False}).in_('id', list(slots_to_deactivate)).execute()

        app.logger.info(f"Event {event_id}: Clustered slots around bookings.")

    except Exception as e:
        app.logger.error(f"Error updating slots for clustering (Event ID: {event_id}): {e}")


@app.route('/api/notifications')
@login_required(role="admin")
def get_notifications():
    """관리자에게 보여줄 승인 대기 중인 알림 목록을 반환합니다."""
    try:
        notifications = supabase.table('notifications') \
            .select('*') \
            .eq('status', 'pending') \
            .order('created_at', desc=True) \
            .execute().data
        return jsonify(notifications)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/notifications/<int:notif_id>/handle', methods=['POST'])
@login_required(role="admin")
def handle_notification(notif_id):
    data = request.json
    action = data.get('action')
    print(f"\n--- [DEBUG] Handling Notification ID: {notif_id}, Action: {action} ---")

    if action not in ['approve', 'deny']:
        return jsonify({"error": "Invalid action"}), 400

    try:
        # 1. 알림 정보 조회
        print("[DEBUG] 1. Fetching notification details...")
        notification_to_handle_res = supabase.table('notifications').select('related_member_id') \
            .eq('id', notif_id).single().execute()

        notification_to_handle = notification_to_handle_res.data

        if not notification_to_handle:
            print("[DEBUG] ERROR: Notification not found.")
            return jsonify({"error": "Notification not found"}), 404
        print(f"[DEBUG]    -> Found. Member ID to update: {notification_to_handle.get('related_member_id')}")

        # 2. 알림 상태 업데이트
        print("[DEBUG] 2. Updating notification status...")
        supabase.table('notifications').update({
            'status': 'approved' if action == 'approve' else 'denied'
        }).eq('id', notif_id).execute()
        print("[DEBUG]    -> Notification status updated successfully.")

        # 3. 'approve' 액션일 경우, 멤버 상태를 'active'로 변경
        if action == 'approve':
            member_id = notification_to_handle.get('related_member_id')

            # [수정] member_id가 0인 경우도 유효한 값으로 처리하도록 조건문 변경
            if member_id is not None:
                print(f"[DEBUG] 3. Approving member. Attempting to update members table for ID: {member_id}")
                update_response = supabase.table('members').update({
                    'account_status': 'active'
                }).eq('id', member_id).execute()
                print(f"[DEBUG]    -> Update response from Supabase: {update_response.data}")
            else:
                print("[DEBUG]    -> No valid member_id found in notification, skipping member update.")

        print("[DEBUG] --- Request handled successfully. ---")
        return jsonify({"status": "success", "message": f"요청이 {action}되었습니다."})

    except Exception as e:
        print(f"[DEBUG] !!! AN EXCEPTION OCCURRED !!!\n{e}")
        app.logger.error(f"Error handling notification {notif_id}: {e}")
        return jsonify({"error": str(e)}), 500

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


@app.route('/making_team', methods=['GET'])
@login_required(role="admin")
def bookclub_index():
    try:
        # 1. 전체 회원 목록을 가져옵니다.
        all_members = supabase.table("members").select("id, name").eq('is_active', True).order("name").execute().data

        # 2. 다음 주 월요일의 출석 정보를 가져옵니다.
        next_monday = get_next_monday()
        attendees_res = supabase.table('attendance').select('user_id, attending_seminar, attending_afterparty') \
            .eq('meeting_date', next_monday.isoformat()).execute()

        # 3. 출석 정보를 user_id를 키로 하는 딕셔너리로 변환하여 쉽게 찾을 수 있게 합니다.
        attendance_map = {att['user_id']: att for att in attendees_res.data}

        # 4. 전체 회원 목록에 각자의 출석 정보를 합칩니다.
        for member in all_members:
            attendance_info = attendance_map.get(member['id'])
            if attendance_info:
                member['attending_seminar'] = attendance_info['attending_seminar']
                member['attending_afterparty'] = attendance_info['attending_afterparty']
            else:  # 출석 정보가 없으면 기본값(불참)으로 설정
                member['attending_seminar'] = False
                member['attending_afterparty'] = False

    except Exception as e:
        flash(f"데이터를 불러오는 중 오류가 발생했습니다: {e}", "danger")
        all_members = []

    return render_template(
        'bookclub_index.html',
        # [수정] 출석 정보가 포함된 전체 멤버 목록을 전달
        members_with_attendance=all_members
    )


@app.route('/start_group_generation')
@login_required(role="admin")
def start_group_generation():
    present_names = request.args.getlist('present')
    facilitator_names = request.args.getlist('facilitators')
    group_count_str = request.args.get('group_count')
    group_names_str = request.args.get('group_names', '')

    # 요청 컨텍스트가 활성 상태일 때 '편집' 페이지 URL을 미리 생성합니다.
    manual_entry_url = url_for('manual_entry')

    def generate_events(manual_url):
        try:
            # DB에서 데이터 로드
            members_res = supabase.table("members").select("*").order("name").execute().data
            members_df = pd.DataFrame(members_res)
            history_res = supabase.table("history").select("groups").execute().data
            history_df = pd.DataFrame(history_res if history_res else [])

            group_count_override = None
            if group_count_str and group_count_str.isdigit():
                group_count_override = int(group_count_str)

            # 제너레이터의 최종 반환 값(return)을 처리하는 헬퍼 함수
            def get_final_result_from_generator(generator, progress_offset=0, progress_scale=0.5):
                final_result = []
                while True:
                    try:
                        progress = next(generator)
                        progress_data = json.dumps({'progress': int(progress_offset + (progress * progress_scale))})
                        yield f"event: progress\ndata: {progress_data}\n\n"
                    except StopIteration as e:
                        # 웹사이트에서는 결과 1개만 반환되므로, 그대로 할당합니다.
                        final_result = e.value
                        break
                return final_result

            # '성비 우선' 알고리즘 실행
            gender_generator = run_genetic_algorithm(
                members_df, history_df, present_names, facilitator_names,
                (10.0, 6.0, 3.0, 2.0, -1000.0), 20, group_count_override, test_mode=False
            )
            gender_solutions = yield from get_final_result_from_generator(gender_generator, 0, 0.5)

            # '새로운 만남 우선' 알고리즘 실행
            new_face_generator = run_genetic_algorithm(
                members_df, history_df, present_names, facilitator_names,
                (6.0, 10.0, 3.0, 2.0, -1000.0), 20, group_count_override, test_mode=False
            )
            new_face_solutions = yield from get_final_result_from_generator(new_face_generator, 50, 0.5)

            # 프론트엔드에 전달할 '만남 횟수 기록' 데이터 생성
            meeting_history = {}
            if not history_df.empty and 'groups' in history_df.columns:
                for _, row in history_df.iterrows():
                    groups_list = row['groups']
                    if not isinstance(groups_list, list): continue
                    for group in groups_list:
                        for i in range(len(group)):
                            for j in range(i + 1, len(group)):
                                pair_key = '-'.join(sorted([group[i], group[j]]))
                                meeting_history[pair_key] = meeting_history.get(pair_key, 0) + 1

            # 최종 결과 페이지 렌더링
            with app.app_context():
                group_names = [name.strip() for name in group_names_str.split(',') if name.strip()]
                final_html = render_template(
                    'bookclub_ga_results.html',
                    gender_solutions=gender_solutions,
                    new_face_solutions=new_face_solutions,
                    present=present_names,
                    facilitators=facilitator_names,
                    group_names=group_names,
                    meeting_history=meeting_history,
                    manual_entry_url=manual_url
                )
                complete_data = json.dumps({'html': final_html})
                yield f"event: complete\ndata: {complete_data}\n\n"

        except Exception as e:
            app.logger.error(f"조 편성 중 오류 발생: {e}", exc_info=True)
            error_data = json.dumps({'error': str(e)})
            yield f"event: error\ndata: {error_data}\n\n"

    return Response(generate_events(manual_entry_url), mimetype='text/event-stream')


# app.py 파일에서 이 함수 전체를 아래 코드로 교체해주세요.

def run_genetic_algorithm(members_df, history_df, attendee_names, presenter_names, weights, num_results=3,
                          group_count_override=None, test_mode=False):
    # --- 1, 2, 3 단계는 기존과 동일하게 유지 ---
    # ... (데이터 전처리, 시나리오 설정, evaluate 함수 등은 생략) ...
    # --- 1. 데이터 전처리 ---
    members_info = members_df.set_index('id').to_dict('index')
    name_to_id_map = pd.Series(members_df.id.values, index=members_df.name).to_dict()
    meeting_history = {}
    if not history_df.empty and 'groups' in history_df.columns:
        for index, row in history_df.iterrows():
            try:
                groups_list = row['groups']
                if not isinstance(groups_list, list): continue
                for group in groups_list:
                    member_ids_in_group = [name_to_id_map.get(name) for name in group if name in name_to_id_map]
                    for i in range(len(member_ids_in_group)):
                        for j in range(i + 1, len(member_ids_in_group)):
                            if member_ids_in_group[i] is None or member_ids_in_group[j] is None: continue
                            pair = tuple(sorted((member_ids_in_group[i], member_ids_in_group[j])))
                            meeting_history[pair] = meeting_history.get(pair, 0) + 1
            except Exception:
                continue

    # --- 2. 시나리오 설정 ---
    TODAY_ATTENDEE_IDS = [name_to_id_map[name] for name in attendee_names if name in name_to_id_map]
    TODAY_PRESENTER_IDS = [name_to_id_map[name] for name in presenter_names if name in name_to_id_map]
    num_attendees = len(TODAY_ATTENDEE_IDS)
    if num_attendees < 3:
        return [], None

    if group_count_override and group_count_override > 0:
        num_groups = group_count_override
    else:
        if num_attendees <= 5:
            num_groups = 1
        elif num_attendees <= 10:
            num_groups = 2
        else:
            num_groups = round(num_attendees / 4.5)

    attendee_id_map = {idx: member_id for idx, member_id in enumerate(TODAY_ATTENDEE_IDS)}

    # --- 3. 적합도 평가 함수 (evaluate) ---
    MIN_GROUP_SIZE = 3

    # [수정] 최대 그룹 인원 수를 동적으로 계산합니다.
    DEFAULT_MAX_GROUP_SIZE = 5
    # 수학적으로 필요한 최소한의 최대 인원 수를 계산합니다 (예: 17명/3그룹 -> 5.33 -> 6명)
    required_max_size = math.ceil(num_attendees / num_groups) if num_groups > 0 else 0
    # 기본값과 필요값 중 더 큰 값을 실제 최대 인원 수로 사용합니다.
    MAX_GROUP_SIZE = max(DEFAULT_MAX_GROUP_SIZE, required_max_size)

    RECENT_MEETING_THRESHOLD = 2

    def calculate_total_score(ind_fitness_values, W):
        total = sum(v * w for v, w in zip(ind_fitness_values, W))

        # [디버깅] 비정상적으로 큰 점수가 계산될 때만 내부 계산 과정을 출력합니다.
        if total > 1000:
            raw_scores_str = ", ".join([f"{v:.2f}" for v in ind_fitness_values])
            print(f"[SCORE_DEBUG] Raw Scores: [{raw_scores_str}] -> Total: {total:.2f}")

        return total

    def evaluate(individual):
        groups = {i: [] for i in range(num_groups)}
        for i, g in enumerate(individual):
            groups[g].append(attendee_id_map[i])

        # [수정] size_penalty를 계산만 하고, 조기 return하지 않습니다.
        size_penalty = sum(1 for g in groups.values() if 0 < len(g) < MIN_GROUP_SIZE or len(g) > MAX_GROUP_SIZE)

        # 만약 유효하지 않은 그룹 크기라면, 다른 점수 계산 없이 바로 페널티만 적용된 값을 반환합니다.
        # 이렇게 하면 계산 시간을 절약하고 로직이 명확해집니다.
        if size_penalty > 0:
            return 0, 0, 0, 0, size_penalty  # 페널티는 양수로 반환

        # --- 유효한 그룹일 경우에만 아래 점수들을 계산 ---
        new_face_score, preference_score, total_pairs = 0, 0, 0
        group_gender_scores = []

        for group_members in groups.values():
            if not group_members: continue

            # 성비 점수 계산
            males = sum(1 for mid in group_members if members_info.get(mid, {}).get('gender') == 'M')
            females = len(group_members) - males
            if males > 0 and females > 0:
                group_gender_scores.append(min(males, females) / max(males, females))
            else:
                group_gender_scores.append(0)

            # 새얼굴, 선호도 점수 계산
            for i, member_id in enumerate(group_members):
                member_prefs = members_info.get(member_id)
                if member_prefs:
                    preferred_id = member_prefs.get('preferred_member_id')
                    avoided_id = member_prefs.get('avoided_member_id')
                    for j in range(i + 1, len(group_members)):
                        other_member_id = group_members[j]
                        total_pairs += 1
                        pair = tuple(sorted((member_id, other_member_id)))
                        meet_count = meeting_history.get(pair, 0)
                        new_face_score += 1 / (meet_count + 1)
                        if other_member_id == preferred_id and meet_count < RECENT_MEETING_THRESHOLD: preference_score += 1
                        other_prefs = members_info.get(other_member_id)
                        if other_prefs and other_prefs.get(
                            'preferred_member_id') == member_id and meet_count < RECENT_MEETING_THRESHOLD: preference_score += 1
                        if other_member_id == avoided_id: preference_score -= 1.5
                        if other_prefs and other_prefs.get('avoided_member_id') == member_id: preference_score -= 1.5

        # 최종 정규화된 점수 계산
        gender_score = np.mean(group_gender_scores) if group_gender_scores else 0
        norm_new_face = new_face_score / total_pairs if total_pairs > 0 else 0
        max_pref_score = len(TODAY_ATTENDEE_IDS) * 2
        norm_pref = (preference_score + max_pref_score) / (max_pref_score * 2) if max_pref_score > 0 else 0
        presenters_per_group = [sum(1 for mid in g if mid in TODAY_PRESENTER_IDS) for g in groups.values()]
        presenter_score = 1 / (np.var(presenters_per_group) + 0.1) if len(presenters_per_group) > 1 else 10.0

        # [수정] 마지막에 모든 점수를 함께 반환합니다. 페널티는 양수(0, 1, 2...) 입니다.
        return gender_score, norm_new_face, presenter_score, norm_pref, size_penalty

    # --- 4. 유전 알고리즘 실행 ---
    fitness_name = f"FitnessGA_{abs(hash(weights))}"
    individual_name = f"IndividualGA_{abs(hash(weights))}"
    if hasattr(creator, fitness_name): delattr(creator, fitness_name)
    if hasattr(creator, individual_name): delattr(creator, individual_name)

    creator.create(fitness_name, base.Fitness, weights=weights)
    creator.create(individual_name, list, fitness=getattr(creator, fitness_name))
    toolbox = base.Toolbox()
    toolbox.register("individual", tools.initRepeat, getattr(creator, individual_name),
                     lambda: random.randint(0, num_groups - 1), n=num_attendees)
    toolbox.register("population", tools.initRepeat, list, toolbox.individual)
    toolbox.register("evaluate", evaluate)
    toolbox.register("mate", tools.cxTwoPoint)
    toolbox.register("mutate", tools.mutUniformInt, low=0, up=num_groups - 1, indpb=0.05)
    toolbox.register("select", tools.selTournament, tournsize=3)

    pop_size, ngen, cxpb, mutpb = 1200, 100, 0.7, 0.6
    population = toolbox.population(n=pop_size)
    hall_of_fame = tools.HallOfFame(50)

    # [수정] Logbook 객체 대신 단순 파이썬 리스트 사용
    manual_log = []

    # 초기 집단 평가
    invalid_ind = [ind for ind in population if not ind.fitness.valid]
    fitnesses = toolbox.map(toolbox.evaluate, invalid_ind)
    for ind, fit in zip(invalid_ind, fitnesses):
        ind.fitness.values = fit
    hall_of_fame.update(population)

    # 세대 진화 시작
    for gen in range(1, ngen + 1):
        if not test_mode:
            if gen % 10 == 0 or gen == ngen:
                yield int((gen / ngen) * 100)

        offspring = toolbox.select(population, len(population))
        offspring = algorithms.varAnd(offspring, toolbox, cxpb, mutpb)
        invalid_ind = [ind for ind in offspring if not ind.fitness.valid]
        fitnesses = toolbox.map(toolbox.evaluate, invalid_ind)
        for ind, fit in zip(invalid_ind, fitnesses):
            ind.fitness.values = fit
        hall_of_fame.update(offspring)
        population[:] = offspring

        # [수정] Statistics 객체 대신 직접 최고 점수를 계산하고 리스트에 추가
        current_scores = [calculate_total_score(ind.fitness.values, weights) for ind in population]
        max_score = np.max(current_scores)
        manual_log.append({'gen': gen, 'max_score': max_score})

    # --- 5. 중복 제거 및 결과 포맷팅 ---
    def normalized_hamming_distance(ind1, ind2):
        labels1 = sorted(list(set(ind1)));
        labels2 = sorted(list(set(ind2)))
        if len(labels1) != len(labels2): return len(ind1)
        min_dist = len(ind1)
        for p_labels in itertools.permutations(labels2):
            label_map = {original: permuted for original, permuted in zip(labels2, p_labels)}
            permuted_ind2 = [label_map[label] for label in ind2]
            dist = sum(c1 != c2 for c1, c2 in zip(ind1, permuted_ind2))
            if dist < min_dist: min_dist = dist
        return min_dist

    def get_groups_from_individual(individual, attendee_id_map):
        groups_dict = {}
        for i, group_num in enumerate(individual):
            if group_num not in groups_dict: groups_dict[group_num] = []
            groups_dict[group_num].append(attendee_id_map[i])
        return {frozenset(v) for v in groups_dict.values() if v}

    def select_diverse_solutions(sorted_solutions, num_to_select, min_distance, attendee_id_map):
        if not sorted_solutions:
            return []

        diverse_selection = []
        # 가장 점수가 높은 첫 번째 추천안은 무조건 포함합니다.
        diverse_selection.append(sorted_solutions[0])

        # 나머지 추천안들을 순회하며 비교합니다.
        for sol in sorted_solutions[1:]:
            # 목표 개수에 도달하면 중단합니다.
            if len(diverse_selection) >= num_to_select:
                break

            is_diverse_enough = True
            # 이미 선택된 모든 추천안들과 하나씩 비교합니다.
            for selected_sol in diverse_selection:
                dist = normalized_hamming_distance(sol, selected_sol)
                # 너무 유사한 추천안이 하나라도 발견되면 탈락시킵니다.
                if dist < min_distance:
                    is_diverse_enough = False
                    break

            # 모든 기존 추천안들과 충분히 다르다고 판단되면, 최종 목록에 추가합니다.
            if is_diverse_enough:
                diverse_selection.append(sol)

        return diverse_selection

    valid_solutions = [ind for ind in hall_of_fame if ind.fitness.values[4] == 0]
    if not valid_solutions:
        return [], manual_log

    sorted_solutions = sorted(valid_solutions, key=lambda ind: calculate_total_score(ind.fitness.values, weights),
                              reverse=True)
    final_solutions_indices = select_diverse_solutions(sorted_solutions, num_results, int(num_attendees * 0.15),
                                                       attendee_id_map)

    output_results = []
    id_to_name_map = {v: k for k, v in name_to_id_map.items()}
    for sol in final_solutions_indices:
        groups = {i: [] for i in range(num_groups)}
        [groups[g].append(attendee_id_map[i]) for i, g in enumerate(sol)]
        formatted_groups = []
        for group_id in sorted(groups.keys()):
            if not groups[group_id]: continue
            member_names = [id_to_name_map.get(mid, "Unknown") for mid in groups[group_id]]
            formatted_groups.append(member_names)
        output_results.append({
            "score": f"{calculate_total_score(sol.fitness.values, weights):.2f}",
            "details": [f"{v:.2f}" for v in sol.fitness.values[:4]],
            "groups": formatted_groups
        })

    if test_mode:
        # 테스트 스크립트에서는 결과와 로그를 모두 반환
        return output_results, manual_log
    else:
        # 웹사이트에서는 최종 결과만 반환
        return output_results


@app.route('/api/bookclub/save', methods=['POST'])
@login_required(role="admin")
def bookclub_save():
    data = request.json
    # 헬퍼 함수를 호출하여 저장 로직 실행
    result = save_group_record_to_db(data["date"], data["present"], data["facilitators"], data["groups"])

    if result["status"] == "ok":
        return jsonify(result)
    else:
        return jsonify(result), 500


# [신규] 조 편성 기록을 DB에 저장하는 헬퍼 함수
def save_group_record_to_db(date, present, facilitators, groups):
    """주어진 데이터로 조 편성 기록과 만남 횟수 매트릭스를 DB에 저장/업데이트합니다."""
    try:
        # 1. history 테이블에 기록 저장
        record = {"date": date, "present": present, "facilitators": facilitators, "groups": groups}
        supabase.table("history").insert(record).execute()

        # 2. bookclub_co_matrix 업데이트
        keys_to_update = {}
        for g in groups:
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
                new_count = current_counts.get(key, 0) + increment
                final_upsert_data.append({"pair_key": key, "count": new_count, "last_met": date})

            supabase.table("bookclub_co_matrix").upsert(final_upsert_data).execute()

        return {"status": "ok"}
    except Exception as e:
        app.logger.error(f"Error saving group record: {e}")
        return {"status": "error", "message": str(e)}

@app.route('/manual_entry')
@login_required(role="admin")
def manual_entry():
    """수동으로 조 편성을 입력하는 페이지를 렌더링합니다."""
    try:
        members_res = supabase.table("members").select("name").eq('is_active', True).order("name").execute().data
        all_members = [m['name'] for m in members_res]
    except Exception as e:
        flash(f"회원 정보를 불러오는 중 오류 발생: {e}", "danger")
        all_members = []
    return render_template('manual_entry.html', all_members=all_members)


@app.route('/save_manual_groups', methods=['POST'])
@login_required(role="admin")
def save_manual_groups():
    try:
        form_data = request.form

        meeting_date = form_data.get('meeting_date')
        present_members = form_data.getlist('present')
        # [수정] 발제자 정보도 폼에서 가져옵니다.
        facilitator_members = form_data.getlist('facilitators')

        groups = []
        for i in range(1, 6):
            group_text = form_data.get(f'group_{i}')
            if group_text:
                member_names = re.split(r'[,;\s\n]+', group_text)
                cleaned_group = [name.strip() for name in member_names if name.strip()]
                if cleaned_group:
                    groups.append(cleaned_group)

        if not all([meeting_date, present_members, groups]):
            flash("날짜, 참석자, 최소 1개 이상의 그룹을 모두 입력해야 합니다.", "danger")
            return redirect(url_for('manual_entry'))

        # [수정] 헬퍼 함수에 발제자 정보를 전달합니다.
        result = save_group_record_to_db(meeting_date, present_members, facilitator_members, groups)

        if result["status"] == "ok":
            flash("수동 조 편성 기록이 성공적으로 저장되었습니다.", "success")
            return redirect(url_for('admin_dashboard'))
        else:
            flash(f"저장 중 오류 발생: {result['message']}", "danger")
            return redirect(url_for('manual_entry'))

    except Exception as e:
        flash(f"처리 중 예외 발생: {e}", "danger")
        return redirect(url_for('manual_entry'))


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
# </editor-fold>
# ==============================================================================


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
        # [수정] 안정적인 데이터 조회 방식으로 변경
        event_res = supabase.table('events').select('id, event_name').eq('id', event_id).execute()
        if not event_res.data:
            flash('해당 이벤트를 찾을 수 없습니다.', 'danger')
            return redirect(url_for('interviewer_events_list'))

        event_data = event_res.data[0]

        return render_template(
            'timetable_view.html',
            event=event_data,
            event_id=event_data['id'],
            user_role=session['user_role'],
            is_shared_view=False  # [수정] is_shared_view=False 명시적 전달
        )
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


@app.route('/api/interviewer/slots/<slot_id>/unassign', methods=['POST'])
@login_required(role="interviewer")
def unassign_interviewer_from_slot(slot_id):
    """면접관이 특정 슬롯에서 자신의 참여를 취소합니다."""
    try:
        # 1. 현재 로그인한 면접관의 ID를 안정적으로 가져옵니다.
        interviewer_name = session.get('user_name')
        interviewer_res = supabase.table('interviewers').select('id').eq('name', interviewer_name).execute()

        if not hasattr(interviewer_res, 'data') or not interviewer_res.data:
            return jsonify({'status': 'error', 'message': '등록된 면접관 정보가 없습니다.'}), 404

        interviewer_id = interviewer_res.data[0]['id']

        # 2. 현재 슬롯의 면접관 ID 목록을 안정적으로 가져옵니다.
        slot_res = supabase.table('time_slots').select('interviewer_ids').eq('id', slot_id).execute()

        if not hasattr(slot_res, 'data') or not slot_res.data:
            return jsonify({'status': 'error', 'message': '존재하지 않는 슬롯입니다.'}), 404

        current_ids = slot_res.data[0].get('interviewer_ids') or []

        # 3. 목록에 해당 면접관 ID가 없으면, 취소할 수 없음을 알립니다.
        if interviewer_id not in current_ids:
            return jsonify({'status': 'error', 'message': '이 시간에 배정되어 있지 않습니다.'}), 409

        # 4. 목록에서 해당 면접관의 ID를 제거합니다.
        current_ids.remove(interviewer_id)

        # 5. 변경된 ID 목록으로 데이터베이스를 업데이트합니다.
        supabase.table('time_slots').update({'interviewer_ids': current_ids if current_ids else None}).eq('id',
                                                                                                          slot_id).execute()

        return jsonify({'status': 'success', 'message': '참여가 성공적으로 취소되었습니다.'})
    except Exception as e:
        app.logger.error(f"Error unassigning interviewer: {e}")
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

            # --- [수정] 요일을 포함한 시간 문자열 생성 로직 ---
            KST = timezone(timedelta(hours=9))
            utc_dt = datetime.fromisoformat(slot_response['slot_datetime'].replace('Z', '+00:00'))
            kst_dt = utc_dt.astimezone(KST)

            weekdays_kr = ["월", "화", "수", "목", "금", "토", "일"]
            day_of_week = weekdays_kr[kst_dt.weekday()]  # 요일을 숫자로 받아(월=0) 한국어 요일로 변환

            # 최종 시간 문자열 포맷팅
            reserved_time_str = kst_dt.strftime(f"%Y년 %m월 %d일 ({day_of_week}) %p %I:%M").replace("AM", "오전").replace(
                "PM", "오후")
            # --- 수정 끝 ---

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

        # --- [신규] 예약 완료 후 슬롯 클러스터링 함수 호출 ---
        event_id = slot_response['event_id']
        update_active_slots_for_clustering(event_id)

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


#=== 위키 관련 모음

@app.route('/docs/<doc_title>')
@login_required(role="ANY")
def view_document(doc_title):
    """
    데이터베이스에서 문서를 찾아 제목과 내용을 보여주는 페이지.
    """
    try:
        doc_res = supabase.table('documents').select('*').eq('title', doc_title).single().execute()
        document = doc_res.data

        if not document:
            flash(f"'{doc_title}' 문서를 찾을 수 없습니다.", "warning")
            return render_template('doc_not_found.html', title=doc_title), 404

        rendered_content = wiki_parser(document.get('content', ''))

        return render_template('doc_view.html', doc=document, content=rendered_content)

    except Exception as e:
        app.logger.error(f"Error viewing document '{doc_title}': {e}")
        flash("문서를 불러오는 중 오류가 발생했습니다.", "danger")
        return redirect(url_for('main_index'))


# 1. 문서 생성 페이지를 보여주는 라우트
@app.route('/docs/create')
@login_required(role="ANY")
def create_document_page():
    # doc_edit.html 템플릿을 렌더링. 'edit' 모드가 아니므로 doc 객체는 전달 안 함
    return render_template('doc_edit.html')


# 2. 문서 생성 요청을 처리하는 API 라우트
@app.route('/api/docs/create', methods=['POST'])
@login_required(role="ANY")
def handle_create_document():
    data = request.json
    title = data.get('title')
    content = data.get('content')
    author_id = session.get('user_id')  # 세션에서 현재 로그인한 사용자의 ID를 가져옴

    if not title or not content:
        return jsonify({"status": "error", "message": "제목과 내용을 모두 입력해야 합니다."}), 400

    try:
        # DB에 새로운 문서 삽입
        supabase.table('documents').insert({
            'title': title,
            'content': content,
            'author_id': author_id
        }).execute()

        # 성공 시, 새로 만들어진 문서 페이지로 바로 이동할 수 있도록 URL 반환
        return jsonify({"status": "success", "message": "문서가 성공적으로 생성되었습니다.", "doc_title": title})

    except Exception as e:
        # Supabase에서 title UNIQUE 제약 조건 위반 시 특정 에러 코드를 반환합니다.
        if '23505' in str(e):  # UNIQUE VIOLATION
            return jsonify({"status": "error", "message": f"이미 '{title}' 제목의 문서가 존재합니다."}), 409
        app.logger.error(f"Error creating document: {e}")
        return jsonify({"status": "error", "message": "문서 생성 중 오류 발생"}), 500


# 3. 전체 문서 목록을 보여주는 라우트
@app.route('/docs')
@login_required(role="ANY")
def view_all_documents():
    """
    지금까지 생성된 모든 문서의 목록을 보여주는 페이지.
    """
    try:
        # 문서의 제목, 마지막 수정일, 그리고 작성자(members 테이블과 join)의 이름을 가져옵니다.
        # 최근 수정된 문서가 위로 오도록 정렬합니다.
        docs_res = supabase.table('documents').select('title, updated_at, members(name)') \
            .order('updated_at', desc=True).execute()

        documents = docs_res.data

        return render_template('doc_list.html', documents=documents)

    except Exception as e:
        app.logger.error(f"Error fetching document list: {e}")
        flash("문서 목록을 불러오는 중 오류가 발생했습니다.", "danger")
        return redirect(url_for('main_index'))


# 4. 문서 수정 페이지를 보여주는 라우트
@app.route('/docs/edit/<doc_title>')
@login_required(role="ANY")
def edit_document_page(doc_title):
    try:
        doc_res = supabase.table('documents').select('*').eq('title', doc_title).single().execute()
        document = doc_res.data

        if not document:
            flash(f"'{doc_title}' 문서를 찾을 수 없습니다.", "warning")
            return redirect(url_for('view_all_documents'))

        # 권한 확인: 작성자 본인이거나 관리자인지 확인
        # if document['author_id'] != session.get('user_id') and session.get('user_role') != 'admin':
        #     flash("이 문서를 수정할 권한이 없습니다.", "danger")
        #     return redirect(url_for('view_document', doc_title=doc_title))

        # 생성 시 사용했던 doc_edit.html 템플릿을 재사용하되,
        # 기존 문서 데이터를 함께 전달하여 폼을 채워넣음
        return render_template('doc_edit.html', doc=document)

    except Exception as e:
        app.logger.error(f"Error loading edit page for document '{doc_title}': {e}")
        flash("편집 페이지를 불러오는 중 오류가 발생했습니다.", "danger")
        return redirect(url_for('view_all_documents'))


# 5. 문서 수정 요청을 처리하는 API 라우트
@app.route('/api/docs/edit/<doc_id>', methods=['POST'])
@login_required(role="ANY")
def handle_edit_document(doc_id):
    data = request.json
    content = data.get('content')
    editor_id = session.get('user_id')

    if not content:
        return jsonify({"status": "error", "message": "내용이 없습니다."}), 400

    try:
        # [수정] 권한 및 문서 존재 여부 확인을 위해 먼저 title을 가져옵니다.
        doc_res = supabase.table('documents').select('author_id, title').eq('id', doc_id).single().execute()
        document = doc_res.data

        if not document:
            return jsonify({"status": "error", "message": "수정할 문서를 찾을 수 없습니다."}), 404

        # 1. 'documents' 테이블의 내용을 업데이트합니다. (반환값은 사용하지 않음)
        supabase.table('documents').update({
            'content': content,
            'updated_at': 'now()'
        }).eq('id', doc_id).execute()

        # 2. 'document_logs' 테이블에 변경 이력을 삽입합니다.
        supabase.table('document_logs').insert({
            'document_id': doc_id,
            'editor_id': editor_id,
            'content': content
        }).execute()

        # 3. 바로 화면에 반영할 수 있도록 렌더링된 HTML을 생성합니다.
        rendered_html = wiki_parser(content)

        return jsonify({
            "status": "success",
            "message": "문서가 성공적으로 수정되었습니다.",
            "doc_title": document['title'],  # [수정] 기존에 조회한 문서의 title을 사용합니다.
            "rendered_html": rendered_html
        })

    except Exception as e:
        app.logger.error(f"Error updating document id {doc_id}: {e}")
        return jsonify({"status": "error", "message": "문서 수정 중 오류 발생"}), 500


# 2. [신규] 문서 수정 로그를 가져오는 API 라우트
@app.route('/api/docs/<doc_id>/history')
@login_required(role="ANY")
def get_document_history(doc_id):
    try:
        logs_res = supabase.table('document_logs').select('created_at, content, members(name)') \
            .eq('document_id', doc_id).order('created_at', desc=True).execute()

        return jsonify(logs_res.data)
    except Exception as e:
        app.logger.error(f"Error fetching history for doc id {doc_id}: {e}")
        return jsonify({"error": "로그를 불러오는 중 오류 발생"}), 500


# 6. [신규] 문서 삭제 요청을 처리하는 API 라우트
@app.route('/api/docs/delete/<doc_id>', methods=['POST'])
@login_required(role="ANY")
def handle_delete_document(doc_id):
    try:
        # 삭제 권한 확인을 위해 먼저 문서의 작성자 정보를 가져옵니다.
        doc_res = supabase.table('documents').select('author_id, title').eq('id', doc_id).single().execute()
        document = doc_res.data

        if not document:
            return jsonify({"status": "error", "message": "삭제할 문서를 찾을 수 없습니다."}), 404

        # 권한 확인: 작성자 본인이거나 관리자가 아니면 삭제 불가
        if document['author_id'] != session.get('user_id') and session.get('user_role') != 'admin':
            return jsonify({"status": "error", "message": "이 문서를 삭제할 권한이 없습니다."}), 403

        # 문서 삭제 실행
        # 'document_logs' 테이블에 ON DELETE CASCADE를 설정했기 때문에,
        # 원본 문서만 삭제해도 관련 로그가 모두 자동으로 삭제됩니다.
        supabase.table('documents').delete().eq('id', doc_id).execute()

        flash(f"'{document['title']}' 문서가 성공적으로 삭제되었습니다.", "success")
        return jsonify({"status": "success", "message": "문서가 삭제되었습니다."})

    except Exception as e:
        app.logger.error(f"Error deleting document id {doc_id}: {e}")
        return jsonify({"status": "error", "message": "문서 삭제 중 오류 발생"}), 500


#=== 마이페이지
@app.route('/mypage')
@login_required(role="ANY")
def my_page():
    user_id = session.get('user_id')
    user_name = session.get('user_name')

    try:
        # 1. 내 정보 조회
        user_res = supabase.table('members').select('*').eq('id', user_id).single().execute()
        user_data = user_res.data
        if not user_data:
            flash("사용자 정보를 찾을 수 없습니다.", "danger")
            return redirect(url_for('main_index'))

        # 2. 총 참석 횟수 집계 로직

        # 2-1. 'attendance' 테이블에서 참석 횟수 집계
        attendance_res = supabase.table('attendance').select('count', count='exact') \
            .eq('user_id', user_id).eq('attending_seminar', True).execute()
        attendance_count_new = attendance_res.count

        # 2-2. 'history' 테이블에서 과거 참석 횟수 집계
        # [수정] user_name 리스트를 json.dumps()를 사용해 json 문자열로 변환하여 전달
        history_res = supabase.table('history').select('count', count='exact') \
            .contains('present', json.dumps([user_name])).execute()
        attendance_count_old = history_res.count

        # 2-3. 두 횟수를 합산
        total_attendance_count = attendance_count_new + attendance_count_old

        # ... (나머지 코드들은 이전과 동일) ...
        question_res = supabase.table('questions').select('count', count='exact') \
            .eq('user_id', user_id).execute()
        question_count = question_res.count

        my_docs_res = supabase.table('documents').select('title') \
            .eq('author_id', user_id).order('created_at', desc=True).execute()
        my_documents = my_docs_res.data

        edited_docs_res = supabase.table('document_logs').select('document_id', count='exact') \
            .eq('editor_id', user_id).execute()
        edited_docs_count = len(set(log['document_id'] for log in edited_docs_res.data))

        return render_template(
            'my_page_member.html',
            user=user_data,
            attendance_count=total_attendance_count,
            question_count=question_count,
            my_documents=my_documents,
            edited_docs_count=edited_docs_count
        )

    except Exception as e:
        app.logger.error(f"Error loading my page for user {user_id}: {e}")
        flash("마이페이지를 불러오는 중 오류가 발생했습니다.", "danger")
        return redirect(url_for('main_index'))

# ==============================================================================
# --- 7. 서버 실행 ---
# ==============================================================================
if __name__ == '__main__':
    # --- [신규] 서버 시작 시 지원자용 빠른 접속 링크 출력 ---
    access_key = os.environ.get('APPLICANT_ACCESS_KEY')
    if access_key:
        print("\n" + "=" * 60)
        print("✅ 지원자용 빠른 접속 링크 (Applicant Quick Entry Link):")
        print(f"   http://127.0.0.1:5000/entry?key={access_key}")
        print("=" * 60 + "\n")

    app.run(host='0.0.0.0', port=5000, debug=True)
