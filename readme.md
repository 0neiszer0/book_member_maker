네, 프로젝트의 전체적인 기능과 구조를 설명하는 `README.md` 파일을 작성해 드리겠습니다.

-----

# 책 먹는 호반우: 동아리 운영 자동화 시스템

이 프로젝트는 대학 동아리 '책 먹는 호반우'의 운영 효율을 높이기 위해 개발된 웹 기반 자동화 시스템입니다. 신입회원 모집을 위한 면접 예약부터, 유전 알고리즘을 활용한 정기 모임 조 편성에 이르기까지, 반복적이고 시간이 많이 소요되는 운영 업무를 자동화하여 동아리 구성원들이 활동의 본질에 더 집중할 수 있도록 돕습니다.


## ✨ 핵심 기능

이 시스템은 크게 두 가지 핵심 기능으로 구성되어 있습니다.

### 1\. 면접 예약 시스템

신입회원 모집 과정을 체계적으로 관리하기 위한 기능입니다. 관리자, 면접관, 지원자의 세 가지 역할에 따라 접근 권한과 기능이 분리되어 있습니다.

  * **⚙️ 관리자 (Admin)**

      * 면접 이벤트(예: '25년 여름방학 모집')를 생성하고, 기간 및 활성화 상태를 관리합니다.
      * 특정 기간, 요일, 시간을 지정하여 면접 시간 슬롯을 일괄로 생성 및 삭제할 수 있습니다.
      * 전체 면접 타임테이블을 통해 예약 현황을 실시간으로 확인하고, 지원자 정보를 수정하거나 예약을 수동으로 등록/취소할 수 있습니다.
      * 동아리 회원 목록에서 면접관을 지정하거나 제외할 수 있습니다.

  * **🧑‍💻 면접관 (Interviewer)**

      * 로그인 후 참여 가능한 면접 이벤트를 확인하고, 원하는 시간에 자신을 면접관으로 배정할 수 있습니다.
      * 타임테이블에서 자신이 배정된 시간과 해당 시간의 예약자 정보를 확인할 수 있습니다.

  * **🙋 지원자 (Applicant)**

      * 이름과 연락처만으로 간단히 로그인하여 면접 예약을 진행할 수 있습니다.
      * 활성화된 이벤트의 예약 가능한 시간 목록을 확인하고, 원하는 시간을 직접 선택하여 예약합니다.
      * 예약 완료 후, 자신의 확정된 면접 시간을 즉시 확인할 수 있습니다.
      * **(자동화)** 신규 예약이 발생하면 관리자에게 즉시 텔레그램 알림이 발송됩니다.

### 2\. 독서모임 조 편성 시스템

단순한 랜덤 배정을 넘어, 다양한 조건을 고려하여 최적의 모임 조를 추천하는 스마트 조 편성 도구입니다.

  * **🤖 유전 알고리즘 기반 추천**

      * 참석자의 성비, 과거에 같은 조에 편성되었던 이력(새로운 만남 추구), 개인별 선호/기피 멤버, 발제자(Facilitator)의 균등 분배 등 복합적인 조건을 고려하여 최적의 조 조합을 계산합니다.
      * '성비 균형'을 우선시하는 조합과 '새로운 만남'을 우선시하는 조합 두 가지 철학에 따른 결과물을 각각 제시하여 운영자가 상황에 맞게 선택할 수 있습니다.

  * **📊 데이터 기반 학습**

      * 모임이 끝난 후 확정된 조 편성 결과를 저장하면, 이 데이터가 다음 조 편성 시 '과거 만남 이력'에 반영되어 알고리즘이 점차 더 나은 추천을 하도록 학습합니다.

## 🛠️ 기술 스택

  * **Backend**: Python, Flask
  * **Database**: Supabase (PostgreSQL)
  * **Frontend**: HTML, Tailwind CSS, Vanilla JavaScript
  * **Key Libraries**: `deap` (유전 알고리즘), `pandas`, `numpy`, `requests` (Telegram API), `supabase-py`

## 🚀 시작하기

### 1\. 사전 준비

  * Python 3.9+
  * Supabase 계정 및 프로젝트 생성
  * Telegram Bot Token 및 Chat ID (알림 기능 사용 시)

### 2\. 설치 및 설정

1.  **레포지토리 클론**

    ```bash
    git clone {레포지토리_URL}
    cd {프로젝트_폴더}
    ```

2.  **가상환경 생성 및 패키지 설치**

    ```bash
    python -m venv venv
    source venv/bin/activate  # Windows: venv\Scripts\activate
    pip install -r requirements.txt # requirements.txt 파일 필요
    ```

3.  **Supabase 데이터베이스 설정**
    Supabase 프로젝트 내에 아래와 같은 테이블들이 필요합니다. `app.py` 코드를 참고하여 컬럼을 설정하세요.

      * `events`: 면접 이벤트 정보
      * `members`: 전체 동아리 회원 정보
      * `interviewers`: 면접관으로 지정된 회원 정보
      * `time_slots`: 면접 시간 슬롯
      * `applicants`: 면접 지원자 정보
      * `reservations`: 예약 정보 (지원자와 시간 슬롯 연결)
      * `history`: 과거 독서모임 조 편성 기록
      * `bookclub_co_matrix`: 회원 간 만남 횟수 기록

4.  **.env 파일 생성**
    프로젝트 루트에 `.env` 파일을 생성하고 아래 변수들을 설정합니다.

    ```env
    # Flask Secret Key
    FLASK_SECRET_KEY='매우_안전하고_추측하기_어려운_문자열'

    # Supabase Credentials
    SUPABASE_URL='https://your-project-url.supabase.co'
    SUPABASE_KEY='your-supabase-anon-key'

    # Role Passwords
    ADMIN_PASSWORD='관리자_로그인_비밀번호'
    INTERVIEWER_PASSWORD='면접관_로그인_비밀번호'
    APPLICANT_PASSWORD='지원자_로그인_비밀번호'

    # Telegram Bot (Optional)
    TELEGRAM_BOT_TOKEN='your-telegram-bot-token'
    TELEGRAM_CHAT_IDS='알림받을_채팅ID,쉼표로_여러개_설정가능'
    ```

5.  **애플리케이션 실행**

    ```bash
    flask run
    ```

    이제 브라우저에서 `http://127.0.0.1:5000`으로 접속할 수 있습니다.