"""Explicit local-only preview entry point; never imported by app.py.

Uses synthetic club rows and the real Kakao callback with fake provider replies.
No production .env, Supabase or Kakao requests are allowed.
"""
import os
from pathlib import Path
import secrets
import sys
from urllib.parse import urlsplit
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
RUNTIME=ROOT.parent/'bookbanwoo-wiki'/'integration-runtime'
if not (RUNTIME/'data.db').is_file():
    raise RuntimeError('Prepare the separate local integration runtime first')
key=RUNTIME/'bridge-secret.txt'
if not key.exists(): key.write_text(secrets.token_urlsafe(48),encoding='utf-8')
os.environ.update(PYTHON_DOTENV_DISABLED='1',FLASK_SECRET_KEY=secrets.token_urlsafe(48),
    SUPABASE_URL='http://127.0.0.1:9',SUPABASE_SERVICE_KEY='local-preview-only',
    PUBLIC_BASE_URL='http://127.0.0.1:5105',SESSION_COOKIE_SECURE='0',
    REQUIRE_ORIGIN_AUTH='',ORIGIN_AUTH_SECRET='',KAKAO_PROXY_REDIRECT_URI='',
    KAKAO_OAUTH_CLIENT_ID='local-preview',KAKAO_OAUTH_CLIENT_SECRET='',
    KAKAO_REDIRECT_URI='http://127.0.0.1:5105/login/kakao/callback',
    WIKI_ENABLED='1',WIKI_UPSTREAM='http://127.0.0.1:5097',
    WIKI_DATABASE=str(RUNTIME/'data.db'),WIKI_IDENTITY_SECRET=key.read_text(encoding='utf-8'))
from testing.test_home_overview import fixture
from testing._fake_supabase import FakeSupabase
from testing.test_wiki_integration import wiki_fixture
from datetime import datetime,timedelta,timezone
rows=fixture()
rows.update(wiki_fixture(datetime.now(timezone(timedelta(hours=9))).date()))
rows['members'].append(dict(rows['members'][0],id=3,social_id='9003',name='가입 대기 예시',account_status='pending'))
rows['members'][0]['student_id']='202600001'
rows['members'][1]['student_id']='202600002'
for row in rows['seminar_weeks']: row['term_id']='current'
for row in rows['seminar_sessions']: row['term_id']='current'
fake=FakeSupabase(rows)
with patch('dotenv.load_dotenv'),patch('supabase.create_client',return_value=fake):
    import app as module
from flask import abort,redirect,render_template_string,request,session,url_for
module.app.config.update(WIKI_LOCAL_PREVIEW=True,SESSION_COOKIE_NAME='wiki_integration_review',
                         SESSION_COOKIE_SECURE=False,TRUSTED_HOSTS=['127.0.0.1'],TEMPLATES_AUTO_RELOAD=True)

# Guard every outbound HTTP call made by this preview process.
import requests
_request=requests.sessions.Session.request
def local_request(self,method,url,*args,**kwargs):
    parsed=urlsplit(url)
    if parsed.hostname!='127.0.0.1' or parsed.port!=5097:
        raise RuntimeError('External network is disabled in the wiki preview')
    return _request(self,method,url,*args,**kwargs)
requests.sessions.Session.request=local_request

@module.app.before_request
def local_only():
    if request.remote_addr!='127.0.0.1': abort(403)

def local_authorize(oauth,prompt=None):
    session['oauth_state']=secrets.token_urlsafe(32)
    return '/__wiki_preview'
module._kakao_authorize_url=local_authorize
module.KakaoOauth.get_token=lambda self,code: {'access_token':code} if code==session.get('preview_code') else abort(403)
def local_user(self,token):
    if token!=session.pop('preview_code',None): abort(403)
    return {'id':9000+session.pop('preview_member'),'kakao_account':{'profile':{}}}
module.KakaoOauth.get_user_info=local_user

@module.app.route('/__wiki_preview',methods=['GET','POST'])
def preview_login():
    if request.method=='POST':
        import hmac
        if not hmac.compare_digest(request.form.get('csrf',''),session.get('preview_csrf','invalid')): abort(403)
        member=int(request.form.get('member','0'))
        if member not in (1,2,3): abort(400)
        session['preview_member']=member
        session['preview_code']=secrets.token_urlsafe(20)
        return redirect(url_for('kakao_callback',state=session['oauth_state'],code=session['preview_code']))
    if not session.get('oauth_state') or session.get('user_id'):
        return redirect(url_for('kakao_login',next='/wiki'))
    session['preview_csrf']=secrets.token_urlsafe(32)
    return render_template_string('''{% extends 'lms_base.html' %}{% block content %}
    <h1>책반우 위키 · 로컬 확인</h1><p>카카오 서버 대신 예시 회원으로 로그인 과정을 확인합니다.</p>
    <p>실제 회원 정보와 운영 DB는 사용하지 않습니다.</p>
    <form method="post"><input type="hidden" name="csrf" value="{{csrf}}">
    <p><button class="lms-button lms-button-primary" name="member" value="1">26-2 활동 회원 · 읽기와 편집</button></p>
    <p><button class="lms-button" name="member" value="2">26-2 휴식 회원 · 읽기만</button></p>
    <p><button class="lms-button" name="member" value="3">가입 대기 · 접근 불가</button></p></form>
    {% endblock %}''',csrf=session['preview_csrf'],lms_title='위키 로컬 확인')

if __name__=='__main__':
    module.app.run(host='127.0.0.1',port=5105,debug=False,use_reloader=False)
