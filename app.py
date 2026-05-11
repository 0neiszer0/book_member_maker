# --- 1. 기본 라이브러리 및 설정 ---
import os
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'
import itertools
import random
import math
from dotenv import load_dotenv
from flask import Flask, render_template, request, jsonify, session, redirect, url_for, flash, Response, send_file
import json
from supabase import create_client, Client
from datetime import datetime, timedelta, timezone, date, time
from functools import wraps
import requests
import re
import pandas as pd
import numpy as np
from ortools.sat.python import cp_model
import uuid
import mwparserfromhell
import bleach
from io import BytesIO
from docx import Document
from docx.shared import Pt, Inches
from docx.enum.text import WD_ALIGN_PARAGRAPH
from collections import defaultdict

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


# 성별 표기 정규화 (DB 표준은 'M'/'W'이지만 과거 데이터에 'F', '남'/'여' 등이 섞일 수 있음)
def normalize_gender(g):
    if g is None:
        return None
    s = str(g).strip().lower()
    if not s or s in ('nan', 'none', 'null'):
        return None
    if s in ('m', 'male', '남', '남성', '남자'):
        return 'M'
    if s in ('w', 'f', 'female', '여', '여성', '여자'):
        return 'W'
    return None


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
            # admin과 officer 역할은 모든 admin 전용 경로에 접근 가능
            user_role = session["user_role"]
            if role == "admin" and user_role not in ("admin", "officer"):
                flash("이 페이지에 접근할 권한이 없습니다.", "danger")
                return redirect(url_for('main_index'))
            elif role != "ANY" and role != "admin" and user_role != role:
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
    days_until_monday = (0 - today.weekday() + 7) % 7
    if days_until_monday == 0:
        days_until_monday = 7
    return today + timedelta(days=days_until_monday)


def get_next_seminar_dates():
    """이번 주 또는 다음 주의 월요일+목요일을 한 쌍으로 반환.
    - 오늘이 월~목 사이라면: 이번 주 월요일 + 목요일
    - 오늘이 금/토/일이라면: 다음 주 월요일 + 목요일
    """
    today = datetime.now(timezone(timedelta(hours=9))).date()
    wd = today.weekday()  # 0=월, 3=목, 4=금, ...
    # 이번 주의 월요일 (0일 전~6일 전)
    this_monday = today - timedelta(days=wd)
    this_thursday = this_monday + timedelta(days=3)
    if today <= this_thursday:  # 아직 목요일 전이면 이번 주 상당
        return sorted([this_monday, this_thursday])
    else:  # 목요일 이후(금/토/일)면 다음 주
        next_monday = this_monday + timedelta(weeks=1)
        next_thursday = next_monday + timedelta(days=3)
        return [next_monday, next_thursday]


# ==============================================================================
# --- 3. 로그인, 로그아웃, 메인 페이지 라우트 ---
# ==============================================================================

