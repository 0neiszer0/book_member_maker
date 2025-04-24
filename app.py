import json
import itertools
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, jsonify

app = Flask(__name__)

# --- 데이터 로딩/저장 ---
MEMBERS_FILE = 'data/members.json'
HISTORY_FILE = 'data/history.json'
CO_MATRIX_FILE = 'data/co_meeting_matrix.json'


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
    # 과거 만남 횟수와 날짜 반영
    score = 0
    for a, b in itertools.combinations(group, 2):
        key = '-'.join(sorted([a,b]))
        entry = co_matrix.get(key)
        if entry:
            score -= entry['count']
    return score


# --- 매칭 알고리즘 ---
def generate_groups(participants, facilitators, members, co_matrix, group_size_range=(3,5), top_n=5):
    best = []  # (score, groups)
    # 단순 랜덤+조합 방식: 참가자 분할 모든 경우 생성은 불가능하므로, 여기서는 샘플링 로직
    # TODO: 실제 구현은 휴리스틱 또는 몬테카를로 방식 추천

    # 간단 샘플: 순서 섞어서 틀짜기
    import random
    for _ in range(5000):
        random.shuffle(participants)
        groups = []
        i = 0
        # 각 그룹에 발제자 1명씩 배정 보장
        remaining = participants.copy()
        # 1) 발제자 먼저 한명씩 그룹에 넣기
        for fac in facilitators:
            groups.append([fac])
            remaining.remove(fac)
        # 2) 나머지 분배
        for group in groups:
            target = random.randint(*group_size_range)
            while len(group) < target and remaining:
                group.append(remaining.pop())
        # 3) 남은 사람들은 랜덤 그룹에 추가
        for person in remaining:
            random.choice(groups).append(person)

        # 점수 계산
        total_score = 0
        for g in groups:
            total_score += gender_balance_score(g, members)
            total_score += preference_score(g, members)
            total_score += history_score(g, co_matrix)
        best.append((total_score, groups))

    # 상위 top_n 선택
    best.sort(key=lambda x: x[0], reverse=True)
    return [groups for score, groups in best[:top_n]]


# --- Flask 라우트 ---
@app.route('/', methods=['GET', 'POST'])
def index():
    members_list = load_json(MEMBERS_FILE)
    if request.method == 'POST':
        present = request.form.getlist('present')
        facilitators = request.form.getlist('facilitators')
        # load datas
        members = {m['name']: m for m in members_list}
        history = load_json(HISTORY_FILE)
        co_matrix = load_json(CO_MATRIX_FILE)
        # generate
        suggestions = generate_groups(present, facilitators, members, co_matrix)
        return render_template('results.html', suggestions=suggestions)
    return render_template('index.html', members=members_list)


@app.route('/save', methods=['POST'])
def save():
    data = request.json
    # data: { date, groups, present, facilitators }
    history = load_json(HISTORY_FILE)
    co_matrix = load_json(CO_MATRIX_FILE)
    # 1) 히스토리 저장
    history.append(data)
    save_json(HISTORY_FILE, history)
    # 2) co-meeting matrix 업데이트
    for g in data['groups']:
        for a, b in itertools.combinations(g, 2):
            key = '-'.join(sorted([a,b]))
            entry = co_matrix.get(key, {'count':0, 'last_met': None})
            entry['count'] += 1
            entry['last_met'] = data['date']
            co_matrix[key] = entry
    save_json(CO_MATRIX_FILE, co_matrix)
    return jsonify({'status':'ok'})


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)

# 참고: templates/index.html, templates/results.html 파일을 생성하여
# 체크박스 기반 UI를 구성하세요.
