"""
Keep-Alive 스크립트.

두 가지 모드를 지원합니다:
1) RENDER_KEEP_ALIVE_URL 환경변수가 설정되어 있으면 해당 엔드포인트(HTTP)를 호출.
   → Render 인스턴스가 잠들지 않게 유지하면서, 엔드포인트 내부에서 Supabase도 깨움.
2) 그렇지 않으면 Supabase에 직접 SELECT를 실행 (기존 동작).
"""
from dotenv import load_dotenv
from datetime import datetime
import os
import sys

load_dotenv()
print(f"[{datetime.now()}] Keep-Alive 스크립트 실행 시작...")

render_url = os.environ.get("RENDER_KEEP_ALIVE_URL")

if render_url:
    import requests
    try:
        # Render 콜드 스타트 대비 60초까지 기다림
        resp = requests.get(render_url, timeout=60)
        if resp.status_code == 200:
            print(f"✅ Render keep-alive 성공: {resp.text[:200]}")
        else:
            print(f"⚠ Render 응답 비정상 (status={resp.status_code}): {resp.text[:200]}")
            sys.exit(1)
    except Exception as e:
        print(f"❌ Render 호출 실패: {e}")
        sys.exit(1)
else:
    try:
        from supabase import create_client, Client
        SUPABASE_URL = os.environ.get("SUPABASE_URL")
        SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY")
        if not SUPABASE_URL or not SUPABASE_KEY:
            raise ValueError("Supabase URL 또는 Key를 찾을 수 없습니다.")
        supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
        supabase.table('members').select('id').limit(1).execute()
        print("✅ Supabase 연결 상태 유지 성공.")
    except Exception as e:
        print(f"❌ 오류가 발생했습니다: {e}")
        sys.exit(1)