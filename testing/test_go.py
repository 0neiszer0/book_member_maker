import sys
import os
import pandas as pd
import random
import numpy as np
from dotenv import load_dotenv
from supabase import create_client, Client

# --- 상위 폴더(app.py가 있는 곳)를 import 경로에 추가 ---
script_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(script_dir)
sys.path.append(parent_dir)

# --- .env 파일에서 DB 접속 정보 로드 ---
dotenv_path = os.path.join(parent_dir, '.env')
load_dotenv(dotenv_path=dotenv_path)

# --- app.py에서 필요한 함수를 가져옵니다 ---
from app import run_genetic_algorithm


def main():
    """실제 DB 데이터로 테스트를 실행하는 메인 함수"""

    print("=" * 40)
    print("유전 알고리즘 독립 테스트 (실제 DB 데이터 사용)")
    print("=" * 40)

    # --- 1. Supabase 클라이언트 초기화 및 데이터 로드 ---
    try:
        print("Supabase에 연결하여 실제 데이터를 불러옵니다...")
        supabase_url = os.environ.get("SUPABASE_URL")
        supabase_key = os.environ.get("SUPABASE_KEY")
        if not supabase_url or not supabase_key:
            raise ValueError("Supabase URL 또는 Key를 .env 파일에서 찾을 수 없습니다.")

        supabase: Client = create_client(supabase_url, supabase_key)

        members_response = supabase.table("members").select("*").execute()
        members_df = pd.DataFrame(members_response.data)

        history_response = supabase.table("history").select("groups").execute()
        history_df = pd.DataFrame(history_response.data if history_response.data else [])

        if members_df.empty:
            print("\n오류: DB에서 회원 정보를 불러오지 못했거나 등록된 회원이 없습니다.")
            return

        print(f"성공: {len(members_df)}명의 회원 정보와 {len(history_df)}개의 모임 기록을 불러왔습니다.\n")

    except Exception as e:
        print(f"\n데이터베이스 연결 또는 데이터 로드 중 오류 발생: {e}")
        return

    # --- 2. 테스트 시나리오 설정 ---
    all_member_names = members_df['name'].tolist()
    num_attendees = min(len(all_member_names), 20)
    num_facilitators = 3

    if num_attendees < 3 or num_attendees < num_facilitators:
        print("오류: 테스트를 진행하기에 회원이 충분하지 않습니다.")
        return

    attendee_names = random.sample(all_member_names, num_attendees)
    presenter_names = random.sample(attendee_names, num_facilitators)
    weights = (6.0, 10.0, 3.0, 2.0, -1000.0)

    print(f"총 참석자 ({len(attendee_names)}명): {', '.join(attendee_names)}")
    print(f"발제자 ({len(presenter_names)}명): {', '.join(presenter_names)}\n")

    # --- 3. 알고리즘 실행 및 결과 처리 (수정된 부분) ---
    print("알고리즘 실행 중...")

    ga_generator = run_genetic_algorithm(
        members_df=members_df,
        history_df=history_df,
        attendee_names=attendee_names,
        presenter_names=presenter_names,
        weights=weights,
        num_results=3,
        group_count_override=None,
        test_mode=True
    )

    solutions = None
    logbook = None

    # test_mode=True에서는 yield 없이 바로 return되므로,
    # while 루프 없이 바로 StopIteration 예외를 잡아 최종 결과를 받습니다.
    try:
        next(ga_generator)
    except StopIteration as e:
        solutions, logbook = e.value
        print("알고리즘 실행 완료!\n")

    # --- 4. 최종 결과 출력 ---
    if solutions:
        print("[ 최종 추천 조 편성 결과 ]")
        for i, result in enumerate(solutions):
            print(f"\n--- 추천안 {i + 1} (총점: {result['score']}) ---")
            for j, group in enumerate(result['groups']):
                group_str = ", ".join([f"*{name}*" if name in presenter_names else name for name in group])
                print(f"  그룹 {j + 1}: {group_str}")
    else:
        print("결과를 생성하지 못했습니다.")

    if logbook:
        print("\n\n[ 세대별 최고 점수 변화 로그 (전체) ]")
        # logbook 리스트 전체를 순회하도록 수정합니다.
        for record in logbook:
            print(f"  세대 {record['gen']:>3}: 최고점수 {record['max_score']:.2f}")



if __name__ == "__main__":
    main()