import json
import itertools
import random
import math
from flask import Flask, render_template, request, jsonify

app = Flask(__name__)

# --- 데이터 파일 경로 ---
MEMBERS_FILE = 'data/members.json'
HISTORY_FILE = 'data/history.json'
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
    m = sum(1 for name in group if members[name]['gender'] == 'M')
    f = sum(1 for name in group if members[name]['gender'] == 'F')
    return -abs(m - f)

def preference_score(group, members):
    score = 0
    for a, b in itertools.permutations(group, 2):
        if b in members[a]['preferred']:
            score += 2
        if b in members[a]['avoided']:
            score -= 3
    return score

def history_score(group, co_matrix):
    score = 0
    for a, b in itertools.combinations(group, 2):
        key = '-'.join(sorted([a, b]))
        entry = co_matrix.get(key)
        if entry:
            score -= entry['count']
    return score

# --- 그룹 생성 알고리즘 ---
def generate_groups(participants, facilitators, members, co_matrix,
                    group_count_override=None,
                    group_size_range=(3,5),
                    top_n=5):

    participants = participants.copy()
    total = len(participants)
    min_size, max_size = group_size_range

    # 1) 그룹 수 계산
    min_groups = math.ceil(total / max_size)
    max_groups = total // min_size
    if group_count_override and min_groups <= group_count_override <= max_groups:
        group_count = group_count_override
    else:
        group_count = max(min_groups, len(facilitators))
        group_count = min(group_count, max_groups)

    if group_count <= 0:
        group_count = min_groups

    # 2) 그룹별 목표 크기 계산
    base_size, extra = divmod(total, group_count)
    sizes = [base_size + 1] * extra + [base_size] * (group_count - extra)

    suggestions = []

    for _ in range(top_n * 2):
        random.shuffle(participants)
        groups = [[] for _ in range(group_count)]

        # 발제자 먼저 배정
        for idx, fac in enumerate(facilitators):
            if idx < group_count:
                groups[idx].append(fac)

        # 나머지 인원 그리디 배정
        remaining = [p for p in participants if p not in facilitators]

        for person in remaining:
            best_inc, best_i = None, None
            for i, group in enumerate(groups):
                if len(group) < sizes[i]:
                    curr_score = (
                        gender_balance_score(group, members)
                        + preference_score(group, members)
                        + history_score(group, co_matrix)
                    )
                    new_group = group + [person]
                    new_score = (
                        gender_balance_score(new_group, members)
                        + preference_score(new_group, members)
                        + history_score(new_group, co_matrix)
                    )
                    inc = new_score - curr_score
                    if best_inc is None or inc > best_inc:
                        best_inc, best_i = inc, i

            # 모든 그룹이 가득 찬 경우 대비 (예외 방어)
            if best_i is None:
                for i, group in enumerate(groups):
                    if len(group) < sizes[i]:
                        best_i = i
                        break
                if best_i is None:
                    best_i = 0  # 그냥 0번 그룹에라도 넣자

            groups[best_i].append(person)

        total_score = sum(
            gender_balance_score(g, members)
            + preference_score(g, members)
            + history_score(g, co_matrix)
            for g in groups
        )
        suggestions.append((total_score, groups))

    suggestions.sort(key=lambda x: x[0], reverse=True)
    return [groups for _, groups in suggestions[:top_n]]


# --- Flask 라우트 ---
@app.route('/', methods=['GET', 'POST'])
def index():
    members_list = load_json(MEMBERS_FILE)
    if request.method == 'POST':
        present      = request.form.getlist('present')
        facilitators = request.form.getlist('facilitators')

        # --- group_count_override 처리 ---
        raw = (request.form.get('group_count') or '').strip()
        if raw.isdigit() and int(raw) > 0:
            group_count_override = int(raw)
        else:
            group_count_override = None

        # 그룹 이름, 선호/회피 등 기존 로직 그대로
        raw_names    = request.form.get('group_names') or ''
        group_names  = [n.strip() for n in raw_names.split(',') if n.strip()]

        members_dict = {m['name']: m for m in members_list}

        co_matrix    = load_json(CO_MATRIX_FILE)
        suggestions  = generate_groups(
            present,
            facilitators,
            members_dict,
            co_matrix,
            group_count_override=group_count_override
        )
        return render_template(
            'results.html',
            suggestions=suggestions,
            present=present,
            facilitators=facilitators,
            group_names=group_names
        )
    return render_template('index.html', members=members_list)

@app.route('/save', methods=['POST'])
def save():
    data = request.json
    history = load_json(HISTORY_FILE)
    co_matrix = load_json(CO_MATRIX_FILE)
    history.append(data)
    save_json(HISTORY_FILE, history)
    for g in data['groups']:
        for a, b in itertools.combinations(g, 2):
            key = '-'.join(sorted([a, b]))
            entry = co_matrix.get(key, {'count': 0, 'last_met': None})
            entry['count'] += 1
            entry['last_met'] = data['date']
            co_matrix[key] = entry
    save_json(CO_MATRIX_FILE, co_matrix)
    return jsonify({'status': 'ok'})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
