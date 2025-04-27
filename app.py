import json
import itertools
import random
import math
from flask import Flask, render_template, request, jsonify
import os
from supabase import create_client, Client

# Supabase 연결 설정
SUPABASE_URL = os.environ.get('SUPABASE_URL')
SUPABASE_KEY = os.environ.get('SUPABASE_KEY')
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)


app = Flask(__name__)

# --- 데이터 파일 경로 ---
MEMBERS_FILE   = 'data/members.json'
HISTORY_FILE   = 'data/history.json'
CO_MATRIX_FILE = 'data/co_meeting_matrix.json'

# --- 유틸: JSON 로드/저장 ---
def load_json(path):
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)

def save_json(path, data):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# --- 점수 함수들 ---
def gender_balance_score(group, members):
    m = sum(1 for name in group if members[name]['gender']=='M')
    f = sum(1 for name in group if members[name]['gender']=='F')
    return -abs(m-f)

def preference_score(group, members):
    score = 0
    for a, b in itertools.permutations(group, 2):
        if b in members[a].get('preferred', []): score += 2
        if b in members[a].get('avoided',   []): score -= 3
    return score

def history_score(group, co_matrix):
    score = 0
    for a, b in itertools.combinations(group, 2):
        key = '-'.join(sorted([a,b]))
        entry = co_matrix.get(key)
        if entry: score -= entry['count']
    return score

# --- 그룹 생성 알고리즘 ---
def generate_groups(participants, facilitators, members, co_matrix,
                    group_count_override=None,
                    group_size_range=(3,5),
                    top_n=5):
    app.logger.info(f"[GENERATE] called with override={group_count_override}, "
                    f"participants={len(participants)}, facilitators={len(facilitators)}")
    total = len(participants:=participants.copy())
    min_size, max_size = group_size_range

    min_groups = math.ceil(total/max_size)
    max_groups = total//min_size
    app.logger.info(f"[GENERATE] computed min_groups={min_groups}, max_groups={max_groups}")
    if group_count_override is not None:
        group_count = group_count_override
        app.logger.info(f"override 적용 완료 그룹 수: {group_count}")
    else:
        min_groups = math.ceil(total / max_size)
        max_groups = total // min_size
        group_count = min(max(min_groups, len(facilitators)), max_groups)
    if group_count<=0: group_count = min_groups

    base, extra = divmod(total, group_count)
    sizes = [base+1]*extra + [base]*(group_count-extra)

    suggestions = []
    for _ in range(top_n*2):
        random.shuffle(participants)
        groups = [[] for _ in range(group_count)]
        # 발제자 우선 배정
        for i, fac in enumerate(facilitators):
            if i<group_count: groups[i].append(fac)
        remaining = [p for p in participants if p not in facilitators]
        for person in remaining:
            best_inc = None; best_i = None
            for i, grp in enumerate(groups):
                if len(grp)<sizes[i]:
                    curr = (gender_balance_score(grp, members)
                            + preference_score(grp, members)
                            + history_score(grp, co_matrix))
                    new_grp = grp+[person]
                    new = (gender_balance_score(new_grp, members)
                           + preference_score(new_grp, members)
                           + history_score(new_grp, co_matrix))
                    inc = new-curr
                    if best_inc is None or inc>best_inc:
                        best_inc, best_i = inc, i
            if best_i is None:
                for i, grp in enumerate(groups):
                    if len(grp)<sizes[i]:
                        best_i = i; break
                if best_i is None: best_i = 0
            groups[best_i].append(person)

        total_score = sum(
            gender_balance_score(g, members)
            + preference_score(g, members)
            + history_score(g, co_matrix)
            for g in groups
        )
        suggestions.append((total_score, groups))

    suggestions.sort(key=lambda x: x[0], reverse=True)
    return [g for _, g in suggestions[:top_n]]

# --- Flask 라우트 ---
@app.route('/', methods=['GET','POST'])
def index():
    members_list = load_json(MEMBERS_FILE)
    if request.method=='POST':
        present      = request.form.getlist('present')
        facilitators = request.form.getlist('facilitators')
        raw = (request.form.get('group_count') or '').strip()
        try:
            gc = int(raw)
            group_count_override = gc if gc > 0 else None
        except ValueError:
            group_count_override = None
        app.logger.info(f"[INDEX] raw group_count='{raw}', parsed override={group_count_override}")
        raw_names   = request.form.get('group_names') or ''
        group_names = [n.strip() for n in raw_names.split(',') if n.strip()]
        members_dict= {m['name']:m for m in members_list}
        co_matrix   = load_json(CO_MATRIX_FILE)
        suggestions = generate_groups(present, facilitators, members_dict, co_matrix,
                                      group_count_override=group_count_override)
        return render_template('results.html',
                               suggestions=suggestions,
                               present=present,
                               facilitators=facilitators,
                               group_names=group_names)
    return render_template('index.html', members=members_list)

@app.route('/save', methods=['POST'])
def save():
    data = request.json
    # 2) Supabase에 기록 추가
    record = {
        "date": data["date"],
        "present": data["present"],
        "facilitators": data["facilitators"],
        "groups": data["groups"]
    }
    supabase.postgrest.from_("history").insert(record).execute()

    # 3) co_meeting_matrix.json 업데이트 (기존 로직 그대로)
    co_matrix = load_json(CO_MATRIX_FILE)
    for g in data['groups']:
        for a, b in itertools.combinations(g, 2):
            key   = '-'.join(sorted([a, b]))
            entry = co_matrix.get(key, {'count':0,'last_met':None})
            entry['count']   += 1
            entry['last_met'] = data['date']
            co_matrix[key]   = entry
    save_json(CO_MATRIX_FILE, co_matrix)

    return jsonify({'status':'ok'})

@app.route('/api/history', methods=['GET'])
def api_get_history():
    # Supabase history 테이블에서 전체 조회
    # 필요한 대로 order() 를 추가할 수 있습니다 (예: 최신순)
    response = supabase.postgrest.from_("history").select("*").order("date", desc=True).execute()
    return jsonify(response.data)

@app.route('/api/history/delete', methods=['POST'])
def api_delete_history():
    idx = request.json.get("index")
    # 1) 삭제 대상 레코드의 id(문자열 uuid) 목록 조회
    response = supabase.postgrest.from_("history").select("id").order("date", desc=True).execute()
    records = response.data
    # 2) index 유효성 검사 후 실제 삭제
    if isinstance(idx, int) and 0 <= idx < len(records):
        record_id = records[idx]["id"]
        supabase.postgrest.from_("history").delete().eq("id", record_id).execute()
        return jsonify({"status":"ok"})
    return jsonify({"status":"error","message":"Invalid index"}), 400

if __name__=='__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)