# [신규] 가장 기본이 되는 메인 페이지 라우트를 추가합니다.
@app.route('/keep-alive')
def keep_alive_endpoint():
    """
    Render 인스턴스와 Supabase를 동시에 깨우는 헬스체크 엔드포인트.
    외부 cron(GitHub Actions, cron-job.org 등)이 주기적으로 호출하면
    - Render: HTTP 요청을 받음 → 잠들지 않음
    - Supabase: 가장 가벼운 SELECT를 실행 → 비활성으로 인한 일시 정지 방지
    """
    try:
        supabase.table('members').select('id').limit(1).execute()
        return jsonify({
            "status": "ok",
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "supabase": "alive"
        }), 200
    except Exception as e:
        app.logger.error(f"keep-alive failed: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


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
    # [신규] 사용자가 누른 버튼이 '로그인'인지 '회원가입'인지 기억
    mode = request.args.get('mode', 'login')
    session['auth_mode'] = mode if mode in ('login', 'signup') else 'login'

    return redirect(login_url)


@app.route('/login/kakao/re-consent')
@login_required(role="ANY")
def kakao_reconsent_login():
    """
    사용자가 카카오 정보 제공에 다시 동의하도록 요청하는 라우트.
    """
    kakao_oauth = KakaoOauth()

    # [핵심] &prompt=consent 파라미터를 추가하여 재동의 화면을 강제로 표시
    login_url = f"https://kauth.kakao.com/oauth/authorize?client_id={kakao_oauth.client_id}&redirect_uri={kakao_oauth.redirect_uri}&response_type=code&prompt=consent"

    # 재동의 후 돌아올 페이지를 '마이페이지'로 설정
    session['next_url'] = url_for('my_page')

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
        token_info = kakao_oauth.get_token(code)
        access_token = token_info.get("access_token")
        user_info = kakao_oauth.get_user_info(access_token)

        social_id = str(user_info["id"])
        kakao_account = user_info.get("kakao_account", {})
        profile = kakao_account.get("profile", {})
        email = kakao_account.get("email")

        member_res = supabase.table("members").select("*").eq("social_id", social_id).execute()
        member = member_res.data[0] if member_res.data else None

        if member:
            # [수정] 세션 업데이트 로직 추가
            update_data = {}
            new_name = member['name']  # 기본값은 기존 이름

            if profile.get("profile_image_url"):
                update_data['profile_pic'] = profile.get("profile_image_url")

            if profile.get("nickname"):
                new_name = profile.get("nickname")
                update_data['name'] = new_name  # 닉네임도 함께 업데이트

            if update_data:
                supabase.table("members").update(update_data).eq("id", member['id']).execute()
                flash("카카오 프로필 정보가 업데이트되었습니다.", "success")
                # [핵심] DB 업데이트 후, 세션에 저장된 이름도 새로운 이름으로 갱신
                session['user_name'] = new_name

            # ... (계정 상태 및 활성 상태 체크 로직은 기존과 동일) ...
            if member.get('account_status') != 'active':
                flash("승인 대기 중입니다. 관리자가 가입/연동 요청을 확인 중입니다.", "warning")
                return redirect(url_for('login'))
            if member.get('member_status', 'active') == 'inactive':
                flash("비활성화된 계정입니다. 관리자에게 문의하세요.", "danger")
                return redirect(url_for('login'))
        else:
            # ... (신규 사용자 '계정 연결' 로직은 기존과 동일) ...
            social_data = {
                "social_id": social_id, "email": email,
                "social_name": profile.get("nickname"), "profile_pic": profile.get("profile_image_url")
            }
            session['temp_social_data'] = social_data
            return redirect(url_for('link_account_page'))

        # 세션 설정 (DB에서 읽은 최신 값으로 매번 갱신)
        session["user_id"] = member["id"]
        session["user_role"] = member["role"]
        session["user_name"] = member["name"]  # 항상 DB 최신값으로 갱신

        next_url = session.pop('next_url', None)
        if next_url:
            return redirect(next_url)
        if member["role"] in ("admin", "officer"):
            return redirect(url_for("admin_dashboard"))
        return redirect(url_for("my_page"))

    except Exception as e:
        flash("카카오 로그인 중 오류가 발생했습니다.", "danger")
        app.logger.error(f"Kakao callback error: {e}", exc_info=True)
        return redirect(url_for("login"))


@app.route('/link_account')
def link_account_page():
    # kakao_callback에서 임시 저장한 소셜 데이터가 없으면 로그인 페이지로
    if 'temp_social_data' not in session:
        return redirect(url_for('login'))

    social_data = session['temp_social_data']
    auth_mode = session.get('auth_mode', 'login')

    # [신규] 카카오 닉네임으로 미연결 멤버 자동 매칭
    # 동명이인 가능성 고려해 결과 0건 / 1건 / 2건 이상으로 분기
    matched_member = None
    multiple_matches = []
    nickname = (social_data.get('social_name') or '').strip()
    if nickname:
        try:
            res = supabase.table("members").select("id,name,student_id,profile_pic")\
                .eq("name", nickname)\
                .or_("social_id.is.null,social_id.eq.").execute()
            rows = res.data or []
            if len(rows) == 1:
                matched_member = rows[0]
            elif len(rows) > 1:
                multiple_matches = rows
        except Exception as e:
            app.logger.warning(f"link_account auto-match failed: {e}")

    return render_template('link_account.html',
                           **social_data,
                           auth_mode=auth_mode,
                           matched_member=matched_member,
                           multiple_matches=multiple_matches)


@app.route('/link_account', methods=['POST'])
def link_account_submit():
    if 'temp_social_data' not in session:
        return redirect(url_for('login'))

    form = request.form
    action = form.get('action')
    social_info = session['temp_social_data']

    member = None
    if action == 'link':
        existing_name = form.get('existing_name', '').strip()
        student_id = form.get('student_id', '').strip()
        if not existing_name:
            flash("기존 활동명을 입력해주세요.", "danger")
            return redirect(url_for('link_account_page'))

        member_res = supabase.table("members").select("*").eq("name", existing_name)\
            .or_("social_id.is.null,social_id.eq.").execute()
        member_to_link = member_res.data[0] if member_res.data else None

        if member_to_link:
            # 학번음 입력했고 DB 학번과 일치하면 자동 승인
            db_student_id = member_to_link.get('student_id')
            auto_approve = student_id and db_student_id and str(student_id).strip() == str(db_student_id).strip()

            update_data = {
                "social_id": social_info['social_id'],
                "profile_pic": social_info['profile_pic'],
                "account_status": 'active' if auto_approve else 'pending',
                "is_active": True if auto_approve else member_to_link.get('is_active', False)
            }
            # 이메일이 있고, 현재 멤버가 사용 중인 이메일이 아닌 경우에만 업데이트
            # (다른 멤버가 이미 같은 이메일을 사용 중이면 UNIQUE 제약 위반 방지)
            kakao_email = social_info.get('email')
            if kakao_email:
                email_conflict = supabase.table("members").select("id").eq("email", kakao_email).neq("id", member_to_link['id']).execute()
                if not email_conflict.data:
                    update_data["email"] = kakao_email
                else:
                    app.logger.warning(f"이메일 {kakao_email}이 이미 다른 멤버에게 사용 중 — 이메일 업데이트 생략")
            updated_member_response = supabase.table("members").update(update_data).eq("id", member_to_link['id']).execute()
            member = updated_member_response.data[0]

            if auto_approve:
                # 세션 설정 및 자동 로그인
                session.pop('temp_social_data', None)
                session['user_id'] = member['id']
                session['user_name'] = member['name']
                session['user_role'] = member.get('role', 'member')
                session['profile_pic'] = member.get('profile_pic', '')
                flash(f"학번 확인이 완료되었습니다. {member['name']}님, 환영합니다!", "success")
                return redirect(url_for('my_page'))
            else:
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





@app.route('/api/attendance', methods=['POST'])
@login_required(role="ANY")
def update_attendance():
    data = request.json
    user_id = session.get('user_id')
    # 클라이언트가 특정 날짜를 보내면 해당 날짜, 아니면 다음 월요일 fallback
    meeting_date = data.get('meeting_date') or get_next_monday().isoformat()
    try:
        supabase.table('attendance').upsert({
            'user_id': user_id,
            'meeting_date': meeting_date,
            'attending_seminar': data.get('attending_seminar'),
            'attending_afterparty': data.get('attending_afterparty', False)
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
        next_monday = get_next_monday()
    except Exception:
        next_monday = None

    try:
        events_res = supabase.table('events').select('*').order('created_at', desc=True).execute().data

        # 기존 demerit_points 및 interviewer 쿼리 제거
        # department 컬럼이 DB에 없어 발생하는 42703 오류를 임시로 방지하기 위해 쿼리에서 제거
        all_members_res = supabase.table('members').select(
            'id, name, is_active, member_status, role, email, department, gender, student_id, recruiting_class'
        ).order('name').execute().data

        # 생성된 발제문 취합 이벤트 목록 불러오기
        topic_events_res = supabase.table('topic_events').select('*').order('created_at', desc=True).execute()
        topic_events = topic_events_res.data

        # 세미나 출석 투표 학기 목록
        seminar_terms_res = supabase.table('seminar_terms').select('*') \
            .order('start_date', desc=True).execute()
        seminar_terms = seminar_terms_res.data or []
        # 회차 수 카운트
        if seminar_terms:
            term_ids = [t['id'] for t in seminar_terms]
            sess_counts_res = supabase.table('seminar_sessions').select('term_id') \
                .in_('term_id', term_ids).execute()
            counts = {}
            for row in (sess_counts_res.data or []):
                counts[row['term_id']] = counts.get(row['term_id'], 0) + 1
            for t in seminar_terms:
                t['session_count'] = counts.get(t['id'], 0)
                t['share_url'] = f"{request.host_url}seminar_vote?token={t['share_token']}"

    except Exception as e:
        flash(f"대시보드 로딩 중 오류 발생: {e}", "danger")
        events_res, all_members_res = [], []
        topic_events = []
        seminar_terms = []

    return render_template(
        'admin_dashboard.html',
        events=events_res,
        all_members=all_members_res,
        meeting_date=next_monday,
        topic_events=topic_events,
        seminar_terms=seminar_terms,
    )





@app.route('/api/admin/members/<int:member_id>/set_status', methods=['POST'])
@login_required(role="admin")
def set_member_status(member_id):
    """관리자가 특정 멤버의 상태를 active / dormant / inactive 중 하나로 설정합니다."""
    data = request.json
    new_status = data.get('member_status')
    if new_status not in ('active', 'dormant', 'inactive'):
        return jsonify({"status": "error", "message": "유효하지 않은 상태입니다."}), 400
    try:
        if member_id == session.get('user_id') and new_status == 'inactive':
            return jsonify({"status": "error", "message": "자기 자신을 비활성화할 수 없습니다."}), 403
        supabase.table('members').update({
            'member_status': new_status,
            'is_active': new_status == 'active'  # 하위 호환성 유지
        }).eq('id', member_id).execute()
        return jsonify({"status": "success", "message": "멤버 상태가 변경되었습니다."})
    except Exception as e:
        app.logger.error(f"Error setting member status for {member_id}: {e}")
        return jsonify({"status": "error", "message": "상태 변경 중 오류 발생"}), 500


@app.route('/api/admin/members/create', methods=['POST'])
@login_required(role="admin")
def create_member():
    """관리자가 새 멤버를 등록합니다."""
    data = request.json
    try:
        name = data.get('name', '').strip()
        if not name:
            return jsonify({"status": "error", "message": "이름은 필수입니다."}), 400
        supabase.table('members').insert({
            'name': name,
            'email': data.get('email', ''),
            'gender': data.get('gender', ''),
            'role': data.get('role', 'member'),
            'member_status': 'active',
            'is_active': True,
            'account_status': 'active'
        }).execute()
        return jsonify({"status": "success", "message": f"{name} 멤버가 추가되었습니다."})
    except Exception as e:
        app.logger.error(f"Error creating member: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/admin/members/<int:member_id>/edit', methods=['POST'])
@login_required(role="admin")
def edit_member(member_id):
    """관리자가 멤버 정보를 편집합니다."""
    data = request.json
    try:
        update_fields = {}
        for field in ('name', 'email', 'gender', 'role', 'department', 'student_id', 'recruiting_class'):
            if field in data:
                val = data[field]
                if isinstance(val, str) and val.strip() == '':
                    update_fields[field] = None  # 빈 문자열은 NULL로
                else:
                    update_fields[field] = val
        if not update_fields:
            return jsonify({"status": "error", "message": "변경할 내용이 없습니다."}), 400
        supabase.table('members').update(update_fields).eq('id', member_id).execute()
        return jsonify({"status": "success", "message": "멤버 정보가 수정되었습니다."})
    except Exception as e:
        app.logger.error(f"Error editing member {member_id}: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/admin/members/<int:member_id>/delete', methods=['POST'])
@login_required(role="admin")
def delete_member(member_id):
    """관리자가 멤버를 삭제합니다."""
    try:
        if member_id == session.get('user_id'):
            return jsonify({"status": "error", "message": "자기 자신을 삭제할 수 없습니다."}), 403
        supabase.table('members').delete().eq('id', member_id).execute()
        return jsonify({"status": "success", "message": "멤버가 삭제되었습니다."})
    except Exception as e:
        app.logger.error(f"Error deleting member {member_id}: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/admin/members/merge', methods=['POST'])
@login_required(role="admin")
def merge_members():
    """두 멤버를 하나로 합칩니다.
    예: '민수'(성 빠짐) → '김민수' 로 모든 활동 이력 이전 후 source 삭제.
    body: {source_id: int, target_id: int}
    """
    try:
        data = request.json or {}
        source_id = int(data.get('source_id'))
        target_id = int(data.get('target_id'))
        if source_id == target_id:
            return jsonify({"status": "error", "message": "같은 멤버입니다."}), 400
        if source_id == session.get('user_id'):
            return jsonify({"status": "error", "message": "자기 자신을 source 로 지정할 수 없습니다."}), 403

        # 두 멤버 모두 존재해야 함
        both = supabase.table('members').select('id, name, social_id, email').in_('id', [source_id, target_id]).execute().data or []
        if len(both) != 2:
            return jsonify({"status": "error", "message": "멤버를 찾을 수 없습니다."}), 404
        source_row = next(m for m in both if m['id'] == source_id)
        target_row = next(m for m in both if m['id'] == target_id)

        # 카카오 로그인 정보(social_id/email)를 target 으로 이전.
        # target 에 이미 값이 있으면 덮어쓰지 않음. source 의 값은 unique 충돌 방지를 위해 먼저 NULL 처리.
        login_transfer = {}
        if (source_row.get('social_id') or '').strip() and not (target_row.get('social_id') or '').strip():
            login_transfer['social_id'] = source_row['social_id']
        if (source_row.get('email') or '').strip() and not (target_row.get('email') or '').strip():
            login_transfer['email'] = source_row['email']
        if login_transfer:
            # source 에서 먼저 비워서 unique 충돌 방지
            supabase.table('members').update({
                k: None for k in login_transfer.keys()
            }).eq('id', source_id).execute()
            # target 으로 이전
            supabase.table('members').update(login_transfer).eq('id', target_id).execute()

        # (table, column, conflict_columns) — conflict_columns 가 있으면 unique 충돌 시 source 행 삭제
        moves = [
            ('attendance', 'user_id', ['user_id', 'meeting_date']),
            ('seminar_votes', 'member_id', ['session_id', 'member_id']),
            ('brick_session_members', 'member_id', ['session_id', 'member_id']),
            ('study_session_members', 'member_id', ['session_id', 'member_id']),
            ('special_event_attendees', 'member_id', ['event_id', 'member_id']),
        ]
        moved_summary = {}
        for table, col, conflict_cols in moves:
            try:
                source_rows = supabase.table(table).select(','.join(['id'] + conflict_cols)) \
                    .eq(col, source_id).execute().data or []
                if not source_rows:
                    moved_summary[table] = 0
                    continue
                # target 이 이미 갖고 있는 conflict_cols 조합 조회
                other_col = [c for c in conflict_cols if c != col][0]
                other_vals = list({r[other_col] for r in source_rows})
                target_existing_res = supabase.table(table).select(other_col) \
                    .eq(col, target_id).in_(other_col, other_vals).execute().data or []
                target_has = {r[other_col] for r in target_existing_res}

                to_delete_ids = [r['id'] for r in source_rows if r[other_col] in target_has]
                to_update_ids = [r['id'] for r in source_rows if r[other_col] not in target_has]

                if to_delete_ids:
                    supabase.table(table).delete().in_('id', to_delete_ids).execute()
                if to_update_ids:
                    supabase.table(table).update({col: target_id}).in_('id', to_update_ids).execute()
                moved_summary[table] = {'updated': len(to_update_ids), 'deleted_dup': len(to_delete_ids)}
            except Exception as e:
                app.logger.warning(f"merge_members move {table} 실패: {e}")
                moved_summary[table] = f"error: {e}"

        # set null 계열: special_events.created_by — source 가 만든 이벤트는 target 으로 이전
        try:
            supabase.table('special_events').update({'created_by': target_id}) \
                .eq('created_by', source_id).execute()
        except Exception as e:
            app.logger.warning(f"merge_members special_events.created_by 실패: {e}")

        # 마지막으로 source 삭제
        supabase.table('members').delete().eq('id', source_id).execute()

        return jsonify({
            "status": "success",
            "message": "멤버가 합쳐졌습니다.",
            "moved": moved_summary,
            "login_transferred": login_transfer,
        })
    except Exception as e:
        app.logger.error(f"merge_members error: {e}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500


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

@app.route('/api/admin/slots/delete_bulk', methods=['POST'])
@login_required(role="admin")
def delete_bulk_slots():
    """관리자가 여러 시간 슬롯을 한 번에 삭제합니다."""
    data = request.get_json()
    slot_ids = data.get('slot_ids')

    if not slot_ids or not isinstance(slot_ids, list):
        return jsonify({'status': 'error', 'message': '슬롯 ID 목록이 필요합니다.'}), 400

    try:
        # 1. Foreign Key 제약 조건을 위해 연결된 '예약'을 먼저 삭제합니다.
        supabase.table('reservations').delete().in_('slot_id', slot_ids).execute()

        # 2. 이제 '시간 슬롯'을 삭제합니다.
        result = supabase.table('time_slots').delete().in_('id', slot_ids).execute()

        if not result.data:
            return jsonify({'status': 'error', 'message': '삭제할 슬롯을 찾을 수 없거나 이미 삭제되었습니다.'}), 404

        return jsonify({'status': 'success', 'message': f'{len(result.data)}개의 슬롯이 성공적으로 삭제되었습니다.'})
    except Exception as e:
        app.logger.error(f"Error deleting bulk slots: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


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

        # 3. 템플릿 렌더링 시도
        app.logger.info("render_template 호출 직전...")
        app.logger.info(
            f"전달할 데이터: event={event_data}, event_id={event_data['id']}")

        return render_template(
            'timetable_view.html',
            event=event_data,
            event_id=event_data['id'],
            user_role=session['user_role'],
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
    """[수정] 각 슬롯이 현재 시간보다 과거인지 판별하는 is_past 플래그를 추가합니다."""
    app.logger.info(f"--- 타임테이블 데이터 요청 시작 (Event ID: {event_id}) ---")
    try:
        response_slots = supabase.table('time_slots').select('*').eq('event_id', event_id).order(
            'slot_datetime').execute()
        slots_res = response_slots.data if hasattr(response_slots, 'data') and response_slots.data else []

        # [추가] 현재 시간을 UTC 기준으로 설정
        now_utc = datetime.now(timezone.utc)

        # interviewer 쿼리 제거 (해결)
        booked_slot_ids = [s['id'] for s in slots_res if s['is_booked']]

        reservations_data = []
        if booked_slot_ids:
            response_reservations = supabase.table('reservations').select('slot_id, applicant_id').in_('slot_id',
                                                                                                       booked_slot_ids).execute()
            reservations_data = response_reservations.data if hasattr(response_reservations,
                                                                      'data') and response_reservations.data else []

        applicant_ids_to_fetch = {r['applicant_id'] for r in reservations_data}
        applicants_data = []
        if applicant_ids_to_fetch:
            response_applicants = supabase.table('applicants').select('*').in_('id',
                                                                               list(applicant_ids_to_fetch)).execute()
            applicants_data = response_applicants.data if hasattr(response_applicants,
                                                                  'data') and response_applicants.data else []

        applicants_map = {a['id']: a for a in applicants_data}
        reservation_map = {r['slot_id']: r['applicant_id'] for r in reservations_data}

        for slot in slots_res:
            if slot.get('slot_datetime'):
                slot['time_display'] = format_datetime_filter(slot['slot_datetime'], format_str="%p %I:%M")
                # [추가] is_past 플래그 계산
                slot_dt_utc = datetime.fromisoformat(slot['slot_datetime'].replace('Z', '+00:00'))
                slot['is_past'] = slot_dt_utc < now_utc
            if slot['id'] in reservation_map:
                applicant_id = reservation_map[slot['id']]
                slot['applicant'] = applicants_map.get(applicant_id)

        return jsonify(slots_res)

    except Exception as e:
        app.logger.error(f"!!! get_timetable_data 함수에서 오류 발생: {e}", exc_info=True)
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
    [최종 수정] '확장형' 클러스터링 로직
    1. 기존에 관리자가 열어둔 슬롯은 절대 닫지 않음 (deactivate 로직 제거).
    2. 예약이 발생하면, 그 슬롯의 '같은 날짜'인 앞/뒤 슬롯만 추가로 엽니다.
    """
    try:
        # 시간순으로 슬롯 정렬하여 가져오기
        all_slots_res = supabase.table('time_slots') \
            .select('id, slot_datetime, is_booked, is_active') \
            .eq('event_id', event_id) \
            .order('slot_datetime') \
            .execute()

        all_slots = all_slots_res.data
        if not all_slots:
            return


        slots_to_activate = set()

        for i, current_slot in enumerate(all_slots):
            # 예약된 슬롯을 찾습니다.
            if current_slot['is_booked']:

                # 현재 슬롯의 날짜를 파악 (문자열 앞 10자리 YYYY-MM-DD 비교)
                current_date_str = current_slot['slot_datetime'][:10]

                # 1. 이전 슬롯 확인 (존재하는 경우)
                if i > 0:
                    prev_slot = all_slots[i - 1]
                    prev_date_str = prev_slot['slot_datetime'][:10]

                    # [조건] 날짜가 같고, 현재 닫혀있고, 예약이 안 된 상태라면 -> 열기 목록에 추가
                    if current_date_str == prev_date_str:
                        if not prev_slot['is_active'] and not prev_slot['is_booked']:
                            slots_to_activate.add(prev_slot['id'])

                # 2. 다음 슬롯 확인 (존재하는 경우)
                if i < len(all_slots) - 1:
                    next_slot = all_slots[i + 1]
                    next_date_str = next_slot['slot_datetime'][:10]

                    # [조건] 날짜가 같고, 현재 닫혀있고, 예약이 안 된 상태라면 -> 열기 목록에 추가
                    if current_date_str == next_date_str:
                        if not next_slot['is_active'] and not next_slot['is_booked']:
                            slots_to_activate.add(next_slot['id'])

        # 찾아낸 '열어야 할 슬롯'들만 활성화 (이미 열려있는 건 건드리지 않음)
        if slots_to_activate:
            supabase.table('time_slots').update({'is_active': True}).in_('id', list(slots_to_activate)).execute()
            app.logger.info(f"Event {event_id}: Additional slots activated: {len(slots_to_activate)}")
        else:
            app.logger.info(f"Event {event_id}: No additional slots needed activation.")

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


# app.py의 handle_notification 함수를 아래 코드로 교체

@app.route('/api/notifications/<int:notif_id>/handle', methods=['POST'])
@login_required(role="admin")
def handle_notification(notif_id):
    data = request.json
    action = data.get('action')  # 'approve' or 'deny'

    if action not in ['approve', 'deny']:
        return jsonify({"error": "Invalid action"}), 400

    try:
        # 1. 알림 정보를 먼저 조회
        notification_to_handle_res = supabase.table('notifications').select('related_member_id, type') \
            .eq('id', notif_id).single().execute()

        notification_to_handle = notification_to_handle_res.data
        if not notification_to_handle:
            return jsonify({"error": "Notification not found"}), 404

        member_id = notification_to_handle.get('related_member_id')
        notif_type = notification_to_handle.get('type')

        # 2. 알림의 상태를 'approved' 또는 'denied'로 업데이트
        supabase.table('notifications').update({
            'status': 'approved' if action == 'approve' else 'denied'
        }).eq('id', notif_id).execute()

        # 3. 알림 유형에 따라 후속 조치 실행
        if member_id:
            # 가입 또는 계정 연결 요청 처리
            if notif_type in ['new_user_request', 'account_link_request']:
                if action == 'approve':
                    supabase.table('members').update({'account_status': 'active'}).eq('id', member_id).execute()
                elif action == 'deny':
                    if notif_type == 'account_link_request':
                        # 연결 거절 시: 다시 시도할 수 있도록 social_id 해제 및 상태 원복
                        supabase.table('members').update({
                            'social_id': None, 
                            'account_status': 'active'
                        }).eq('id', member_id).execute()
                    elif notif_type == 'new_user_request':
                        # 신규 가입 거절 시: 임시로 생성된 pending 멤버 레코드 자체를 삭제하여 재가입 가능하도록 함
                        supabase.table('members').delete().eq('id', member_id).execute()

            # 불참 요청 처리
            elif notif_type == 'absence_request':
                next_monday = get_next_monday()

                # [핵심 수정] update_data를 정의하고, where 절을 명확하게 지정하여 업데이트
                if action == 'approve':
                    # 불참 승인: 불참 확정 및 상태 변경
                    update_data = {
                        'absence_request_status': 'approved',
                        'attending_seminar': False
                    }
                else:  # action == 'deny'
                    # 불참 반려: 요청 상태만 변경
                    update_data = {
                        'absence_request_status': 'denied'
                    }

                # 업데이트할 행을 명확하게 지정
                supabase.table('attendance').update(update_data) \
                    .eq('user_id', member_id) \
                    .eq('meeting_date', next_monday.isoformat()) \
                    .eq('absence_request_status', 'pending') \
                    .execute()

        return jsonify({"status": "success", "message": f"요청이 {action}되었습니다."})

    except Exception as e:
        app.logger.error(f"Error handling notification {notif_id}: {e}")
        return jsonify({"error": str(e)}), 500


# --- 4.2. 독서 모임 조 편성 (관리자 전용) ---


@app.route('/making_team', methods=['GET'])
@login_required(role="admin")
def bookclub_index():
    app.logger.info("---/making_team 경로 함수 실행 시작---")
    # 어느 요일 기준으로 조 편성할지 (월/목 분리). 기본은 '월'.
    day_choice = (request.args.get('day') or 'mon').lower()
    if day_choice not in ('mon', 'thu', 'all'):
        day_choice = 'mon'

    mon_attendee_ids: set = set()
    thu_attendee_ids: set = set()
    mon_date_iso = ''
    thu_date_iso = ''

    try:
        seminar_dates = get_next_seminar_dates()  # [월요일, 목요일] (혹은 비슷한 묶음)
        app.logger.info(f"[1] 다음 세미나 날짜: {[d.isoformat() for d in seminar_dates]}")
        for d in seminar_dates:
            wd = d.weekday()  # 월=0, 목=3
            if wd == 0:
                mon_date_iso = d.isoformat()
            elif wd == 3:
                thu_date_iso = d.isoformat()

        # 1. 모든 활성 멤버 목록.
        all_active_members_res = supabase.table("members").select("id, name") \
            .eq('is_active', True).order("name").execute()
        all_active_members = all_active_members_res.data
        app.logger.info(f"[2] DB에서 가져온 전체 활성 멤버 수: {len(all_active_members)}명")

        # 2. attendance 테이블 - 날짜별로 분리해서 집계
        date_strs = [d.isoformat() for d in seminar_dates]
        if date_strs:
            attendance_res = supabase.table('attendance').select('user_id, meeting_date') \
                .in_('meeting_date', date_strs) \
                .eq('attending_seminar', True) \
                .execute()
            for row in (attendance_res.data or []):
                md = row.get('meeting_date')
                if md == mon_date_iso:
                    mon_attendee_ids.add(row['user_id'])
                elif md == thu_date_iso:
                    thu_attendee_ids.add(row['user_id'])

        # 3. seminar_votes도 day_type별로 분리
        try:
            sess_res = supabase.table('seminar_sessions') \
                .select('id, meeting_date, day_type') \
                .in_('meeting_date', date_strs).eq('is_active', True).execute()
            sess_rows = sess_res.data or []
            mon_sess_ids = [s['id'] for s in sess_rows if s.get('day_type') == 'mon']
            thu_sess_ids = [s['id'] for s in sess_rows if s.get('day_type') == 'thu']
            if mon_sess_ids:
                v = supabase.table('seminar_votes').select('member_id') \
                    .in_('session_id', mon_sess_ids).eq('attending', True).execute()
                mon_attendee_ids |= {x['member_id'] for x in (v.data or [])}
            if thu_sess_ids:
                v = supabase.table('seminar_votes').select('member_id') \
                    .in_('session_id', thu_sess_ids).eq('attending', True).execute()
                thu_attendee_ids |= {x['member_id'] for x in (v.data or [])}
        except Exception as e:
            app.logger.warning(f"seminar_votes 통합 실패 (무시 가능): {e}")

        # 4. day_choice 에 따라 pre_checked 결정
        if day_choice == 'mon':
            pre_checked_attendee_ids = mon_attendee_ids
        elif day_choice == 'thu':
            pre_checked_attendee_ids = thu_attendee_ids
        else:  # 'all'
            pre_checked_attendee_ids = mon_attendee_ids | thu_attendee_ids
        app.logger.info(f"[5] day={day_choice}, 미리 체크될 참석자 수: {len(pre_checked_attendee_ids)}명 (월 {len(mon_attendee_ids)} / 목 {len(thu_attendee_ids)})")

    except Exception as e:
        app.logger.error(f"!!! /making_team 경로에서 오류 발생: {e}", exc_info=True)
        flash(f"데이터를 불러오는 중 오류가 발생했습니다: {e}", "danger")
        all_active_members = []
        pre_checked_attendee_ids = set()

    return render_template(
        'bookclub_index.html',
        all_members=all_active_members,
        pre_checked_attendee_ids=pre_checked_attendee_ids,
        mon_attendee_ids=mon_attendee_ids,
        thu_attendee_ids=thu_attendee_ids,
        mon_date=mon_date_iso,
        thu_date=thu_date_iso,
        day_choice=day_choice,
    )


@app.route('/start_group_generation')
@login_required(role="admin")
def start_group_generation():
    # --- [수정] 로그 추가 ---
    app.logger.info("\n---/start_group_generation 경로 함수 실행 시작---")
    present_names = request.args.getlist('present')
    facilitator_names = request.args.getlist('facilitators')
    group_count_str = request.args.get('group_count')
    group_names_str = request.args.get('group_names', '')
    app.logger.info(f"[1] 전달받은 참석자 명단 (총 {len(present_names)}명): {present_names}")
    app.logger.info(f"[2] 전달받은 발제자 명단: {facilitator_names}")
    app.logger.info(f"[3] 전달받은 그룹 수: '{group_count_str}'")
    # --- [수정 끝] ---

    manual_entry_url = url_for('manual_entry')

    def generate_events(manual_url):
        try:
            app.logger.info("[4] DB에서 전체 회원 및 히스토리 데이터 로드 시작")
            members_res = supabase.table("members").select("*").order("name").execute().data
            members_df = pd.DataFrame(members_res)
            history_res = supabase.table("history").select("groups").execute().data
            history_df = pd.DataFrame(history_res if history_res else [])
            app.logger.info(f"[5] 데이터 로드 완료: 회원 {len(members_df)}명, 히스토리 {len(history_df)}건")

            group_count_override = None
            if group_count_str and group_count_str.isdigit():
                group_count_override = int(group_count_str)

            # co_matrix 로드
            co_matrix_res = supabase.table("bookclub_co_matrix").select("pair_key, count").execute()
            co_matrix = {r['pair_key']: r['count'] for r in (co_matrix_res.data or [])}
            app.logger.info(f"[6] co_matrix {len(co_matrix)}개 항목 로드 완료")

            yield f"event: progress\ndata: {json.dumps({'progress': 10})}\n\n"

            app.logger.info("[7] '종합 최적화(단일)' CP-SAT 알고리즘 실행 시작")

            # 솔버를 별도 스레드에서 돌리고, 진행률을 큐를 통해 실시간 스트리밍
            import threading, queue
            progress_queue = queue.Queue()

            def progress_callback(pct):
                try:
                    progress_queue.put(('progress', pct))
                except Exception:
                    pass

            solver_result = {'solutions': None, 'error': None}

            def run_solver():
                try:
                    solver_result['solutions'] = run_cp_grouping(
                        members_df, co_matrix, present_names, facilitator_names,
                        optimize_for='combined', top_n=12,
                        group_count_override=group_count_override,
                        progress_callback=progress_callback
                    )
                except Exception as ex:
                    solver_result['error'] = ex
                finally:
                    progress_queue.put(('done', None))

            t = threading.Thread(target=run_solver, daemon=True)
            t.start()

            # 큐를 폴링하면서 진행률을 실시간 yield
            last_sent_pct = 10
            while True:
                try:
                    kind, payload = progress_queue.get(timeout=30)
                except queue.Empty:
                    # heartbeat (SSE 연결 유지)
                    yield ": keep-alive\n\n"
                    continue
                if kind == 'progress':
                    if payload > last_sent_pct:
                        last_sent_pct = payload
                        yield f"event: progress\ndata: {json.dumps({'progress': payload})}\n\n"
                elif kind == 'done':
                    break

            t.join()
            if solver_result['error']:
                raise solver_result['error']
            combined_solutions = solver_result['solutions'] or []
            app.logger.info(f"[8] '종합 최적화' 완료, {len(combined_solutions)}개")

            yield f"event: progress\ndata: {json.dumps({'progress': 90})}\n\n"

            # 결과 페이지에서 'M'/'W'로 비교하므로 정규화된 값으로 전달
            member_genders = {
                row['name']: normalize_gender(row.get('gender'))
                for row in members_df.to_dict(orient='records')
            }

            meeting_history = {}
            # co_matrix에서 last_met도 함께 가져와서 {count, last_met} 형태로 저장
            matrix_res = supabase.table('bookclub_co_matrix').select('pair_key, count, last_met').execute()
            for row in (matrix_res.data or []):
                if row.get('count', 0) > 0:
                    meeting_history[row['pair_key']] = {
                        'count': row['count'],
                        'last_met': row.get('last_met', '')
                    }

            app.logger.info("[10] 최종 결과 페이지(HTML) 렌더링 시작")
            with app.app_context():
                group_names = [name.strip() for name in group_names_str.split(',') if name.strip()]
                final_html = render_template(
                    'bookclub_ga_results.html',
                    combined_solutions=combined_solutions,
                    present=present_names,
                    facilitators=facilitator_names,
                    group_names=group_names,
                    meeting_history=meeting_history,
                    member_genders=member_genders,
                    manual_entry_url=manual_url
                )
                complete_data = json.dumps({'html': final_html})
                yield f"event: complete\ndata: {complete_data}\n\n"
            app.logger.info("[11] 성공적으로 최종 HTML을 브라우저로 전송 완료")

        except Exception as e:
            app.logger.error(f"!!! 조 편성 중 심각한 오류 발생: {e}", exc_info=True)
            error_data = json.dumps({'error': str(e)})
            yield f"event: error\ndata: {error_data}\n\n"

    return Response(generate_events(manual_entry_url), mimetype='text/event-stream')



def run_cp_grouping(members_df, co_matrix, attendee_names, presenter_names,
                    optimize_for='gender', top_n=10, group_count_override=None,
                    progress_callback=None):
    """
    OR-Tools CP-SAT 기반 조 편성 알고리즘.
    optimize_for: 'gender' (성비우선) or 'new_face' (새만남우선)
    top_n: 반환할 다양한 조합 수
    """
    app.logger.info(f"[CP-SAT] 시작: optimize_for={optimize_for}, top_n={top_n}, attendees={len(attendee_names)}")

    names = list(attendee_names)
    n = len(names)

    if n < 3:
        app.logger.warning("[CP-SAT] 참석자 3명 미만, 중단")
        return []

    # 멤버 정보 딕셔너리
    name_to_info = {}
    for _, row in members_df.iterrows():
        name_to_info[row['name']] = row.to_dict()

    # 그룹 수 결정
    MIN_GROUP_SIZE = 4
    if group_count_override and group_count_override > 0:
        num_groups = group_count_override
    else:
        q, r = divmod(n, 4)
        num_groups = q if r == 0 else q + 1
    # 모든 그룹이 최소 MIN_GROUP_SIZE명 이상 가질 수 있도록 그룹 수 상한선 적용
    num_groups = max(1, min(num_groups, n // MIN_GROUP_SIZE))

    min_size = MIN_GROUP_SIZE
    max_size = math.ceil(n / num_groups)  # +1 제거: 일부 조에 여유 생갈 경우 3인조 발생 방지

    app.logger.info(f"[CP-SAT] 그룹={num_groups}, 크기={min_size}~{max_size}")

    # 성별 정규화: 미상은 별도 카테고리로 두어 자동으로 여성에 합산되지 않도록 함.
    is_male_arr = []   # 1 if 남성 else 0
    is_female_arr = [] # 1 if 여성 else 0
    for name in names:
        info = name_to_info.get(name, {})
        norm = normalize_gender(info.get('gender'))
        is_male_arr.append(1 if norm == 'M' else 0)
        is_female_arr.append(1 if norm == 'W' else 0)
    # 하위호환을 위해 genders도 유지 (기존 변수 참조 자리)
    genders = is_male_arr

    # 발제자 인덱스
    presenter_set = set(presenter_names)
    presenter_indices = [i for i, nm in enumerate(names) if nm in presenter_set]

    # 쌍별 만남 횟수
    def get_pair_count(a, b):
        key = '-'.join(sorted([a, b]))
        return co_matrix.get(key, 0)

    # objective 계산을 위한 쌍 사전
    pair_counts = {}
    for i in range(n):
        for j in range(i + 1, n):
            pair_counts[(i, j)] = get_pair_count(names[i], names[j])

    SCALE = 1000
    results = []
    # 金지 조합: 이미 찾은 조합들 (각각 frozenset of frozensets)
    found_groupings = []

    for attempt in range(top_n * 2): # 최대 탐색 횟수 조정
        if len(results) >= top_n:
            break

        model = cp_model.CpModel()

        # x[i][g]: 멤버 i가 그룹 g에 소속
        x = [[model.NewBoolVar(f'x_{i}_{g}') for g in range(num_groups)] for i in range(n)]

        # --- [대칭성 파괴(Symmetry Breaking)] ---
        # 첫 번째 사람을 무조건 그룹 0에 넣음으로써 불필요한 자리바꿈 탐색 공간을 기하급수적으로 줄임
        if n > 0 and num_groups > 0:
            model.Add(x[0][0] == 1)

        # 각 멤버는 정확히 하나의 그룹
        for i in range(n):
            model.AddExactlyOne(x[i][g] for g in range(num_groups))

        # 그룹 크기 제약
        for g in range(num_groups):
            sz = sum(x[i][g] for i in range(n))
            model.Add(sz >= min_size)
            model.Add(sz <= max_size)

        # 발제자 분산: 그룹 수 >= 발제자 수일 때 각 그룹에 1명씩
        if len(presenter_indices) <= num_groups:
            for pi in range(len(presenter_indices)):
                for pj in range(pi + 1, len(presenter_indices)):
                    for g in range(num_groups):
                        model.Add(x[presenter_indices[pi]][g] + x[presenter_indices[pj]][g] <= 1)

        # 이전에 찾은 조합 금지: 동일한 pair grouping을 피하기 위해
        for attempt_idx, found_pairs in enumerate(found_groupings):
            if not found_pairs:
                continue
            same_g_vars = []
            for (i, j) in found_pairs:
                for g in range(num_groups):
                    b = model.NewBoolVar(f'f_{attempt_idx}_{i}_{j}_{g}')
                    # x[i][g] == 1 and x[j][g] == 1 이면 b >= 1 이어야 함
                    model.Add(x[i][g] + x[j][g] - 1 <= b)
                    same_g_vars.append(b)
            # 이전에 같은 그룹이었던 쌍들 중 무조건 하나 이상은 이번엔 다른 그룹이어야 함
            if same_g_vars:
                model.Add(sum(same_g_vars) <= len(found_pairs) - 1)

        # --- 목적함수 ---
        obj = []

        # 성비 점수: 각 그룹 내 성별 불균형(|남-여|)을 최소화.
        # 성별 미상자는 어느 쪽으로도 카운트하지 않아 결과 왜곡을 막음.
        for g in range(num_groups):
            males = model.NewIntVar(0, n, f'm_{g}')
            model.Add(males == sum(is_male_arr[i] * x[i][g] for i in range(n)))
            females = model.NewIntVar(0, n, f'f_{g}')
            model.Add(females == sum(is_female_arr[i] * x[i][g] for i in range(n)))
            diff = model.NewIntVar(-n, n, f'd_{g}')
            model.Add(diff == males - females)
            abs_diff = model.NewIntVar(0, n, f'ad_{g}')
            model.AddAbsEquality(abs_diff, diff)
            gender_w = 40 if optimize_for in ['gender', 'combined'] else 6
            obj.append(abs_diff * (-SCALE * gender_w))

        # 새만남 점수 (최적화 변환): 
        # 기존: 모든 쌍에 대해 보너스를 주는 방식 (O(N^2) 변수 생성)
        # 변경: 이미 만난 1~2단계 쌍에 대해서만 '페널티(loss)'를 부과 (O(E) 90% 이상 변수 축소)
        new_face_w = 10 if optimize_for in ['new_face', 'combined'] else 6
        max_nf_val = SCALE * new_face_w
        for (i, j), cnt in pair_counts.items():
            if cnt > 0:
                nf_val = max_nf_val // (cnt + 1)
                loss = max_nf_val - nf_val
                if loss > 0:
                    for g in range(num_groups):
                        bv = model.NewBoolVar(f's_{attempt}_{i}_{j}_{g}')
                        model.Add(x[i][g] + x[j][g] - 1 <= bv)
                        obj.append(bv * (-loss))

        model.Maximize(sum(obj))

        solver = cp_model.CpSolver()
        # 탐색 구조를 대폭 줄였으므로 1.5초만에 최적해/실현가능 영역에 도달
        solver.parameters.max_time_in_seconds = 1.5
        solver.parameters.num_workers = 4
        solver.parameters.random_seed = attempt * 13 + 7

        status = solver.Solve(model)

        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            app.logger.warning(f"[CP-SAT] attempt {attempt}: 실패 status={status}")
            continue

        # 결과 추출
        assignment = {}
        for i in range(n):
            for g in range(num_groups):
                if solver.Value(x[i][g]) == 1:
                    assignment[names[i]] = g
                    break

        groups_dict = {g: [] for g in range(num_groups)}
        for name, g in assignment.items():
            groups_dict[g].append(name)
        formatted_groups = [groups_dict[g] for g in sorted(groups_dict) if groups_dict[g]]

        # 중복 체크
        frozen = frozenset(frozenset(grp) for grp in formatted_groups)
        if frozen in [frozenset(frozenset(grp) for grp in r['groups']) for r in results]:
            app.logger.info(f"[CP-SAT] attempt {attempt}: 중복, 스킵")
            continue

        # 점수 계산 (표시용 — combined 가중치 40:10 적용).
        # 성별 미상자는 분모/분자에서 모두 제외해 점수 왜곡 방지.
        gender_score = 0.0
        for grp in formatted_groups:
            m = sum(1 for nm in grp if normalize_gender(name_to_info.get(nm, {}).get('gender')) == 'M')
            f = sum(1 for nm in grp if normalize_gender(name_to_info.get(nm, {}).get('gender')) == 'W')
            if m > 0 and f > 0:
                gender_score += min(m, f) / max(m, f)

        new_face_score = 0.0
        for (i, j), cnt in pair_counts.items():
            if assignment.get(names[i]) == assignment.get(names[j]):
                new_face_score += 1.0 / (cnt + 1)

        total_score = (gender_score * 40 + new_face_score * 10)

        results.append({
            'score': f"{total_score:.2f}",
            'details': [f"{gender_score:.2f}", f"{new_face_score:.2f}", "0.00", "0.00"],
            'groups': formatted_groups
        })
        app.logger.info(f"[CP-SAT] attempt {attempt}: 성공 {len(results)}/{top_n}, score={total_score:.2f}")

        # 현재 진행률을 progress_callback으로 통보 (10~85% 범위를 results 수에 청해 비례 배분)
        if progress_callback:
            pct = min(85, 12 + int((len(results) / top_n) * 73))
            progress_callback(pct)

        # 이 조합의 동일-그룹 쌍을 금지 목록에 추가
        same_pairs = set()
        for i in range(n):
            for j in range(i + 1, n):
                if assignment.get(names[i]) == assignment.get(names[j]):
                    same_pairs.add((i, j))
        found_groupings.append(same_pairs)

    app.logger.info(f"[CP-SAT] 완료: {len(results)}개 반환")
    return results



#todo 미리보기에서도 * 거르기

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


def _adjust_co_matrix(groups, date_str, sign):
    """groups의 모든 페어에 대해 bookclub_co_matrix count를 sign(+1/-1)만큼 조정.
    sign=+1: 증가 (upsert), sign=-1: 감소 (0이 되면 row 삭제, 그렇지 않으면 upsert).
    last_met은 sign=+1일 때 더 최근 날짜로 갱신, sign=-1일 때는 건드리지 않음.
    """
    deltas = {}
    for g in groups or []:
        for a, b in itertools.combinations(g, 2):
            key = '-'.join(sorted([a, b]))
            deltas[key] = deltas.get(key, 0) + sign
    if not deltas:
        return
    keys = list(deltas.keys())
    matrix_res = supabase.table('bookclub_co_matrix').select('pair_key, count, last_met').in_('pair_key', keys).execute()
    current = {row['pair_key']: row for row in (matrix_res.data or [])}

    upsert_rows = []
    del_keys = []
    for key, delta in deltas.items():
        cur = current.get(key)
        cur_count = (cur or {}).get('count', 0)
        new_count = max(0, cur_count + delta)
        if new_count == 0:
            if cur:
                del_keys.append(key)
            continue
        row = {"pair_key": key, "count": new_count}
        if sign > 0:
            cur_last = (cur or {}).get('last_met') or ''
            row["last_met"] = date_str if (not cur_last or date_str >= cur_last) else cur_last
        upsert_rows.append(row)

    if del_keys:
        supabase.table('bookclub_co_matrix').delete().in_('pair_key', del_keys).execute()
    if upsert_rows:
        supabase.table('bookclub_co_matrix').upsert(upsert_rows, on_conflict='pair_key').execute()


# [신규] 조 편성 기록을 DB에 저장하는 헬퍼 함수
def save_group_record_to_db(date, present, facilitators, groups, book_title=None, genre=None):
    """주어진 데이터로 조 편성 기록과 만남 횟수 매트릭스를 DB에 저장/업데이트합니다."""
    try:
        # 1. history 테이블에 기록 저장
        record = {"date": date, "present": present, "facilitators": facilitators, "groups": groups}
        if book_title:
            record["book_title"] = book_title.strip()
        if genre:
            record["genre"] = genre.strip()
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

            supabase.table("bookclub_co_matrix").upsert(final_upsert_data, on_conflict='pair_key').execute()

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
    # 회차 관리 페이지에서 "+ 수동 추가" 클릭 시 prefill (?date=, ?book_title=)
    prefill = {
        'date': (request.args.get('date') or '').strip(),
        'book_title': (request.args.get('book_title') or '').strip(),
    }
    try:
        genres = _load_genres()
    except Exception:
        genres = []
    return render_template('manual_entry.html', all_members=all_members,
                           prefill=prefill, genres=genres)


@app.route('/save_manual_groups', methods=['POST'])
@login_required(role="admin")
def save_manual_groups():
    try:
        form_data = request.form
        meeting_date = form_data.get('meeting_date')
        book_title = (form_data.get('book_title') or '').strip()
        genre = (form_data.get('genre') or '').strip()

        groups = []
        present_members_set = set()
        facilitator_members_set = set()  # [수정] 발제자 목록을 저장할 Set

        for i in range(1, 16):
            group_text = form_data.get(f'group_{i}')
            if group_text:
                member_names_raw = re.split(r'[,;\s\n]+', group_text)

                cleaned_group = []
                for name_raw in member_names_raw:
                    name = name_raw.strip()
                    if not name:
                        continue

                    # [수정] 이름 뒤에 '*'가 있는지 확인
                    if name.endswith('*'):
                        clean_name = name[:-1]  # '*'를 제거한 순수 이름
                        facilitator_members_set.add(clean_name)
                        cleaned_group.append(clean_name)
                    else:
                        cleaned_group.append(name)

                if cleaned_group:
                    groups.append(cleaned_group)
                    present_members_set.update(cleaned_group)

        present_members = sorted(list(present_members_set))
        facilitator_members = sorted(list(facilitator_members_set))  # [수정] 발제자 목록 정렬

        if not all([meeting_date, present_members, groups]):
            flash("날짜와 최소 1명 이상의 그룹 멤버를 모두 입력해야 합니다.", "danger")
            return redirect(url_for('manual_entry'))

        # [수정] 발제자/도서/장르 정보도 함께 DB에 저장
        result = save_group_record_to_db(meeting_date, present_members, facilitator_members, groups,
                                         book_title=book_title, genre=genre)

        if result["status"] == "ok":
            flash("수동 조 편성 기록이 성공적으로 저장되었습니다.", "success")
            return redirect(url_for('records_seminars'))
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
    """history 테이블에서 해당 ID의 기록을 삭제하고 co_matrix를 삭제된 만남 횟수를 바삼하여 재계산."""
    record_id = request.json.get("id")
    if not record_id:
        return jsonify({"status": "error", "message": "record id required"}), 400
    try:
        # 1. 삭제할 기록 조회
        del_res = supabase.table("history").select("groups, date").eq("id", record_id).execute()
        if not del_res.data:
            return jsonify({"status": "error", "message": "Record not found"}), 404
        deleted_record = del_res.data[0]

        # 2. 실제 삭제
        supabase.table("history").delete().eq("id", record_id).execute()

        # 3. 삭제된 기록에 릴린 쫐들의 co_matrix 횟수 괐산
        keys_to_decrement = {}
        deleted_groups = deleted_record.get("groups", []) or []
        for g in deleted_groups:
            for a, b in itertools.combinations(g, 2):
                key = '-'.join(sorted([a, b]))
                keys_to_decrement[key] = keys_to_decrement.get(key, 0) + 1

        if keys_to_decrement:
            matrix_res = supabase.table('bookclub_co_matrix') \
                .select('pair_key, count').in_('pair_key', list(keys_to_decrement.keys())).execute()
            current_counts = {item['pair_key']: item['count'] for item in matrix_res.data}

            upsert_rows = []
            del_keys = []
            for key, decrement in keys_to_decrement.items():
                new_count = max(0, current_counts.get(key, 0) - decrement)
                if new_count == 0:
                    del_keys.append(key)
                else:
                    upsert_rows.append({"pair_key": key, "count": new_count})

            if del_keys:
                supabase.table('bookclub_co_matrix').delete().in_('pair_key', del_keys).execute()
            if upsert_rows:
                supabase.table('bookclub_co_matrix').upsert(upsert_rows, on_conflict='pair_key').execute()

        return jsonify({"status": "ok"})
    except Exception as e:
        app.logger.error(f"Error deleting history: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500
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
    [수정] 지원자에게 보여줄 슬롯 목록에 is_past 플래그를 추가하여
    시간이 지났는지 여부를 프론트엔드에서 알 수 있도록 합니다.
    """
    try:
        response = supabase.table('time_slots').select('*').eq('event_id', event_id).eq('is_active', True).order(
            'slot_datetime', desc=False).execute()

        slots_data = response.data if hasattr(response, 'data') else response
        slots_by_date = {}

        # 한국 시간대(KST)와 현재 UTC 시간 정의
        KST = timezone(timedelta(hours=9))
        now_utc = datetime.now(timezone.utc)

        for slot in slots_data:
            if not slot.get('slot_datetime'):
                continue

            utc_dt = datetime.fromisoformat(slot['slot_datetime'].replace('Z', '+00:00'))
            kst_dt = utc_dt.astimezone(KST)

            # [추가] is_past 플래그 계산
            slot['is_past'] = utc_dt < now_utc

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


# 수동 추가 시 정보 확인용
@app.route('/api/bookclub/preview_manual_groups', methods=['POST'])
@login_required(role="admin")
def preview_manual_groups():
    try:
        data = request.get_json()
        groups = data.get('groups')

        if not groups:
            return jsonify({"error": "그룹 정보가 없습니다."}), 400

        # 1. DB에서 전체 회원 정보와 만남 기록을 가져옵니다.
        all_members_res = supabase.table("members").select("name, gender").execute()
        name_to_gender = {m['name']: normalize_gender(m.get('gender')) for m in all_members_res.data}

        # [수정] last_met 컬럼도 함께 가져옵니다.
        co_matrix_res = supabase.table("bookclub_co_matrix").select("pair_key, count, last_met").execute()
        co_matrix = {item['pair_key']: {'count': item['count'], 'last_met': item.get('last_met')} for item in
                     co_matrix_res.data}

        # 발제자 표시용 '*' 접미사를 제거하여 실제 회원 이름으로 정규화
        def strip_facilitator_mark(nm):
            return nm[:-1].strip() if isinstance(nm, str) and nm.endswith('*') else nm

        groups = [[strip_facilitator_mark(n) for n in g if n] for g in groups]

        # 2. 그룹별 분석 시작
        group_analysis = []
        for i, group in enumerate(groups):
            # 성비 계산
            gender_counts = {'M': 0, 'W': 0, 'Unknown': 0}
            for name in group:
                gender = name_to_gender.get(name)
                if gender in ['M', 'W']:
                    gender_counts[gender] += 1
                else:
                    gender_counts['Unknown'] += 1

            # 만남 기록 분석
            new_encounters = []
            past_encounters = []

            # itertools.combinations를 사용하여 그룹 내 모든 쌍을 생성
            for name1, name2 in itertools.combinations(group, 2):
                pair_key = '-'.join(sorted([name1, name2]))

                if pair_key in co_matrix:
                    # 만난 기록이 있는 경우
                    record = co_matrix[pair_key]
                    past_encounters.append({
                        "pair": f"{name1} & {name2}",
                        "count": record['count'],
                        "last_met": record.get('last_met', 'N/A')  # last_met이 없을 경우 대비
                    })
                else:
                    # 처음 만나는 경우
                    new_encounters.append(f"{name1} & {name2}")

            # 결과 구조화
            group_analysis.append({
                "group_index": i + 1,
                "gender_balance": gender_counts,
                "encounters": {
                    "new": new_encounters,
                    "past": sorted(past_encounters, key=lambda x: x['count'], reverse=True)  # 횟수 내림차순 정렬
                }
            })

        return jsonify({"group_analysis": group_analysis})

    except Exception as e:
        app.logger.error(f"Error in preview_manual_groups: {e}", exc_info=True)
        return jsonify({"error": "데이터 분석 중 오류가 발생했습니다."}), 500


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

        attendance_records_res = supabase.table('attendance').select('meeting_date') \
            .eq('user_id', user_id).eq('attending_seminar', True).order('meeting_date', desc=True).execute()
        attendance_records = attendance_records_res.data


        # 다음 세미나 날짜 계산 (월/목)
        seminar_date_objs = get_next_seminar_dates()
        weekday_labels = {0: '월', 1: '화', 2: '수', 3: '목', 4: '금', 5: '토', 6: '일'}
        seminar_dates = [
            {
                'date': d.isoformat(),
                'label': f"{d.strftime('%m/%d')} ({weekday_labels[d.weekday()]})"
            }
            for d in seminar_date_objs
        ]
        date_strs = [s['date'] for s in seminar_dates]

        # 나의 참석 확인 날짜 목록
        confirmed_res = supabase.table('attendance').select('meeting_date') \
            .eq('user_id', user_id) \
            .in_('meeting_date', date_strs) \
            .eq('attending_seminar', True).execute()
        my_confirmed_dates = {r['meeting_date'] for r in (confirmed_res.data or [])}

        # 현재 진행 중인 발제문 제출 이벤트들 (다중 지원)
        active_topic_events = []
        try:
            topic_res = supabase.table('topic_events').select('*').eq('is_active', True).order('meeting_date', desc=True).execute()
            active_topic_events = topic_res.data or []
        except Exception:
            pass

        # 내 활동 요약 (세미나/발제/벽돌책/소모임)
        try:
            activity = _aggregate_member_activity(user_id, user_data.get('name', ''))
        except Exception as e:
            app.logger.warning(f"my_page activity error: {e}")
            activity = {'seminar_count': 0, 'facilitator_count': 0, 'brick_sessions': [], 'study_sessions': []}

        # 내가 참여한 스페셜 이벤트 (최근 5개)
        my_special_events = _member_special_events(user_id)[:5]

        # 현재 투표 가능한 세미나 회차 (학기별)
        my_open_votes = []
        active_seminar_terms = []
        try:
            now_kst = datetime.now(KST)
            terms = supabase.table('seminar_terms').select('id, name, share_token, max_capacity') \
                .eq('is_active', True).execute().data or []
            active_seminar_terms = [
                {'name': t['name'], 'share_token': t['share_token']} for t in terms
            ]
            for term in terms:
                t_sess = supabase.table('seminar_sessions') \
                    .select('id, meeting_date, day_type, vote_open_at, vote_close_at') \
                    .eq('term_id', term['id']).eq('is_active', True) \
                    .order('meeting_date').execute().data or []
                # 내 기존 투표
                sids = [s['id'] for s in t_sess]
                my_votes = {}
                if sids:
                    mv = supabase.table('seminar_votes').select('session_id, attending') \
                        .in_('session_id', sids).eq('member_id', user_id).execute().data or []
                    my_votes = {v['session_id']: v['attending'] for v in mv}
                for s in t_sess:
                    open_at, close_at = _voting_window_for(s)
                    if open_at <= now_kst <= close_at:
                        s['my_vote'] = my_votes.get(s['id'])  # True/False/None
                        s['term_token'] = term['share_token']
                        s['term_name'] = term['name']
                        s['vote_close_label'] = close_at.strftime('%m/%d %H:%M')
                        my_open_votes.append(s)
        except Exception as e:
            app.logger.warning(f"my_page open votes error: {e}")

        return render_template(
            'my_page_member.html',
            user=user_data,
            attendance_records=attendance_records,
            seminar_dates=seminar_dates,
            my_confirmed_dates=my_confirmed_dates,
            active_topic_events=active_topic_events,
            activity=activity,
            my_open_votes=my_open_votes,
            active_seminar_terms=active_seminar_terms,
            my_special_events=my_special_events,
        )

    except Exception as e:
        app.logger.error(f"Error loading my page for user {user_id}: {e}")
        flash("마이페이지를 불러오는 중 오류가 발생했습니다.", "danger")
        return redirect(url_for('main_index'))


@app.route('/api/request_absence', methods=['POST'])
@login_required(role="ANY")
def request_absence():
    user_id = session.get('user_id')
    reason = request.json.get('reason')
    next_monday = get_next_monday()

    if datetime.now(timezone(timedelta(hours=9))).date().weekday() == 0:
        return jsonify({"error": "당일에는 불참 요청을 할 수 없습니다. 관리자에게 직접 문의하세요."}), 403

    if not reason or not reason.strip():
        return jsonify({"error": "불참 사유를 입력해야 합니다."}), 400

    try:
        # 1. [수정] attendance 테이블의 상태를 'pending'으로 설정
        supabase.table('attendance').upsert({
            'user_id': user_id,
            'meeting_date': next_monday.isoformat(),
            'attending_seminar': False,  # 우선 불참으로 설정
            'attending_afterparty': False,
            'absence_reason': reason,
            'absence_request_status': 'pending'  # 승인 대기 상태
        }, on_conflict='user_id, meeting_date').execute()

        # 2. [수정] 관리자에게 '승인/반려'가 필요한 알림 생성
        supabase.table('notifications').insert({
            'type': 'absence_request',  # 승인/반려가 필요한 타입으로 변경
            'related_member_id': user_id,
            'details': {'name': session.get('user_name'), 'reason': reason}
        }).execute()

        return jsonify({"status": "success", "message": "불참 요청이 관리자에게 전달되었습니다."})
    except Exception as e:
        app.logger.error(f"Error on absence request for user {user_id}: {e}")
        return jsonify({"error": "처리 중 오류가 발생했습니다."}), 500



#=== 벌점 추가
# ==============================================================================
# --- [신규] 주간 발제문 수집 및 문서화 시스템 ---
# ==============================================================================

# 1. 관리자: 발제문 이벤트 생성 API
@app.route('/api/admin/topic_events/create', methods=['POST'])
@login_required(role="admin")
def create_topic_event():
    try:
        data = request.json
        token = str(uuid.uuid4())
        supabase.table('topic_events').insert({
            'meeting_date': data.get('meeting_date'),
            'book_title': data.get('book_title'),
            'book_author': data.get('book_author'),
            'share_token': token
        }).execute()
        return jsonify({"status": "success", "message": "발제문 수집 링크가 생성되었습니다."})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# 1.5. 관리자: 발제문 이벤트 영구 삭제 API (제출 내역까지 포함)
@app.route('/api/admin/topic_events/<event_id>/delete', methods=['POST'])
@login_required(role="admin")
def delete_topic_event(event_id):
    try:
        supabase.table('topic_submissions').delete().eq('event_id', event_id).execute()
        supabase.table('topic_events').delete().eq('id', event_id).execute()
        return jsonify({"status": "success", "message": "발제문 이벤트가 영구 삭제되었습니다."})
    except Exception as e:
        app.logger.error(f"Error deleting topic event: {e}")
        return jsonify({"error": "이벤트 삭제 중 서버 오류가 발생했습니다."}), 500


# 1.6. 관리자: 발제문 이벤트 활성/숨김 토글 (soft delete)
@app.route('/api/admin/topic_events/<event_id>/toggle_active', methods=['POST'])
@login_required(role="admin")
def toggle_topic_event(event_id):
    try:
        cur = supabase.table('topic_events').select('is_active').eq('id', event_id).single().execute().data
        if not cur:
            return jsonify({"error": "이벤트를 찾을 수 없습니다."}), 404
        new_state = not bool(cur.get('is_active'))
        supabase.table('topic_events').update({'is_active': new_state}).eq('id', event_id).execute()
        return jsonify({"status": "success", "is_active": new_state})
    except Exception as e:
        app.logger.error(f"Error toggling topic event: {e}")
        return jsonify({"error": "상태 변경 중 오류가 발생했습니다."}), 500


# 2. 사용자: 공유 링크를 통한 발제문 작성 페이지
@app.route('/shared_topics')
def view_shared_topics():
    token = request.args.get('token')
    if not token:
        flash("잘못된 접근입니다.", "danger")
        return redirect(url_for('main_index'))

    try:
        event_res = supabase.table('topic_events').select('*').eq('share_token', token).single().execute()
        event_data = event_res.data
        if not event_data or not event_data.get('is_active'):
            flash("마감되었거나 유효하지 않은 링크입니다.", "warning")
            return redirect(url_for('main_index'))

        user_name = session.get('user_name')
        user_department = None
        user_student_id = None
        if user_name:
            try:
                member_res = supabase.table('members').select('department, student_id').eq('name', user_name).single().execute()
                if member_res.data:
                    user_department = member_res.data.get('department')
                    user_student_id = member_res.data.get('student_id')
            except Exception:
                pass
        return render_template('topic_submit.html',
                               event=event_data,
                               user_name=user_name,
                               user_department=user_department,
                               user_student_id=user_student_id)
    except Exception as e:
        app.logger.error(f"Error loading topic event: {e}")
        return "유효하지 않은 링크입니다.", 404


# 3. 사용자: 발제문 제출/수정 API (PIN 검증 포함)
@app.route('/api/topics/submit', methods=['POST'])
def submit_topics():
    data = request.json
    event_id = data.get('event_id')
    author_name = data.get('author_name')
    department = data.get('department')
    pin_code = data.get('pin_code')
    student_id = (data.get('student_id') or '').strip()
    topics = data.get('topics')  # JSON Array

    # 로그인한 회원은 PIN 검증 패스 (세션 확인)
    is_logged_in_member = session.get('user_name') == author_name

    # 학번+이름 매칭으로도 회원 인증 가능
    if not is_logged_in_member and student_id and author_name:
        try:
            mres = supabase.table('members').select('id, name, department, is_active') \
                .eq('student_id', student_id).execute().data or []
            for m in mres:
                if (m.get('name') or '').strip() == author_name.strip() and m.get('is_active'):
                    is_logged_in_member = True
                    if not department:
                        department = m.get('department') or ''
                    break
        except Exception as e:
            app.logger.warning(f"student_id member lookup 실패: {e}")

    if not all([event_id, author_name, department, topics]):
        return jsonify({"error": "필수 정보를 모두 입력해주세요."}), 400

    if not is_logged_in_member and not pin_code:
        return jsonify({"error": "비회원은 4자리 PIN 번호를 입력해야 합니다."}), 400

    try:
        # 기존 제출 내역 확인
        existing_res = supabase.table('topic_submissions').select('id, pin_code').eq('event_id', event_id).eq(
            'author_name', author_name).eq('department', department).execute()

        # 학번에서 입학년도 2자리 추출 (예: "2022123456" → "22")
        # student_id 가 4자 이상이면 3-4번째 문자 사용
        admission_year = ''
        sid = (student_id or '').strip()
        if len(sid) >= 4 and sid[2:4].isdigit():
            admission_year = sid[2:4]

        if existing_res.data:
            # 수정 모드: 로그인한 본인이거나 PIN 번호가 일치해야 함
            existing_record = existing_res.data[0]
            if not is_logged_in_member and existing_record['pin_code'] != pin_code:
                return jsonify({"error": "PIN 번호가 일치하지 않습니다. (동명이인일 경우 학과를 다르게 입력해주세요)"}), 403

            # 업데이트 실행
            update_payload = {'topics': topics, 'updated_at': 'now()'}
            if admission_year:
                update_payload['admission_year'] = admission_year
            supabase.table('topic_submissions').update(update_payload) \
                .eq('id', existing_record['id']).execute()
            return jsonify({"status": "success", "message": "발제문이 성공적으로 수정되었습니다."})
        else:
            # 신규 생성 모드
            supabase.table('topic_submissions').insert({
                'event_id': event_id,
                'author_name': author_name,
                'department': department,
                'admission_year': admission_year or None,
                'pin_code': pin_code if not is_logged_in_member else 'MEMBER',
                'topics': topics
            }).execute()
            return jsonify({"status": "success", "message": "발제문이 성공적으로 제출되었습니다."})

    except Exception as e:
        app.logger.error(f"Error submitting topics: {e}")
        return jsonify({"error": "제출 중 서버 오류가 발생했습니다."}), 500


# 3.5. 사용자: 발제문 불러오기 API
@app.route('/api/topics/load', methods=['POST'])
def load_topics():
    data = request.json
    event_id = data.get('event_id')
    author_name = data.get('author_name')
    department = data.get('department')
    pin_code = data.get('pin_code')
    student_id = (data.get('student_id') or '').strip()

    # 로그인한 회원은 PIN 검증 패스
    is_logged_in_member = session.get('user_name') == author_name

    # 학번+이름 매칭으로도 회원 인증 가능
    if not is_logged_in_member and student_id and author_name:
        try:
            mres = supabase.table('members').select('id, name, department, is_active') \
                .eq('student_id', student_id).execute().data or []
            for m in mres:
                if (m.get('name') or '').strip() == author_name.strip() and m.get('is_active'):
                    is_logged_in_member = True
                    if not department:
                        department = m.get('department') or ''
                    break
        except Exception as e:
            app.logger.warning(f"student_id member lookup 실패: {e}")

    if not all([event_id, author_name, department]):
        return jsonify({"error": "이름과 소속을 모두 입력해주세요."}), 400

    if not is_logged_in_member and not pin_code:
        return jsonify({"error": "비회원은 4자리 PIN 번호를 입력해야 합니다."}), 400

    try:
        existing_res = supabase.table('topic_submissions').select('*').eq('event_id', event_id).eq(
            'author_name', author_name).eq('department', department).execute()

        if existing_res.data:
            existing_record = existing_res.data[0]
            if not is_logged_in_member and str(existing_record['pin_code']) != str(pin_code):
                return jsonify({"error": "PIN 번호가 일치하지 않습니다. (동명이인일 경우 학과를 다르게 입력해주세요)"}), 403

            return jsonify({"status": "success", "topics": existing_record['topics']})
        else:
            return jsonify({"error": "작성된 발제문 내역이 없습니다. 처음 작성하는 것이 맞나요?"}), 404

    except Exception as e:
        app.logger.error(f"Error loading topics: {e}")
        return jsonify({"error": "불러오기 중 서버 오류가 발생했습니다."}), 500


# 3.7 관리자: 발제문 제출 내역 삭제/수정 API (다른 사람의 것도 관리 가능)
@app.route('/api/admin/topic_submissions/<submission_id>/delete', methods=['POST'])
@login_required(role="admin")
def admin_delete_topic_submission(submission_id):
    try:
        supabase.table('topic_submissions').delete().eq('id', submission_id).execute()
        return jsonify({"status": "success", "message": "발제문이 삭제되었습니다."})
    except Exception as e:
        app.logger.error(f"admin_delete_topic_submission error: {e}")
        return jsonify({"error": "삭제 중 오류가 발생했습니다."}), 500


@app.route('/api/admin/topic_submissions/<submission_id>/update', methods=['POST'])
@login_required(role="admin")
def admin_update_topic_submission(submission_id):
    try:
        data = request.json or {}
        topics = data.get('topics')
        if not topics or not isinstance(topics, list):
            return jsonify({"error": "발제문 내용이 비어있습니다."}), 400
        update_fields = {'topics': topics, 'updated_at': 'now()'}
        # 작성자/소속도 함께 수정할 수 있게 허용
        if data.get('author_name'):
            update_fields['author_name'] = data['author_name']
        if data.get('department'):
            update_fields['department'] = data['department']
        supabase.table('topic_submissions').update(update_fields).eq('id', submission_id).execute()
        return jsonify({"status": "success", "message": "발제문이 수정되었습니다."})
    except Exception as e:
        app.logger.error(f"admin_update_topic_submission error: {e}")
        return jsonify({"error": "수정 중 오류가 발생했습니다."}), 500


# 3.8 관리자: 발제문 상세 보기 및 취합 페이지
@app.route('/admin/topics/<event_id>/view')
@login_required(role="admin")
def view_admin_topics(event_id):
    try:
        event = supabase.table('topic_events').select('*').eq('id', event_id).single().execute().data
        submissions = supabase.table('topic_submissions').select('*').eq('event_id', event_id).order(
            'created_at').execute().data
        
        return render_template('admin_topic_view.html', event=event, submissions=submissions)
    except Exception as e:
        flash(f"상세 정보를 불러오는 중 오류 발생: {str(e)}", "danger")
        return redirect(url_for('admin_dashboard'))


# 4. 관리자: Word 파일로 출력 (template.docx 디자인 유지)
# - docxtpl 라이브러리 버전 차이로 production에서 일부 iteration이 누락되는 이슈가 보고됨.
#   대응:
#   1) requirements.txt에 python-docx, docxtpl 버전 핀 (로컬과 동일하게 맞춤)
#   2) 렌더링 후 모든 제출자의 이름이 문서에 실제로 들어갔는지 검증
#   3) 누락 발견 시 누락된 제출만 python-docx로 문서 끝에 append (디자인은 일부 상이하나 누락 방지)
@app.route('/admin/topics/<event_id>/download_word')
@login_required(role="admin")
def download_topics_word(event_id):
    try:
        from docxtpl import DocxTemplate
        from docx import Document
        from docx.shared import Pt, RGBColor
        from docx.enum.text import WD_BREAK

        event = supabase.table('topic_events').select('*').eq('id', event_id).single().execute().data
        submissions = supabase.table('topic_submissions').select('*') \
            .eq('event_id', event_id).order('created_at').execute().data or []
        app.logger.info(f"download_topics_word: 제출 {len(submissions)}건")

        template_path = os.path.join(app.root_path, 'templates', 'template.docx')
        if not os.path.exists(template_path):
            flash("템플릿 워드 파일(template.docx)을 templates 폴더에서 찾을 수 없습니다.", "danger")
            return redirect(url_for('admin_dashboard'))

        # 1) docxtpl로 템플릿 렌더링 (원본 디자인 유지)
        # ※ 발제문 내용에 '<책제목>' 같이 꺾쇠괄호가 들어가면 Word XML 구조를 깨뜨려서
        #   해당 지점 이후 렌더링이 중단되고 파일이 손상됨.
        #   docxtpl의 자동 escape이 production 환경에서 일관되지 않게 동작하므로,
        #   사전에 풀-와이드 유니코드(〈, 〉)로 치환해서 시각적으로는 동일하지만 안전하게 처리.
        def _safe(s):
            if s is None:
                return ''
            return (str(s)
                    .replace('<', '〈')
                    .replace('>', '〉'))

        doc = DocxTemplate(template_path)
        date_str = (event.get('meeting_date') or '').replace('-', '.')
        context = {
            'book_title': _safe(event.get('book_title', '')),
            'meeting_date': date_str,
            'book_author': _safe(event.get('book_author', '')),
            'moderator_name': '',
            'submissions': [
                {
                    # template.docx 에서 '{{ sub.department }} {{ sub.author_name }}' 로 노출되던 부분을
                    # '{입학년도} {이름}' 형태로 바꾸기 위해 department 자리에 학번 prefix 를 넣음.
                    # (admission_year 없는 구 데이터는 기존 department 로 fallback)
                    'department': (sub.get('admission_year') or '').strip() or _safe(sub.get('department', '')),
                    'author_name': _safe(sub.get('author_name', '')),
                    'topics': [
                        {
                            'topic': _safe(t.get('topic', '')),
                            'page': _safe(t.get('page', '')),
                            'reference': _safe(t.get('reference', '')),
                        }
                        for t in (sub.get('topics') or [])
                    ],
                }
                for sub in submissions
            ],
        }
        doc.render(context)

        # 메모리에 저장
        buf = BytesIO()
        doc.save(buf)
        buf.seek(0)

        # 2) 렌더링 검증 — 모든 제출자가 본문에 들어갔는지 확인 (누락 방지)
        import zipfile, re
        buf.seek(0)
        with zipfile.ZipFile(BytesIO(buf.getvalue())) as zin:
            body_xml = zin.read('word/document.xml').decode('utf-8', errors='replace')
        # 본문 plaintext만 추출
        body_text = ''.join(re.findall(r'<w:t[^>]*>([^<]*)</w:t>', body_xml))
        # 각 제출자가 '발제자' 섹션에 들어갔는지 검사: 이름 등장 횟수가 2 이상이면 OK
        # (1회: 참석자 명단, 2회 이상: 발제자 섹션 포함)
        missing = []
        for sub in submissions:
            nm = (sub.get('author_name') or '').strip()
            dept = (sub.get('department') or '').strip()
            if not nm:
                continue
            # 이름이 '발제자' 섹션에 등장하는지 검사: '발제자' 텍스트 이후에 이름이 등장하는지
            # 간단하게 본문 전체에서 이름 등장 횟수로 판별
            cnt = body_text.count(nm)
            if cnt < 2:  # 참석자 명단 1회만 있고 발제 섹션엔 없음
                missing.append(sub)
        if missing:
            app.logger.warning(f"download_topics_word: 누락 감지 {len(missing)}건 → python-docx로 append")
            # 3) 누락된 제출을 문서 끝에 직접 추가
            doc2 = Document(BytesIO(buf.getvalue()))
            for sub in missing:
                # 페이지 나눔
                br_p = doc2.add_paragraph()
                br_p.add_run().add_break(WD_BREAK.PAGE)
                # 발제자 헤더
                hp = doc2.add_paragraph()
                r1 = hp.add_run('발제자: ')
                r1.bold = True
                r1.font.size = Pt(13)
                r1.font.color.rgb = RGBColor(0, 102, 204)
                year_or_dept = (sub.get('admission_year') or '').strip() or sub.get('department','')
                r2 = hp.add_run(f"{year_or_dept} {sub.get('author_name','')}")
                r2.bold = True
                r2.font.size = Pt(13)
                # 발제 내용
                for ti, t in enumerate(sub.get('topics') or [], 1):
                    topic_text = (t.get('topic') or '').strip()
                    page = (t.get('page') or '').strip()
                    reference = (t.get('reference') or '').strip()
                    p = doc2.add_paragraph()
                    rn = p.add_run(f"{ti}. "); rn.bold = True; rn.font.size = Pt(11)
                    first = True
                    for line in topic_text.split('\n'):
                        if not first:
                            p.add_run().add_break()
                        rr = p.add_run(line); rr.font.size = Pt(11); first = False
                    if page or reference:
                        meta = doc2.add_paragraph()
                        parts = []
                        if page: parts.append(f"페이지: {page}")
                        if reference: parts.append(f"참조: {reference}")
                        rm = meta.add_run('   ' + ' | '.join(parts))
                        rm.italic = True; rm.font.size = Pt(10)
                        rm.font.color.rgb = RGBColor(102, 102, 102)
            buf = BytesIO()
            doc2.save(buf)
            buf.seek(0)

        filename = f"발제문_{event.get('book_title','')}_{event.get('meeting_date','')}.docx"
        app.logger.info(f"download_topics_word: 완료, 크기={len(buf.getvalue())} bytes")
        return Response(
            buf.getvalue(),
            mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            headers={"Content-disposition": f"attachment; filename={filename.encode('utf-8').decode('latin1')}"}
        )
    except Exception as e:
        app.logger.error(f"download_topics_word error: {e}", exc_info=True)
        flash(f"문서 생성 중 오류 발생: {str(e)}", "danger")
        return redirect(url_for('admin_dashboard'))

# ==============================================================================
# --- 6.5 세미나 출석 투표 (학기 단위) ---
# ==============================================================================

KST = timezone(timedelta(hours=9))


def _parse_db_ts(val):
    """Supabase timestamptz 문자열 → KST datetime."""
    if not val:
        return None
    if isinstance(val, datetime):
        return val.astimezone(KST) if val.tzinfo else val.replace(tzinfo=KST)
    try:
        s = str(val).replace('Z', '+00:00')
        # Postgres가 "2026-05-10 23:59:59+00" 같은 형식을 줄 수도 있으므로 보정
        if 'T' not in s and ' ' in s:
            s = s.replace(' ', 'T', 1)
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=KST)
        return dt.astimezone(KST)
    except Exception:
        return None


def _default_voting_window(meeting_date):
    """기본 규칙(전주 금 18:00 ~ 전주 일 23:59:59 KST)."""
    if isinstance(meeting_date, str):
        d = date.fromisoformat(meeting_date)
    else:
        d = meeting_date
    monday = d - timedelta(days=d.weekday())
    friday_before = monday - timedelta(days=3)
    sunday_before = monday - timedelta(days=1)
    open_at = datetime.combine(friday_before, time(18, 0), tzinfo=KST)
    close_at = datetime.combine(sunday_before, time(23, 59, 59), tzinfo=KST)
    return open_at, close_at


def _voting_window_for(session_or_date):
    """세미나 회차의 투표 오픈/마감 시각 반환.
    - session dict가 들어오면 vote_open_at/vote_close_at(관리자 지정값)이 있으면 그걸 우선.
    - 둘 다 없거나 date/str만 들어오면 기본 규칙(전주 금 18:00 ~ 전주 일 23:59:59 KST).
    """
    if isinstance(session_or_date, dict):
        meeting_date = session_or_date.get('meeting_date')
        custom_open = _parse_db_ts(session_or_date.get('vote_open_at'))
        custom_close = _parse_db_ts(session_or_date.get('vote_close_at'))
    else:
        meeting_date = session_or_date
        custom_open = None
        custom_close = None
    default_open, default_close = _default_voting_window(meeting_date)
    return (custom_open or default_open), (custom_close or default_close)


def _is_voting_open(session_or_date):
    open_at, close_at = _voting_window_for(session_or_date)
    now = datetime.now(KST)
    return open_at <= now <= close_at


def _enumerate_mon_thu(start_date, end_date):
    """start_date~end_date(둘 다 포함) 사이 모든 월/목 날짜를 (date, day_type) 리스트로 반환."""
    if isinstance(start_date, str):
        start_date = datetime.strptime(start_date, '%Y-%m-%d').date()
    if isinstance(end_date, str):
        end_date = datetime.strptime(end_date, '%Y-%m-%d').date()
    result = []
    d = start_date
    while d <= end_date:
        # weekday(): 월=0, 목=3
        if d.weekday() == 0:
            result.append((d, 'mon'))
        elif d.weekday() == 3:
            result.append((d, 'thu'))
        d += timedelta(days=1)
    return result


@app.route('/api/admin/seminar_terms/create', methods=['POST'])
@login_required(role="admin")
def seminar_term_create():
    try:
        data = request.json or request.form
        name = (data.get('name') or '').strip()
        start_date = data.get('start_date')
        end_date = data.get('end_date')
        max_capacity = int(data.get('max_capacity') or 32)
        if not (name and start_date and end_date):
            return jsonify({'status': 'error', 'message': '학기명/시작일/종료일은 필수입니다.'}), 400

        term_res = supabase.table('seminar_terms').insert({
            'name': name,
            'start_date': start_date,
            'end_date': end_date,
            'max_capacity': max_capacity,
            'is_active': True,
        }).execute()
        term = term_res.data[0]

        sessions_payload = [
            {'term_id': term['id'], 'meeting_date': d.isoformat(), 'day_type': dt}
            for d, dt in _enumerate_mon_thu(start_date, end_date)
        ]
        if sessions_payload:
            supabase.table('seminar_sessions').insert(sessions_payload).execute()

        share_url = f"{request.host_url}seminar_vote?token={term['share_token']}"
        return jsonify({
            'status': 'success',
            'term': term,
            'session_count': len(sessions_payload),
            'share_url': share_url,
        })
    except Exception as e:
        app.logger.error(f"seminar_term_create error: {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/admin/seminar_terms/<term_id>/update', methods=['POST'])
@login_required(role="admin")
def seminar_term_update(term_id):
    try:
        data = request.json or request.form
        update = {}
        for key in ('name', 'start_date', 'end_date'):
            if data.get(key) is not None:
                update[key] = data.get(key)
        if data.get('max_capacity') is not None:
            update['max_capacity'] = int(data.get('max_capacity'))
        if data.get('is_active') is not None:
            v = data.get('is_active')
            update['is_active'] = v if isinstance(v, bool) else str(v).lower() in ('true', '1', 'on', 'yes')
        if update:
            supabase.table('seminar_terms').update(update).eq('id', term_id).execute()

        # 기간이 변경된 경우, 누락된 회차만 추가 (기존 회차는 보존)
        if 'start_date' in update or 'end_date' in update:
            term_res = supabase.table('seminar_terms').select('start_date, end_date').eq('id', term_id).single().execute()
            t = term_res.data
            existing_res = supabase.table('seminar_sessions').select('meeting_date').eq('term_id', term_id).execute()
            existing_dates = {row['meeting_date'] for row in (existing_res.data or [])}
            to_insert = []
            for d, dt in _enumerate_mon_thu(t['start_date'], t['end_date']):
                if d.isoformat() not in existing_dates:
                    to_insert.append({'term_id': term_id, 'meeting_date': d.isoformat(), 'day_type': dt})
            if to_insert:
                supabase.table('seminar_sessions').insert(to_insert).execute()

        return jsonify({'status': 'success'})
    except Exception as e:
        app.logger.error(f"seminar_term_update error: {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/admin/seminar_terms/<term_id>/delete', methods=['POST'])
@login_required(role="admin")
def seminar_term_delete(term_id):
    try:
        supabase.table('seminar_terms').delete().eq('id', term_id).execute()
        return jsonify({'status': 'success'})
    except Exception as e:
        app.logger.error(f"seminar_term_delete error: {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/admin/seminar_sessions/<session_id>/toggle_active', methods=['POST'])
@login_required(role="admin")
def seminar_session_toggle(session_id):
    try:
        cur = supabase.table('seminar_sessions').select('is_active').eq('id', session_id).single().execute().data
        new_val = not bool(cur.get('is_active'))
        supabase.table('seminar_sessions').update({'is_active': new_val}).eq('id', session_id).execute()
        return jsonify({'status': 'success', 'is_active': new_val})
    except Exception as e:
        app.logger.error(f"seminar_session_toggle error: {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/admin/seminar_terms/<term_id>')
@login_required(role="admin")
def admin_seminar_term(term_id):
    try:
        term = supabase.table('seminar_terms').select('*').eq('id', term_id).single().execute().data
        sessions = supabase.table('seminar_sessions').select('*').eq('term_id', term_id) \
            .order('meeting_date').execute().data or []
        session_ids = [s['id'] for s in sessions]
        votes = []
        if session_ids:
            votes = supabase.table('seminar_votes').select('session_id, member_id, attending') \
                .in_('session_id', session_ids).execute().data or []
        # 회차별 집계 + 참석자 멤버 ID 목록
        agg = {sid: {'yes': 0, 'no': 0, 'attendee_ids': []} for sid in session_ids}
        for v in votes:
            sid = v['session_id']
            if v['attending']:
                agg[sid]['yes'] += 1
                agg[sid]['attendee_ids'].append(v['member_id'])
            else:
                agg[sid]['no'] += 1
        # 멤버 이름 매핑
        member_ids = {mid for a in agg.values() for mid in a['attendee_ids']}
        member_map = {}
        if member_ids:
            mres = supabase.table('members').select('id, name').in_('id', list(member_ids)).execute().data or []
            member_map = {m['id']: m['name'] for m in mres}

        # 진행 기록(history)과 연동: 같은 날짜의 history row 존재 여부 + id
        session_dates = [s['meeting_date'] for s in sessions]
        history_map = {}
        if session_dates:
            hres = supabase.table('history').select('id, date, book_title, genre, groups, facilitators') \
                .in_('date', session_dates).execute().data or []
            for h in hres:
                history_map[h['date']] = h

        today_kst = datetime.now(KST).date()
        upcoming_sessions, past_sessions = [], []
        for s in sessions:
            a = agg.get(s['id'], {'yes': 0, 'no': 0, 'attendee_ids': []})
            s['yes_count'] = a['yes']
            s['no_count'] = a['no']
            s['attendees'] = [{'id': mid, 'name': member_map.get(mid, f"id={mid}")} for mid in a['attendee_ids']]
            open_at, close_at = _voting_window_for(s)
            s['voting_open_at'] = open_at.strftime('%Y-%m-%d %H:%M')
            s['voting_close_at'] = close_at.strftime('%Y-%m-%d %H:%M')
            s['voting_open_at_input']  = open_at.strftime('%Y-%m-%dT%H:%M')
            s['voting_close_at_input'] = close_at.strftime('%Y-%m-%dT%H:%M')
            s['voting_custom'] = bool(s.get('vote_open_at') or s.get('vote_close_at'))
            now_kst = datetime.now(KST)
            if now_kst < open_at:
                s['vote_status'] = 'upcoming'
            elif now_kst <= close_at:
                s['vote_status'] = 'open'
            else:
                s['vote_status'] = 'closed'

            # 기록 연동
            h = history_map.get(s['meeting_date'])
            s['history_id'] = h['id'] if h else None
            if h and not s.get('book_title') and h.get('book_title'):
                s['book_title'] = h['book_title']

            # 과거 회차 분리
            try:
                m_date = date.fromisoformat(s['meeting_date'])
            except Exception:
                m_date = today_kst
            s['is_past'] = m_date < today_kst
            if s['is_past']:
                past_sessions.append(s)
            else:
                upcoming_sessions.append(s)

        # 전체 활성 멤버 (관리자 수동 추가용)
        all_members = supabase.table('members').select('id, name, student_id, department') \
            .eq('is_active', True).order('name').execute().data or []

        share_url = f"{request.host_url}seminar_vote?token={term['share_token']}"
        return render_template('admin_seminar_term.html', term=term, sessions=sessions,
                               upcoming_sessions=upcoming_sessions, past_sessions=past_sessions,
                               share_url=share_url, all_members=all_members)
    except Exception as e:
        app.logger.error(f"admin_seminar_term error: {e}", exc_info=True)
        flash(f"학기 정보를 불러오는 중 오류: {e}", "danger")
        return redirect(url_for('admin_dashboard'))


@app.route('/api/admin/seminar_sessions/<session_id>/update_book', methods=['POST'])
@login_required(role="admin")
def seminar_session_update_book(session_id):
    try:
        data = request.json or {}
        book_title = (data.get('book_title') or '').strip()
        supabase.table('seminar_sessions').update({'book_title': book_title or None}) \
            .eq('id', session_id).execute()
        return jsonify({'status': 'success'})
    except Exception as e:
        app.logger.error(f"seminar_session_update_book error: {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/admin/seminar_sessions/<session_id>/update_voting_window', methods=['POST'])
@login_required(role="admin")
def seminar_session_update_voting_window(session_id):
    """관리자: 회차별 투표 오픈/마감 시각을 직접 지정하거나 기본 규칙으로 되돌림.
    body: { vote_open_at: 'YYYY-MM-DDTHH:MM' | '', vote_close_at: 'YYYY-MM-DDTHH:MM' | '',
            reset: bool }
    빈 문자열이거나 reset=True면 NULL로 설정 → 기본 규칙으로 fallback.
    """
    try:
        data = request.json or {}

        def parse_local_kst(val):
            if not val:
                return None
            s = str(val).strip()
            if not s:
                return None
            # datetime-local input: 'YYYY-MM-DDTHH:MM' (초 없음일 수 있음)
            try:
                if len(s) == 16:
                    s += ':00'
                dt = datetime.fromisoformat(s)
            except Exception:
                return None
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=KST)
            return dt.astimezone(timezone.utc).isoformat()

        if data.get('reset'):
            new_open, new_close = None, None
        else:
            new_open = parse_local_kst(data.get('vote_open_at'))
            new_close = parse_local_kst(data.get('vote_close_at'))
            if new_open and new_close and new_open >= new_close:
                return jsonify({'status': 'error', 'message': '오픈 시각은 마감 시각보다 빨라야 합니다.'}), 400

        supabase.table('seminar_sessions').update({
            'vote_open_at': new_open,
            'vote_close_at': new_close,
        }).eq('id', session_id).execute()

        # 새 윈도우를 다시 계산해서 반환 (NULL이면 기본 규칙으로)
        sess = supabase.table('seminar_sessions') \
            .select('meeting_date, vote_open_at, vote_close_at') \
            .eq('id', session_id).single().execute().data or {}
        open_at, close_at = _voting_window_for(sess)
        return jsonify({
            'status': 'success',
            'voting_open_at': open_at.strftime('%Y-%m-%d %H:%M'),
            'voting_close_at': close_at.strftime('%Y-%m-%d %H:%M'),
            'voting_open_at_input':  open_at.strftime('%Y-%m-%dT%H:%M'),
            'voting_close_at_input': close_at.strftime('%Y-%m-%dT%H:%M'),
            'voting_custom': bool(sess.get('vote_open_at') or sess.get('vote_close_at')),
        })
    except Exception as e:
        app.logger.error(f"seminar_session_update_voting_window error: {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/admin/seminar_sessions/<session_id>/add_attendee', methods=['POST'])
@login_required(role="admin")
def seminar_session_add_attendee(session_id):
    try:
        data = request.json or {}
        member_id = data.get('member_id')
        if not member_id:
            return jsonify({'status': 'error', 'message': 'member_id 필요'}), 400
        supabase.table('seminar_votes').upsert({
            'session_id': session_id,
            'member_id': member_id,
            'attending': True,
            'added_by_admin': True,
        }, on_conflict='session_id,member_id').execute()
        return jsonify({'status': 'success'})
    except Exception as e:
        app.logger.error(f"seminar_session_add_attendee error: {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/admin/seminar_sessions/<session_id>/remove_attendee', methods=['POST'])
@login_required(role="admin")
def seminar_session_remove_attendee(session_id):
    try:
        data = request.json or {}
        member_id = data.get('member_id')
        if not member_id:
            return jsonify({'status': 'error', 'message': 'member_id 필요'}), 400
        supabase.table('seminar_votes').delete() \
            .eq('session_id', session_id).eq('member_id', member_id).execute()
        return jsonify({'status': 'success'})
    except Exception as e:
        app.logger.error(f"seminar_session_remove_attendee error: {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/seminar_vote')
def seminar_vote_page():
    token = request.args.get('token')
    if not token:
        return "잘못된 접근입니다.", 400
    try:
        term = supabase.table('seminar_terms').select('*').eq('share_token', token).single().execute().data
        if not term or not term.get('is_active'):
            return "유효하지 않거나 종료된 학기입니다.", 404
        sessions = supabase.table('seminar_sessions').select('*') \
            .eq('term_id', term['id']).eq('is_active', True) \
            .order('meeting_date').execute().data or []
        session_ids = [s['id'] for s in sessions]
        counts = {sid: 0 for sid in session_ids}
        attendees_by_session = {sid: [] for sid in session_ids}
        if session_ids:
            votes = supabase.table('seminar_votes').select('session_id, member_id') \
                .in_('session_id', session_ids).eq('attending', True).execute().data or []
            member_ids = list({v['member_id'] for v in votes})
            name_by_id = {}
            if member_ids:
                mres = supabase.table('members').select('id, name') \
                    .in_('id', member_ids).execute().data or []
                name_by_id = {m['id']: m.get('name') or '' for m in mres}
            for v in votes:
                counts[v['session_id']] = counts.get(v['session_id'], 0) + 1
                nm = name_by_id.get(v['member_id'])
                if nm:
                    attendees_by_session.setdefault(v['session_id'], []).append(nm)
            for sid in attendees_by_session:
                attendees_by_session[sid].sort()
        now_kst = datetime.now(KST)
        is_admin = session.get('user_role') in ('admin', 'officer')
        open_sessions, upcoming_sessions, closed_sessions = [], [], []
        for s in sessions:
            s['attending_count'] = counts.get(s['id'], 0)
            s['is_full'] = s['attending_count'] >= term.get('max_capacity', 32)
            s['attendee_names'] = attendees_by_session.get(s['id'], [])
            open_at, close_at = _voting_window_for(s)
            s['voting_open_at'] = open_at.strftime('%Y-%m-%d %H:%M')
            s['voting_close_at'] = close_at.strftime('%Y-%m-%d %H:%M')
            s['voting_close_label'] = close_at.strftime('%m월 %d일 (%a) %H:%M')
            if open_at <= now_kst <= close_at:
                s['status'] = 'open'
                open_sessions.append(s)
            elif now_kst < open_at:
                s['status'] = 'upcoming'
                upcoming_sessions.append(s)
            else:
                s['status'] = 'closed'
                closed_sessions.append(s)
        # 관리자/임원은 열리기 전 회차도 바로 투표 가능 → open에 합쳐서 노출
        if is_admin:
            for s in upcoming_sessions:
                s['admin_early'] = True
            open_sessions = open_sessions + upcoming_sessions
            upcoming_sessions_for_template = []
        else:
            upcoming_sessions_for_template = upcoming_sessions[:6]
        return render_template('seminar_vote.html', term=term,
                               open_sessions=open_sessions,
                               upcoming_sessions=upcoming_sessions_for_template,
                               is_admin=is_admin)
    except Exception as e:
        app.logger.error(f"seminar_vote_page error: {e}", exc_info=True)
        return "유효하지 않은 링크입니다.", 404


@app.route('/api/seminar_vote/verify', methods=['POST'])
def seminar_vote_verify():
    """학번+이름으로 본인 확인 + 기존 투표/세션 현황 반환."""
    try:
        data = request.json or {}
        token = (data.get('token') or '').strip()
        student_id = (data.get('student_id') or '').strip()
        name = (data.get('name') or '').strip()
        if not (token and student_id and name):
            return jsonify({'status': 'error', 'message': '학번/이름을 입력해주세요.'}), 400
        term_res = supabase.table('seminar_terms').select('*').eq('share_token', token).single().execute()
        term = term_res.data
        if not term or not term.get('is_active'):
            return jsonify({'status': 'error', 'message': '유효하지 않은 링크입니다.'}), 404
        member_res = supabase.table('members').select('id, name, student_id') \
            .eq('student_id', student_id).execute()
        candidates = [m for m in (member_res.data or []) if (m.get('name') or '').strip() == name]
        if not candidates:
            return jsonify({'status': 'error', 'message': '학번/이름이 일치하는 멤버를 찾을 수 없습니다.'}), 404
        member = candidates[0]
        # 기존 투표 (이 학기의 모든 세션)
        sess_res = supabase.table('seminar_sessions').select('id') \
            .eq('term_id', term['id']).execute().data or []
        sess_ids = [s['id'] for s in sess_res]
        existing = {}
        if sess_ids:
            ev = supabase.table('seminar_votes').select('session_id, attending') \
                .in_('session_id', sess_ids).eq('member_id', member['id']).execute().data or []
            existing = {x['session_id']: ('yes' if x['attending'] else 'no') for x in ev}
        return jsonify({
            'status': 'success',
            'member_name': member['name'],
            'existing_votes': existing,
        })
    except Exception as e:
        app.logger.error(f"seminar_vote_verify error: {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/seminar_vote/counts')
def seminar_vote_counts():
    """현재 회차별 참석 인원 수 (실시간 새로고침용)."""
    try:
        token = (request.args.get('token') or '').strip()
        if not token:
            return jsonify({'status': 'error', 'message': 'token 필요'}), 400
        term = supabase.table('seminar_terms').select('id, max_capacity') \
            .eq('share_token', token).single().execute().data
        if not term:
            return jsonify({'status': 'error', 'message': '유효하지 않은 링크'}), 404
        sess = supabase.table('seminar_sessions').select('id') \
            .eq('term_id', term['id']).eq('is_active', True).execute().data or []
        sess_ids = [s['id'] for s in sess]
        counts = {sid: 0 for sid in sess_ids}
        if sess_ids:
            votes = supabase.table('seminar_votes').select('session_id') \
                .in_('session_id', sess_ids).eq('attending', True).execute().data or []
            for v in votes:
                counts[v['session_id']] = counts.get(v['session_id'], 0) + 1
        return jsonify({'status': 'success', 'counts': counts, 'max_capacity': term.get('max_capacity', 32)})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/seminar_vote/submit', methods=['POST'])
def seminar_vote_submit():
    try:
        data = request.json or {}
        token = (data.get('token') or '').strip()
        student_id = (data.get('student_id') or '').strip()
        name = (data.get('name') or '').strip()
        votes = data.get('votes') or []
        if not (token and student_id and name):
            return jsonify({'status': 'error', 'message': '토큰/학번/이름은 필수입니다.'}), 400

        term_res = supabase.table('seminar_terms').select('*').eq('share_token', token).single().execute()
        term = term_res.data
        if not term or not term.get('is_active'):
            return jsonify({'status': 'error', 'message': '유효하지 않은 링크입니다.'}), 404

        # 학번+이름으로 멤버 검증
        member_res = supabase.table('members').select('id, name, student_id') \
            .eq('student_id', student_id).execute()
        candidates = [m for m in (member_res.data or []) if (m.get('name') or '').strip() == name]
        if not candidates:
            return jsonify({'status': 'error', 'message': '학번/이름이 일치하는 멤버를 찾을 수 없습니다.'}), 400
        member = candidates[0]
        member_id = member['id']

        max_cap = int(term.get('max_capacity', 32))
        success, full, skipped = [], [], []
        is_admin = session.get('user_role') in ('admin', 'officer')

        # 회차 ID 화이트리스트 (이 학기 소속만 허용)
        valid_sessions = supabase.table('seminar_sessions') \
            .select('id, meeting_date, day_type, is_active, vote_open_at, vote_close_at') \
            .eq('term_id', term['id']).execute().data or []
        valid_map = {s['id']: s for s in valid_sessions}

        for v in votes:
            sid = v.get('session_id')
            choice = (v.get('attending') or '').lower()
            if sid not in valid_map or not valid_map[sid].get('is_active'):
                continue
            label = f"{valid_map[sid]['meeting_date']} ({valid_map[sid]['day_type']})"

            # 투표 윈도우 체크: 관리자/임원은 언제든 가능
            if not is_admin and not _is_voting_open(valid_map[sid]):
                skipped.append(f"{label} - 투표 기간 외")
                continue

            if choice == 'skip':
                supabase.table('seminar_votes').delete() \
                    .eq('session_id', sid).eq('member_id', member_id).execute()
                skipped.append(label)
                continue

            if choice == 'yes':
                # 본인 제외 현재 참석자 수 확인
                cnt_res = supabase.table('seminar_votes').select('member_id', count='exact') \
                    .eq('session_id', sid).eq('attending', True).neq('member_id', member_id).execute()
                cur_count = cnt_res.count if hasattr(cnt_res, 'count') and cnt_res.count is not None else len(cnt_res.data or [])
                if cur_count >= max_cap:
                    full.append(label)
                    continue
                supabase.table('seminar_votes').upsert({
                    'session_id': sid, 'member_id': member_id, 'attending': True,
                }, on_conflict='session_id,member_id').execute()
                success.append(label)
            elif choice == 'no':
                supabase.table('seminar_votes').upsert({
                    'session_id': sid, 'member_id': member_id, 'attending': False,
                }, on_conflict='session_id,member_id').execute()
                success.append(label)

        return jsonify({
            'status': 'success',
            'member_name': member['name'],
            'success': success,
            'full': full,
            'skipped': skipped,
        })
    except Exception as e:
        app.logger.error(f"seminar_vote_submit error: {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': str(e)}), 500


# ==============================================================================
# --- 6.6 통합 기록 시스템 (회원/세미나/벽돌책/소모임/장르) ---
# ==============================================================================

DEFAULT_GENRES = ['고전문학', '한국문학', '비문학', '시']


def _load_genres():
    try:
        res = supabase.table('genres').select('*') \
            .order('display_order').order('name').execute()
        return res.data or []
    except Exception as e:
        app.logger.warning(f"장르 로드 실패: {e}")
        return []


def _can_view_member_profile(member_id):
    if session.get('user_role') == 'admin':
        return True
    if session.get('user_id') == member_id:
        return True
    return False


def _aggregate_member_activity(member_id, member_name):
    """한 멤버의 세미나/벽돌책/소모임 활동 집계."""
    history_res = supabase.table('history').select('id, date, book_title, genre, groups, facilitators') \
        .order('date', desc=True).execute()
    history = history_res.data or []
    seminar_records, facilitator_count = [], 0
    for row in history:
        groups = row.get('groups') or []
        present = set()
        for g in groups:
            if isinstance(g, list):
                present.update(g)
            elif isinstance(g, str):
                present.add(g)
        if member_name in present:
            is_fac = member_name in (row.get('facilitators') or [])
            if is_fac:
                facilitator_count += 1
            seminar_records.append({
                'history_id': row['id'],
                'date': row.get('date'),
                'book_title': row.get('book_title') or '',
                'genre': row.get('genre') or '',
                'is_facilitator': is_fac,
            })

    # 벽돌책 세션 참여
    try:
        bb_parts = supabase.table('brick_session_members').select(
            'session_id, brick_book_sessions(id, meeting_date, notes, brick_book_id, brick_books(id, title))'
        ).eq('member_id', member_id).execute().data or []
    except Exception:
        bb_parts = []
    brick_sessions = []
    for p in bb_parts:
        s = p.get('brick_book_sessions') or {}
        b = s.get('brick_books') or {}
        brick_sessions.append({
            'book_id': b.get('id'), 'book_title': b.get('title'),
            'session_id': s.get('id'), 'meeting_date': s.get('meeting_date'),
        })
    brick_sessions.sort(key=lambda x: x.get('meeting_date') or '', reverse=True)

    # 소모임 세션 참여
    try:
        sg_parts = supabase.table('study_session_members').select(
            'session_id, study_group_sessions(id, meeting_date, notes, study_group_id, study_groups(id, name))'
        ).eq('member_id', member_id).execute().data or []
    except Exception:
        sg_parts = []
    study_sessions = []
    for p in sg_parts:
        s = p.get('study_group_sessions') or {}
        g = s.get('study_groups') or {}
        study_sessions.append({
            'group_id': g.get('id'), 'group_name': g.get('name'),
            'session_id': s.get('id'), 'meeting_date': s.get('meeting_date'),
        })
    study_sessions.sort(key=lambda x: x.get('meeting_date') or '', reverse=True)

    return {
        'seminar_records': seminar_records,
        'seminar_count': len(seminar_records),
        'facilitator_count': facilitator_count,
        'brick_sessions': brick_sessions,
        'study_sessions': study_sessions,
    }


# --- 장르 API ---
@app.route('/api/genres')
@login_required(role="ANY")
def list_genres():
    return jsonify({'genres': _load_genres()})


@app.route('/api/admin/genres/create', methods=['POST'])
@login_required(role="admin")
def create_genre():
    try:
        name = ((request.json or {}).get('name') or '').strip()
        if not name:
            return jsonify({'status': 'error', 'message': '장르명을 입력하세요.'}), 400
        existing = supabase.table('genres').select('id').eq('name', name).execute().data or []
        if existing:
            return jsonify({'status': 'error', 'message': '이미 존재하는 장르입니다.'}), 400
        res = supabase.table('genres').insert({'name': name, 'is_default': False}).execute()
        return jsonify({'status': 'success', 'genre': res.data[0]})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/admin/genres/<genre_id>/delete', methods=['POST'])
@login_required(role="admin")
def delete_genre(genre_id):
    try:
        cur = supabase.table('genres').select('is_default').eq('id', genre_id).single().execute().data
        if cur and cur.get('is_default'):
            return jsonify({'status': 'error', 'message': '기본 장르는 삭제할 수 없습니다.'}), 400
        supabase.table('genres').delete().eq('id', genre_id).execute()
        return jsonify({'status': 'success'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


# ============================================================================
# 스페셜 이벤트 (MT, 워크숍, 강연 등 1회성 행사)
# ============================================================================

@app.route('/admin/special_events')
@login_required(role="admin")
def admin_special_events():
    """관리자: 스페셜 이벤트 목록 + 생성/관리 페이지"""
    try:
        events = supabase.table('special_events').select('*') \
            .order('event_date', desc=True).execute().data or []
        # 각 이벤트별 참석자 수
        for evt in events:
            cnt_res = supabase.table('special_event_attendees') \
                .select('id', count='exact').eq('event_id', evt['id']).execute()
            evt['attendee_count'] = cnt_res.count or 0
        terms = supabase.table('seminar_terms').select('id, name, start_date, end_date') \
            .order('start_date', desc=True).execute().data or []
        return render_template('admin_special_events.html', events=events, terms=terms)
    except Exception as e:
        app.logger.error(f"admin_special_events error: {e}")
        flash("스페셜 이벤트 페이지 로드 중 오류.", "danger")
        return redirect(url_for('admin_dashboard'))


@app.route('/admin/special_events/<event_id>')
@login_required(role="admin")
def admin_special_event_detail(event_id):
    """관리자: 단일 이벤트 상세 + 참석자 관리"""
    try:
        evt = supabase.table('special_events').select('*').eq('id', event_id).single().execute().data
        if not evt:
            flash("이벤트를 찾을 수 없습니다.", "danger")
            return redirect(url_for('admin_special_events'))
        attendees = supabase.table('special_event_attendees') \
            .select('id, member_id, role, note, members(id, name, student_id, department)') \
            .eq('event_id', event_id).order('created_at').execute().data or []
        all_members = supabase.table('members').select('id, name, student_id, department') \
            .eq('is_active', True).order('name').execute().data or []
        attendee_ids = {a['member_id'] for a in attendees}
        candidates = [m for m in all_members if m['id'] not in attendee_ids]
        return render_template('admin_special_event_detail.html',
                               event=evt, attendees=attendees, candidates=candidates)
    except Exception as e:
        app.logger.error(f"admin_special_event_detail error: {e}")
        flash("이벤트 상세 로드 중 오류.", "danger")
        return redirect(url_for('admin_special_events'))


@app.route('/api/admin/special_events/create', methods=['POST'])
@login_required(role="admin")
def create_special_event():
    try:
        data = request.json or {}
        name = (data.get('name') or '').strip()
        event_date = data.get('event_date')
        if not name or not event_date:
            return jsonify({'error': '이름과 날짜는 필수입니다.'}), 400
        payload = {
            'name': name,
            'description': (data.get('description') or '').strip() or None,
            'event_date': event_date,
            'end_date': data.get('end_date') or None,
            'category': (data.get('category') or 'event'),
            'term_id': data.get('term_id') or None,
            'created_by': session.get('user_id'),
        }
        res = supabase.table('special_events').insert(payload).execute()
        return jsonify({'status': 'success', 'event': res.data[0]})
    except Exception as e:
        app.logger.error(f"create_special_event error: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/admin/special_events/<event_id>/update', methods=['POST'])
@login_required(role="admin")
def update_special_event(event_id):
    try:
        data = request.json or {}
        update = {}
        for k in ('name', 'description', 'event_date', 'end_date', 'category', 'term_id'):
            if k in data:
                update[k] = data[k] if data[k] != '' else None
        if 'is_active' in data:
            update['is_active'] = bool(data['is_active'])
        if not update:
            return jsonify({'error': '수정할 내용이 없습니다.'}), 400
        supabase.table('special_events').update(update).eq('id', event_id).execute()
        return jsonify({'status': 'success'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/admin/special_events/<event_id>/toggle_active', methods=['POST'])
@login_required(role="admin")
def toggle_special_event(event_id):
    try:
        cur = supabase.table('special_events').select('is_active').eq('id', event_id).single().execute().data
        if not cur:
            return jsonify({'error': '이벤트를 찾을 수 없습니다.'}), 404
        new_state = not bool(cur.get('is_active'))
        supabase.table('special_events').update({'is_active': new_state}).eq('id', event_id).execute()
        return jsonify({'status': 'success', 'is_active': new_state})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/admin/special_events/<event_id>/delete', methods=['POST'])
@login_required(role="admin")
def delete_special_event(event_id):
    try:
        # cascade로 참석자도 함께 삭제됨
        supabase.table('special_events').delete().eq('id', event_id).execute()
        return jsonify({'status': 'success'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/admin/special_events/<event_id>/attendees/add', methods=['POST'])
@login_required(role="admin")
def add_special_event_attendee(event_id):
    try:
        data = request.json or {}
        member_ids = data.get('member_ids') or []
        if isinstance(member_ids, (int, str)):
            member_ids = [member_ids]
        if not member_ids:
            return jsonify({'error': '추가할 회원을 선택하세요.'}), 400
        rows = [{'event_id': event_id, 'member_id': int(mid),
                 'role': data.get('role', 'attendee'),
                 'note': (data.get('note') or '').strip() or None}
                for mid in member_ids]
        # ON CONFLICT DO NOTHING 동작 — 이미 등록된 멤버는 스킵
        supabase.table('special_event_attendees').upsert(rows, on_conflict='event_id,member_id').execute()
        return jsonify({'status': 'success', 'added': len(rows)})
    except Exception as e:
        app.logger.error(f"add_special_event_attendee error: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/admin/special_events/<event_id>/attendees/<int:member_id>/remove', methods=['POST'])
@login_required(role="admin")
def remove_special_event_attendee(event_id, member_id):
    try:
        supabase.table('special_event_attendees').delete() \
            .eq('event_id', event_id).eq('member_id', member_id).execute()
        return jsonify({'status': 'success'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ============================================================================
# 출석 매트릭스 (관리자 도구)
# 가로축: 세미나 주차(월/목 묶어서 1주차로 표시), 세로축: 회원, 셀: O/X
# 데이터 소스: history (확정된 세미나 진행 기록의 present 명단)
# ============================================================================

def _build_attendance_matrix(start_date=None, end_date=None):
    """history의 present 명단 + members 명부로 출석 매트릭스를 생성.
    Returns: (members_list, weeks_list, matrix_dict[member_id][week_key]=bool)
    """
    # 1) 회원 명부 (활성 + 비활성 모두 — 과거 회원 기록 보존)
    members = supabase.table('members').select('id, name, student_id, department, is_active') \
        .order('name').execute().data or []

    # 2) 세미나 history 조회 (날짜 범위 필터)
    q = supabase.table('history').select('id, date, present, book_title, book_genre')
    if start_date:
        q = q.gte('date', start_date)
    if end_date:
        q = q.lte('date', end_date)
    histories = q.order('date').execute().data or []

    # 3) 주차 단위로 묶기 — 같은 주의 월/목 출석을 합쳐 OR 연산
    from datetime import datetime as _dt
    name_to_id = {m['name']: m['id'] for m in members}
    week_meta = {}        # week_key -> {label, dates:[date_str], titles:set}
    matrix = {}           # member_id -> {week_key: True}

    for h in histories:
        try:
            d = _dt.strptime(h['date'], '%Y-%m-%d').date()
        except Exception:
            continue
        # ISO 주차로 묶기 (월요일 기준)
        iso_year, iso_week, _ = d.isocalendar()
        week_key = f"{iso_year}-W{iso_week:02d}"
        meta = week_meta.setdefault(week_key, {'label': '', 'dates': [], 'titles': set(), 'sort': d})
        meta['dates'].append(h['date'])
        if h.get('book_title'):
            meta['titles'].add(h['book_title'])
        if d < meta['sort']:
            meta['sort'] = d

        # 출석자 처리 — present 는 이름 배열
        present_names = h.get('present') or []
        for nm in present_names:
            if not nm:
                continue
            mid = name_to_id.get(nm)
            if mid is None:
                continue
            matrix.setdefault(mid, {})[week_key] = True

    # 4) 주차 정렬 + 라벨 만들기
    weeks = []
    for wk, meta in week_meta.items():
        first_date = min(meta['dates'])
        try:
            d = _dt.strptime(first_date, '%Y-%m-%d').date()
            label = f"{d.month}/{d.day}~"
        except Exception:
            label = first_date
        title = ' / '.join(sorted(meta['titles'])) if meta['titles'] else '(미정)'
        weeks.append({'key': wk, 'label': label, 'title': title, 'sort': meta['sort']})
    weeks.sort(key=lambda w: w['sort'])

    return members, weeks, matrix


@app.route('/admin/attendance_matrix')
@login_required(role="admin")
def admin_attendance_matrix():
    start_date = request.args.get('start_date') or None
    end_date = request.args.get('end_date') or None
    term_id = request.args.get('term_id') or None

    # 학기 선택 시 학기 기간으로 자동 채움
    if term_id and not (start_date and end_date):
        try:
            t = supabase.table('seminar_terms').select('start_date, end_date') \
                .eq('id', term_id).single().execute().data
            if t:
                start_date = start_date or t['start_date']
                end_date = end_date or t['end_date']
        except Exception:
            pass

    try:
        members, weeks, matrix = _build_attendance_matrix(start_date, end_date)
        terms = supabase.table('seminar_terms').select('id, name, start_date, end_date') \
            .order('start_date', desc=True).execute().data or []

        # 회원별 출석 횟수 집계
        member_counts = {m['id']: sum(1 for w in weeks if matrix.get(m['id'], {}).get(w['key'])) for m in members}

        return render_template('admin_attendance_matrix.html',
                               members=members, weeks=weeks, matrix=matrix,
                               member_counts=member_counts,
                               terms=terms, term_id=term_id,
                               start_date=start_date or '', end_date=end_date or '')
    except Exception as e:
        app.logger.error(f"admin_attendance_matrix error: {e}")
        flash("매트릭스 로드 중 오류.", "danger")
        return redirect(url_for('admin_dashboard'))


@app.route('/admin/attendance_matrix/export')
@login_required(role="admin")
def admin_attendance_matrix_export():
    """엑셀(.xlsx)로 출석 매트릭스 내보내기"""
    start_date = request.args.get('start_date') or None
    end_date = request.args.get('end_date') or None
    term_id = request.args.get('term_id') or None
    if term_id and not (start_date and end_date):
        try:
            t = supabase.table('seminar_terms').select('start_date, end_date, name') \
                .eq('id', term_id).single().execute().data
            if t:
                start_date = start_date or t['start_date']
                end_date = end_date or t['end_date']
        except Exception:
            pass

    members, weeks, matrix = _build_attendance_matrix(start_date, end_date)

    # DataFrame 구성: 행=회원, 열=주차
    columns = ['이름', '학번', '소속'] + [f"{w['label']} {w['title']}" for w in weeks] + ['출석횟수']
    rows = []
    for m in members:
        row = [m.get('name', ''), m.get('student_id', '') or '', m.get('department', '') or '']
        cnt = 0
        for w in weeks:
            attended = bool(matrix.get(m['id'], {}).get(w['key']))
            row.append('O' if attended else 'X')
            if attended:
                cnt += 1
        row.append(cnt)
        rows.append(row)

    df = pd.DataFrame(rows, columns=columns)
    buf = BytesIO()
    with pd.ExcelWriter(buf, engine='openpyxl') as writer:
        df.to_excel(writer, sheet_name='출석매트릭스', index=False)
    buf.seek(0)

    fname_parts = ['attendance_matrix']
    if start_date: fname_parts.append(start_date)
    if end_date: fname_parts.append(end_date)
    fname = '_'.join(fname_parts) + '.xlsx'

    return send_file(buf,
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                     as_attachment=True, download_name=fname)


# --- 학기 필터 헬퍼 ---
def _get_terms_for_filter():
    """기록 페이지의 학기 필터 드롭다운에 사용할 학기 목록 (최신순)."""
    try:
        return supabase.table('seminar_terms').select('id, name, start_date, end_date') \
            .order('start_date', desc=True).execute().data or []
    except Exception:
        return []


def _get_term_range(term_id):
    """선택된 term_id의 (start_date, end_date, term_dict) 반환. 없으면 (None, None, None)."""
    if not term_id:
        return None, None, None
    try:
        term = supabase.table('seminar_terms').select('*').eq('id', term_id).single().execute().data
        if not term:
            return None, None, None
        return term['start_date'], term['end_date'], term
    except Exception:
        return None, None, None


def _date_in_range(d, start, end):
    """문자열 또는 date를 받아 [start, end] 범위에 있는지 확인."""
    if not d or not start or not end:
        return False
    s = str(d)[:10]
    return str(start)[:10] <= s <= str(end)[:10]


# --- 도움말 페이지 ---
@app.route('/help/admin')
@login_required(role="admin")
def help_admin():
    return render_template('help_admin.html')


@app.route('/help/member')
@login_required(role="ANY")
def help_member():
    return render_template('help_member.html')


# --- 기록 허브 ---
@app.route('/records')
@login_required(role="admin")
def records_hub():
    try:
        seminar_count = supabase.table('history').select('id', count='exact').execute().count or 0
        bb_count = supabase.table('brick_books').select('id', count='exact').execute().count or 0
        sg_count = supabase.table('study_groups').select('id', count='exact').execute().count or 0
        member_count = supabase.table('members').select('id', count='exact').eq('is_active', True).execute().count or 0
    except Exception as e:
        app.logger.warning(f"records_hub count error: {e}")
        seminar_count = bb_count = sg_count = member_count = 0
    return render_template('records_hub.html',
                           seminar_count=seminar_count, brick_book_count=bb_count,
                           study_group_count=sg_count, member_count=member_count)


# --- 회원명부 ---
@app.route('/records/members')
@login_required(role="admin")
def records_members():
    try:
        members = supabase.table('members').select(
            'id, name, gender, department, student_id, recruiting_class, member_status, role, email'
        ).eq('is_active', True).order('name').execute().data or []
        # 회원명부 클릭 시 미리 활동 요약을 보여주기 위해 각 멤버의 활동 카운트 집계
        if members:
            # 1) 세미나/발제 카운트 (history.groups 이름 매칭)
            history_rows = supabase.table('history').select('groups, facilitators').execute().data or []
            seminar_cnt, fac_cnt = {}, {}
            for r in history_rows:
                names = set()
                for g in (r.get('groups') or []):
                    if isinstance(g, list): names.update(g)
                    elif isinstance(g, str): names.add(g)
                facs = set(r.get('facilitators') or [])
                for n in names: seminar_cnt[n] = seminar_cnt.get(n, 0) + 1
                for n in facs: fac_cnt[n] = fac_cnt.get(n, 0) + 1
            # 2) 벽돌책 + 소모임 세션 카운트 (member_id 기반)
            try:
                bb_rows = supabase.table('brick_session_members').select('member_id').execute().data or []
            except Exception: bb_rows = []
            try:
                sg_rows = supabase.table('study_session_members').select('member_id').execute().data or []
            except Exception: sg_rows = []
            bb_cnt, sg_cnt = {}, {}
            for r in bb_rows: bb_cnt[r['member_id']] = bb_cnt.get(r['member_id'], 0) + 1
            for r in sg_rows: sg_cnt[r['member_id']] = sg_cnt.get(r['member_id'], 0) + 1
            for m in members:
                m['seminar_count'] = seminar_cnt.get(m['name'], 0)
                m['facilitator_count'] = fac_cnt.get(m['name'], 0)
                m['brick_count'] = bb_cnt.get(m['id'], 0)
                m['study_count'] = sg_cnt.get(m['id'], 0)
    except Exception as e:
        app.logger.error(f"records_members error: {e}", exc_info=True)
        flash(f"멤버 로딩 오류: {e}", 'danger')
        members = []
    return render_template('records_members.html', members=members)


@app.route('/records/members/<int:member_id>')
@login_required(role="ANY")
def records_member_profile(member_id):
    if not _can_view_member_profile(member_id):
        flash("접근 권한이 없습니다.", "danger")
        return redirect(url_for('main_index'))
    try:
        member = supabase.table('members').select('*').eq('id', member_id).single().execute().data
        if not member:
            flash("멤버를 찾을 수 없습니다.", "danger")
            return redirect(url_for('records_members') if session.get('user_role') == 'admin' else url_for('my_page'))
        activity = _aggregate_member_activity(member_id, member.get('name', ''))
        special_events = _member_special_events(member_id)
        return render_template('records_member_profile.html', member=member,
                               special_events=special_events, **activity)
    except Exception as e:
        app.logger.error(f"records_member_profile error: {e}", exc_info=True)
        flash(f"프로필 로딩 오류: {e}", 'danger')
        return redirect(url_for('records_hub'))


# --- 세미나 ---
@app.route('/records/seminars')
@login_required(role="admin")
def records_seminars():
    term_id = request.args.get('term_id') or ''
    try:
        q = supabase.table('history').select('*').order('date', desc=True)
        start, end, _ = _get_term_range(term_id)
        if start and end:
            q = q.gte('date', start).lte('date', end)
        history = q.execute().data or []
        for row in history:
            groups = row.get('groups') or []
            present = []
            for g in groups:
                if isinstance(g, list):
                    present.extend(g)
                elif isinstance(g, str):
                    present.append(g)
            row['present_count'] = len(present)
            row['group_count'] = len(groups) if groups and isinstance(groups[0], list) else 0
            row['facilitator_count'] = len(row.get('facilitators') or [])

        # 6개월 단위 버킷 그룹화 (예: "2025년 상반기", "2025년 하반기")
        buckets = []  # [{'key': str, 'label': str, 'rows': [..]}]
        seen = {}
        for row in history:
            try:
                d = date.fromisoformat(row['date'])
                half = '상반기' if d.month <= 6 else '하반기'
                key = f"{d.year}-{1 if d.month <= 6 else 2}"
                label = f"{d.year}년 {half}"
            except Exception:
                key, label = 'unknown', '날짜 미상'
            if key not in seen:
                seen[key] = {'key': key, 'label': label, 'rows': []}
                buckets.append(seen[key])
            seen[key]['rows'].append(row)
        # history는 이미 date desc 정렬이므로 buckets도 자연스럽게 최신순
        genres = _load_genres()
        terms = _get_terms_for_filter()
    except Exception as e:
        app.logger.error(f"records_seminars error: {e}", exc_info=True)
        flash(f"오류: {e}", 'danger')
        history, genres, terms, buckets = [], [], [], []
    return render_template('records_seminars.html', history=history, genres=genres,
                           terms=terms, selected_term_id=term_id, buckets=buckets)


@app.route('/records/seminars/<history_id>')
@login_required(role="admin")
def records_seminar_detail(history_id):
    try:
        row = supabase.table('history').select('*').eq('id', history_id).single().execute().data
        groups = row.get('groups') or []
        all_present = []
        for g in groups:
            if isinstance(g, list):
                all_present.extend(g)
            elif isinstance(g, str):
                all_present.append(g)
        member_map = {}
        if all_present:
            mres = supabase.table('members').select('id, name').in_('name', list(set(all_present))).execute().data or []
            member_map = {m['name']: m['id'] for m in mres}
        genres = _load_genres()
        all_members = supabase.table('members').select('id, name').eq('is_active', True).order('name').execute().data or []
        return render_template('records_seminar_detail.html',
                               row=row, groups=groups, member_map=member_map,
                               genres=genres, total_present=len(all_present),
                               all_members=all_members)
    except Exception as e:
        app.logger.error(f"records_seminar_detail error: {e}", exc_info=True)
        flash(f"오류: {e}", 'danger')
        return redirect(url_for('records_seminars'))


@app.route('/api/admin/history/<history_id>/update_meta', methods=['POST'])
@login_required(role="admin")
def update_history_meta(history_id):
    """세미나 기록 메타 + 본문(날짜/발제자/조) 수정.
    허용 필드: book_title, genre, date, facilitators(list[str]), groups(list[list[str]])
    """
    try:
        data = request.json or {}
        update = {}
        if 'book_title' in data:
            update['book_title'] = (data.get('book_title') or '').strip() or None
        if 'genre' in data:
            update['genre'] = (data.get('genre') or '').strip() or None
        if 'date' in data:
            d = (data.get('date') or '').strip()
            if not d:
                return jsonify({'status': 'error', 'message': '날짜는 비울 수 없습니다.'}), 400
            update['date'] = d
        if 'facilitators' in data:
            facs = data.get('facilitators') or []
            if not isinstance(facs, list):
                return jsonify({'status': 'error', 'message': 'facilitators는 배열이어야 합니다.'}), 400
            update['facilitators'] = [str(x).strip() for x in facs if str(x).strip()]
        if 'groups' in data:
            groups = data.get('groups') or []
            if not isinstance(groups, list) or not all(isinstance(g, list) for g in groups):
                return jsonify({'status': 'error', 'message': 'groups는 배열의 배열이어야 합니다.'}), 400
            cleaned = [[str(n).strip() for n in g if str(n).strip()] for g in groups]
            update['groups'] = [g for g in cleaned if g]  # 빈 조 제거
        if not update:
            return jsonify({'status': 'error', 'message': '변경할 필드가 없습니다.'}), 400

        # groups/date 변경 시 co_matrix 재계산
        groups_changed = 'groups' in update
        date_changed = 'date' in update
        old_row = None
        if groups_changed or date_changed:
            old_res = supabase.table('history').select('groups, date').eq('id', history_id).execute()
            old_row = (old_res.data or [None])[0]

        supabase.table('history').update(update).eq('id', history_id).execute()

        if old_row is not None and (groups_changed or date_changed):
            old_groups = old_row.get('groups') or []
            old_date = old_row.get('date') or ''
            new_groups = update.get('groups', old_groups)
            new_date = update.get('date', old_date)
            # 기존 페어 카운트 차감 후 새 페어 카운트 가산
            _adjust_co_matrix(old_groups, old_date, -1)
            _adjust_co_matrix(new_groups, new_date, +1)

        return jsonify({'status': 'success'})
    except Exception as e:
        app.logger.error(f"update_history_meta error: {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/admin/history/<history_id>/delete', methods=['POST'])
@login_required(role="admin")
def records_history_delete(history_id):
    """세미나 기록 삭제 + co_matrix 차감."""
    try:
        old_res = supabase.table('history').select('groups, date').eq('id', history_id).execute()
        old_row = (old_res.data or [None])[0]
        supabase.table('history').delete().eq('id', history_id).execute()
        if old_row:
            _adjust_co_matrix(old_row.get('groups') or [], old_row.get('date') or '', -1)
        return jsonify({'status': 'success'})
    except Exception as e:
        app.logger.error(f"records_history_delete error: {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': str(e)}), 500


# --- 벽돌책 ---
@app.route('/records/brick_books')
@login_required(role="admin")
def records_brick_books():
    term_id = request.args.get('term_id') or ''
    try:
        books = supabase.table('brick_books').select('*').order('created_at', desc=True).execute().data or []
        start, end, _ = _get_term_range(term_id)
        if books:
            ids = [b['id'] for b in books]
            sq = supabase.table('brick_book_sessions').select('brick_book_id, meeting_date').in_('brick_book_id', ids)
            if start and end:
                sq = sq.gte('meeting_date', start).lte('meeting_date', end)
            sess_res = sq.execute().data or []
            cnt = {}
            for s in sess_res:
                cnt[s['brick_book_id']] = cnt.get(s['brick_book_id'], 0) + 1
            for b in books:
                b['session_count'] = cnt.get(b['id'], 0)
            # 학기 필터링 시: 해당 학기 내 세션이 있는 책만 표시
            if start and end:
                books = [b for b in books if b['session_count'] > 0]
        terms = _get_terms_for_filter()
    except Exception as e:
        app.logger.error(f"records_brick_books error: {e}", exc_info=True)
        flash(f"오류: {e}", 'danger')
        books, terms = [], []
    return render_template('records_brick_books.html', books=books,
                           terms=terms, selected_term_id=term_id)


@app.route('/records/brick_books/<book_id>')
@login_required(role="admin")
def records_brick_book_detail(book_id):
    try:
        book = supabase.table('brick_books').select('*').eq('id', book_id).single().execute().data
        sessions_res = supabase.table('brick_book_sessions').select('*') \
            .eq('brick_book_id', book_id).order('meeting_date', desc=True).execute()
        sessions = sessions_res.data or []
        sess_ids = [s['id'] for s in sessions]
        member_map_by_sess = {}
        if sess_ids:
            parts = supabase.table('brick_session_members').select('session_id, member_id, members(id, name)') \
                .in_('session_id', sess_ids).execute().data or []
            for p in parts:
                sid = p['session_id']
                member_map_by_sess.setdefault(sid, []).append(p.get('members') or {})
        for s in sessions:
            s['members'] = member_map_by_sess.get(s['id'], [])
        all_members = supabase.table('members').select('id, name').eq('is_active', True).order('name').execute().data or []
        return render_template('records_brick_book_detail.html',
                               book=book, sessions=sessions, all_members=all_members)
    except Exception as e:
        app.logger.error(f"records_brick_book_detail error: {e}", exc_info=True)
        flash(f"오류: {e}", 'danger')
        return redirect(url_for('records_brick_books'))


@app.route('/api/admin/brick_books/create', methods=['POST'])
@login_required(role="admin")
def brick_book_create():
    try:
        data = request.json or {}
        title = (data.get('title') or '').strip()
        if not title:
            return jsonify({'status': 'error', 'message': '제목은 필수입니다.'}), 400
        res = supabase.table('brick_books').insert({
            'title': title,
            'notes': (data.get('notes') or '').strip() or None,
        }).execute()
        return jsonify({'status': 'success', 'book': res.data[0]})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/admin/brick_books/<book_id>/delete', methods=['POST'])
@login_required(role="admin")
def brick_book_delete(book_id):
    try:
        supabase.table('brick_books').delete().eq('id', book_id).execute()
        return jsonify({'status': 'success'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/admin/brick_books/<book_id>/sessions/add', methods=['POST'])
@login_required(role="admin")
def brick_session_add(book_id):
    try:
        data = request.json or {}
        meeting_date = data.get('meeting_date')
        if not meeting_date:
            return jsonify({'status': 'error', 'message': '날짜가 필요합니다.'}), 400
        sess = supabase.table('brick_book_sessions').insert({
            'brick_book_id': book_id,
            'meeting_date': meeting_date,
            'notes': (data.get('notes') or '').strip() or None,
        }).execute().data[0]
        member_ids = [int(m) for m in (data.get('member_ids') or []) if m]
        if member_ids:
            supabase.table('brick_session_members').insert([
                {'session_id': sess['id'], 'member_id': mid} for mid in member_ids
            ]).execute()
        return jsonify({'status': 'success', 'session': sess})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/admin/brick_sessions/<session_id>/delete', methods=['POST'])
@login_required(role="admin")
def brick_session_delete(session_id):
    try:
        supabase.table('brick_book_sessions').delete().eq('id', session_id).execute()
        return jsonify({'status': 'success'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


# --- 소모임 ---
@app.route('/records/study_groups')
@login_required(role="admin")
def records_study_groups():
    term_id = request.args.get('term_id') or ''
    try:
        groups = supabase.table('study_groups').select('*').order('created_at', desc=True).execute().data or []
        start, end, _ = _get_term_range(term_id)
        if groups:
            ids = [g['id'] for g in groups]
            sq = supabase.table('study_group_sessions').select('study_group_id, meeting_date').in_('study_group_id', ids)
            if start and end:
                sq = sq.gte('meeting_date', start).lte('meeting_date', end)
            sess_res = sq.execute().data or []
            cnt = {}
            for s in sess_res:
                cnt[s['study_group_id']] = cnt.get(s['study_group_id'], 0) + 1
            for g in groups:
                g['session_count'] = cnt.get(g['id'], 0)
            if start and end:
                groups = [g for g in groups if g['session_count'] > 0]
        terms = _get_terms_for_filter()
    except Exception as e:
        app.logger.error(f"records_study_groups error: {e}", exc_info=True)
        flash(f"오류: {e}", 'danger')
        groups, terms = [], []
    return render_template('records_study_groups.html', groups=groups,
                           terms=terms, selected_term_id=term_id)


@app.route('/records/study_groups/<group_id>')
@login_required(role="admin")
def records_study_group_detail(group_id):
    try:
        group = supabase.table('study_groups').select('*').eq('id', group_id).single().execute().data
        sessions_res = supabase.table('study_group_sessions').select('*') \
            .eq('study_group_id', group_id).order('meeting_date', desc=True).execute()
        sessions = sessions_res.data or []
        sess_ids = [s['id'] for s in sessions]
        member_map_by_sess = {}
        if sess_ids:
            parts = supabase.table('study_session_members').select('session_id, member_id, members(id, name)') \
                .in_('session_id', sess_ids).execute().data or []
            for p in parts:
                sid = p['session_id']
                member_map_by_sess.setdefault(sid, []).append(p.get('members') or {})
        for s in sessions:
            s['members'] = member_map_by_sess.get(s['id'], [])
        all_members = supabase.table('members').select('id, name').eq('is_active', True).order('name').execute().data or []
        return render_template('records_study_group_detail.html',
                               group=group, sessions=sessions, all_members=all_members)
    except Exception as e:
        app.logger.error(f"records_study_group_detail error: {e}", exc_info=True)
        flash(f"오류: {e}", 'danger')
        return redirect(url_for('records_study_groups'))


@app.route('/api/admin/study_groups/create', methods=['POST'])
@login_required(role="admin")
def study_group_create():
    try:
        data = request.json or {}
        name = (data.get('name') or '').strip()
        if not name:
            return jsonify({'status': 'error', 'message': '이름은 필수입니다.'}), 400
        res = supabase.table('study_groups').insert({
            'name': name,
            'notes': (data.get('notes') or '').strip() or None,
        }).execute()
        return jsonify({'status': 'success', 'group': res.data[0]})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/admin/study_groups/<group_id>/delete', methods=['POST'])
@login_required(role="admin")
def study_group_delete(group_id):
    try:
        supabase.table('study_groups').delete().eq('id', group_id).execute()
        return jsonify({'status': 'success'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/admin/study_groups/<group_id>/sessions/add', methods=['POST'])
@login_required(role="admin")
def study_session_add(group_id):
    try:
        data = request.json or {}
        meeting_date = data.get('meeting_date')
        if not meeting_date:
            return jsonify({'status': 'error', 'message': '날짜가 필요합니다.'}), 400
        sess = supabase.table('study_group_sessions').insert({
            'study_group_id': group_id,
            'meeting_date': meeting_date,
            'notes': (data.get('notes') or '').strip() or None,
        }).execute().data[0]
        member_ids = [int(m) for m in (data.get('member_ids') or []) if m]
        if member_ids:
            supabase.table('study_session_members').insert([
                {'session_id': sess['id'], 'member_id': mid} for mid in member_ids
            ]).execute()
        return jsonify({'status': 'success', 'session': sess})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/admin/study_sessions/<session_id>/delete', methods=['POST'])
@login_required(role="admin")
def study_session_delete(session_id):
    try:
        supabase.table('study_group_sessions').delete().eq('id', session_id).execute()
        return jsonify({'status': 'success'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


# --- 통계 ---
@app.route('/records/analytics')
@login_required(role="admin")
def records_analytics():
    term_id = request.args.get('term_id') or ''
    try:
        start, end, _ = _get_term_range(term_id)
        hq = supabase.table('history').select('date, genre, groups')
        if start and end:
            hq = hq.gte('date', start).lte('date', end)
        history = hq.execute().data or []
        genre_counts, monthly_counts, member_attend = {}, {}, {}
        for row in history:
            g = row.get('genre') or '미분류'
            genre_counts[g] = genre_counts.get(g, 0) + 1
            d = row.get('date')
            if d:
                ym = str(d)[:7]
                monthly_counts[ym] = monthly_counts.get(ym, 0) + 1
            groups = row.get('groups') or []
            for grp in groups:
                for n in (grp if isinstance(grp, list) else [grp]):
                    member_attend[n] = member_attend.get(n, 0) + 1
        top_attendees = sorted(member_attend.items(), key=lambda x: x[1], reverse=True)[:15]

        # 벽돌책/소모임 월별 세션 카운트 (학기 필터 적용)
        bb_monthly, sg_monthly = {}, {}
        try:
            bbq = supabase.table('brick_book_sessions').select('meeting_date')
            if start and end:
                bbq = bbq.gte('meeting_date', start).lte('meeting_date', end)
            bb_sess = bbq.execute().data or []
            for s in bb_sess:
                ym = str(s.get('meeting_date') or '')[:7]
                if ym: bb_monthly[ym] = bb_monthly.get(ym, 0) + 1
        except Exception: pass
        try:
            sgq = supabase.table('study_group_sessions').select('meeting_date')
            if start and end:
                sgq = sgq.gte('meeting_date', start).lte('meeting_date', end)
            sg_sess = sgq.execute().data or []
            for s in sg_sess:
                ym = str(s.get('meeting_date') or '')[:7]
                if ym: sg_monthly[ym] = sg_monthly.get(ym, 0) + 1
        except Exception: pass

        # 벽돌책/소모임 카운트: 학기 내 세션이 있는 것만
        if start and end:
            bb_count = len({s.get('brick_book_id') for s in (supabase.table('brick_book_sessions')
                .select('brick_book_id, meeting_date').gte('meeting_date', start).lte('meeting_date', end)
                .execute().data or [])})
            sg_count = len({s.get('study_group_id') for s in (supabase.table('study_group_sessions')
                .select('study_group_id, meeting_date').gte('meeting_date', start).lte('meeting_date', end)
                .execute().data or [])})
        else:
            bb_count = supabase.table('brick_books').select('id', count='exact').execute().count or 0
            sg_count = supabase.table('study_groups').select('id', count='exact').execute().count or 0

        terms = _get_terms_for_filter()
        return render_template('records_analytics.html',
                               total_seminars=len(history),
                               total_brick_books=bb_count,
                               total_study_groups=sg_count,
                               genre_counts=genre_counts,
                               monthly_counts=dict(sorted(monthly_counts.items())),
                               bb_monthly=dict(sorted(bb_monthly.items())),
                               sg_monthly=dict(sorted(sg_monthly.items())),
                               top_attendees=top_attendees,
                               terms=terms, selected_term_id=term_id)
    except Exception as e:
        app.logger.error(f"records_analytics error: {e}", exc_info=True)
        flash(f"오류: {e}", 'danger')
        return redirect(url_for('records_hub'))




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
