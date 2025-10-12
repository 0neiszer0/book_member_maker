# rebuild_matrix.py
from dotenv import load_dotenv
from supabase import create_client, Client
from datetime import datetime
import os
import itertools

print(f"[{datetime.now()}] 'bookclub_co_matrix' 테이블 재구축을 시작합니다.")

try:
    # .env 파일에서 환경 변수 로드 및 Supabase 클라이언트 초기화
    load_dotenv()
    SUPABASE_URL = os.environ.get("SUPABASE_URL")
    SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY")
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

    # 1. 'history' 테이블에서 모든 원본 기록을 가져옵니다.
    history_res = supabase.table('history').select('date, groups').execute()
    all_history = history_res.data
    print(f"INFO: 총 {len(all_history)}개의 과거 모임 기록을 발견했습니다.")

    # 2. 'members' 테이블에서 모든 회원 이름을 가져와 유효한 이름 목록을 만듭니다.
    members_res = supabase.table('members').select('name').execute()
    valid_names = {member['name'] for member in members_res.data}
    print(f"INFO: 총 {len(valid_names)}명의 유효한 회원 이름을 확인했습니다.")

    # 3. 모든 만남 기록을 처음부터 다시 계산합니다.
    new_matrix = {}
    for record in all_history:
        meeting_date = record.get('date')
        groups = record.get('groups', [])
        for group in groups:
            # 그룹 내에 유효한 이름만 필터링합니다.
            valid_group_members = [name for name in group if name in valid_names]

            # 그룹 내 모든 쌍(pair)을 만듭니다.
            for name1, name2 in itertools.combinations(valid_group_members, 2):
                pair_key = '-'.join(sorted([name1, name2]))

                if pair_key not in new_matrix:
                    new_matrix[pair_key] = {'count': 0, 'last_met': '1970-01-01'}

                new_matrix[pair_key]['count'] += 1
                if meeting_date and meeting_date > new_matrix[pair_key]['last_met']:
                    new_matrix[pair_key]['last_met'] = meeting_date

    print(f"INFO: 총 {len(new_matrix)}개의 고유한 만남 쌍을 재계산했습니다.")

    # 4. 기존 'bookclub_co_matrix' 테이블의 모든 데이터를 삭제합니다.
    print("INFO: 기존 'bookclub_co_matrix' 테이블의 모든 데이터를 삭제합니다...")
    # 'match'를 사용하여 모든 행을 대상으로 delete를 실행합니다.
    supabase.table('bookclub_co_matrix').delete().neq('pair_key', 'dummy_value_to_delete_all').execute()

    # 5. 새로 계산된 데이터를 테이블에 삽입합니다.
    if new_matrix:
        data_to_insert = [
            {'pair_key': pair, 'count': values['count'], 'last_met': values['last_met']}
            for pair, values in new_matrix.items()
        ]
        print(f"INFO: 새로 계산된 {len(data_to_insert)}개의 데이터를 테이블에 삽입합니다...")
        supabase.table('bookclub_co_matrix').insert(data_to_insert).execute()

    print("✅ 'bookclub_co_matrix' 테이블 재구축이 성공적으로 완료되었습니다.")

except Exception as e:
    print(f"❌ 오류가 발생했습니다: {e}")
