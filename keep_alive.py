from dotenv import load_dotenv
from supabase import create_client, Client
from datetime import datetime
import os

print(f"[{datetime.now()}] Keep-Alive 스크립트 실행 시작...")

try:
    # .env 파일에서 환경 변수 로드
    load_dotenv()

    # Supabase 클라이언트 초기화
    SUPABASE_URL = os.environ.get("SUPABASE_URL")
    SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY")

    if not SUPABASE_URL or not SUPABASE_KEY:
        raise ValueError("Supabase URL 또는 Key를 찾을 수 없습니다.")

    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

    # DB에 간단한 요청을 보내 활동 기록을 남김 (가장 가벼운 작업)
    response = supabase.table('members').select('id').limit(1).execute()

    # 요청이 성공했는지 확인 (오류가 없으면 성공)
    if response.data or not response.data:
        print("✅ Supabase 연결 상태 유지 성공.")

except Exception as e:
    print(f"❌ 오류가 발생했습니다: {e}")