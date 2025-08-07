import os
from flask import Flask, redirect, url_for, session, jsonify
from flask_dance.consumer import OAuth2ConsumerBlueprint
from dotenv import load_dotenv

# 1. http 통신 허용 및 .env 파일 로드
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'
dotenv_path = os.path.join(os.path.dirname(__file__), '..', '.env')
load_dotenv(dotenv_path=dotenv_path)

# 2. Flask 앱 생성 및 기본 설정
app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "supersecretkey_for_test")

# 3. Flask-Dance 카카오 블루프린트 설정
# [수정] 변수 이름을 'kakao_bp'에서 'kakao'로 변경합니다.
# testing/kakao_test.py의 카카오 블루프린트 설정 부분

kakao = OAuth2ConsumerBlueprint(
    "kakao", __name__,
    client_id=os.environ.get("KAKAO_OAUTH_CLIENT_ID"),
    client_secret=os.environ.get("KAKAO_OAUTH_CLIENT_SECRET"), # 이 줄을 추가!
    base_url="https://kapi.kakao.com",
    token_url="https://kauth.kakao.com/oauth/token",
    authorization_url="https://kauth.kakao.com/oauth/authorize",
)
# [수정] register_blueprint에 'kakao' 변수를 사용합니다.
app.register_blueprint(kakao, url_prefix="/login")


# 4. 가장 기본적인 라우트 2개만 생성
@app.route("/")
def index():
    """로그인 버튼만 있는 메인 페이지"""
    # [수정] 이제 'kakao' 변수가 정상적으로 인식됩니다.
    if not kakao.authorized:
        return f'<h1>카카오 로그인 테스트</h1><a href="{url_for("kakao.login")}">카카오로 로그인하기</a>'

    try:
        # kakao.session.get()으로 수정
        user_info_res = kakao.session.post("/v2/user/me")
        user_info = user_info_res.json()
        # 성공 시, JSON 데이터를 예쁘게 출력
        return jsonify(user_info)
    except Exception as e:
        return f"<h1>사용자 정보 조회 실패</h1><p>{e}</p><a href='/logout'>로그아웃</a>"


@app.route("/logout")
def logout():
    # 이 테스트에서는 Flask-Dance의 세션만 정리합니다.
    session.clear()
    # blueprint의 토큰도 명시적으로 삭제
    if 'kakao_oauth_token' in session:
        del session['kakao_oauth_token']
    return redirect("/")


# 5. 테스트 앱 실행
if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000, debug=True)