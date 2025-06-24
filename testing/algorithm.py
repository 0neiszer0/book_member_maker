import random
import pandas as pd
import numpy as np
from deap import base, creator, tools, algorithms
from pathlib import Path
import json

# --- 1. 데이터 로드 및 전처리 ---
try:
    SCRIPT_DIR = Path(__file__).parent
    PROJECT_ROOT = SCRIPT_DIR.parent
    DATA_DIR = PROJECT_ROOT / "data"
    MEMBERS_FILE_PATH = DATA_DIR / "members_rows.csv"
    HISTORY_FILE_PATH = DATA_DIR / "history_rows.csv"
    members_df = pd.read_csv(MEMBERS_FILE_PATH)
    history_df = pd.read_csv(HISTORY_FILE_PATH)
except NameError:
    print("스크립트 환경이 아니므로, 기본 경로에서 파일을 찾습니다.")
    members_df = pd.read_csv('members_rows.csv')
    history_df = pd.read_csv('history_rows.csv')
except FileNotFoundError:
    print(f"오류: 데이터 파일이 있는지 확인해주세요.")
    exit()

members_info = members_df.set_index('id').to_dict('index')
name_to_id_map = pd.Series(members_df.id.values, index=members_df.name).to_dict()

meeting_history = {}
for index, row in history_df.iterrows():
    try:
        groups_list = json.loads(row['groups'])
    except (json.JSONDecodeError, TypeError):
        continue
    for group in groups_list:
        member_ids_in_group = [name_to_id_map.get(name) for name in group if name in name_to_id_map]
        for i in range(len(member_ids_in_group)):
            for j in range(i + 1, len(member_ids_in_group)):
                if member_ids_in_group[i] is None or member_ids_in_group[j] is None: continue
                pair = tuple(sorted((member_ids_in_group[i], member_ids_in_group[j])))
                meeting_history[pair] = meeting_history.get(pair, 0) + 1

# --- 사용자 설정 변수 ---
TODAY_ATTENDEE_IDS = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22]
TODAY_PRESENTER_IDS = [1, 15, 22]
TODAY_GUESTS = {'객원멤버_김지민': 3}
# --- 설정 끝 ---

# --- 2. 설정 기반 시나리오 생성 ---
valid_member_ids = set(members_info.keys())
# (검증 코드 생략)
today_final_attendees_ids = list(TODAY_ATTENDEE_IDS)
guest_to_host_map = {}
guest_id_counter = -1
for guest_name, host_id in TODAY_GUESTS.items():
    guest_id = guest_id_counter
    today_final_attendees_ids.append(guest_id)
    members_info[guest_id] = {'name': guest_name, 'gender': random.choice(['M', 'F']), 'major': 'Guest',
                              'grade': 'Guest'}
    guest_to_host_map[guest_id] = host_id
    guest_id_counter -= 1

print("--- 오늘의 모임 정보 ---")
print(f"총 참석 인원: {len(today_final_attendees_ids)}명")
# (정보 출력 코드 생략)

# --- 3. 유전 알고리즘 설정 (DEAP) ---
num_attendees = len(today_final_attendees_ids)
num_groups = round(num_attendees / 4.5)
print(f"예상 그룹 수: {num_groups}개")
weights_gender_first = (10.0, 6.0, 3.0, 2.0, -1000.0)
weights_new_face_first = (6.0, 10.0, 3.0, 2.0, -1000.0)
attendee_id_map = {idx: member_id for idx, member_id in enumerate(today_final_attendees_ids)}
idx_to_gender_map = {idx: members_info.get(mid, {}).get('gender') for idx, mid in attendee_id_map.items()}

# --- 4. 적합도 평가 함수 ---
# (이전과 동일하여 생략)
MIN_GROUP_SIZE = 3;
MAX_GROUP_SIZE = 5;
RECENT_MEETING_THRESHOLD = 2


def evaluate(individual):
    groups = {i: [] for i in range(num_groups)};
    [groups[g].append(attendee_id_map[i]) for i, g in enumerate(individual)]
    size_penalty = sum(1 for g in groups.values() if 0 < len(g) < MIN_GROUP_SIZE or len(g) > MAX_GROUP_SIZE)
    if size_penalty > 0: return 0, 0, 0, 0, size_penalty
    gender_score, new_face_score, preference_score, total_pairs = 0, 0, 0, 0
    for group_members in groups.values():
        if not group_members: continue
        males = sum(1 for mid in group_members if members_info.get(mid, {}).get('gender') == 'M')
        females = len(group_members) - males
        if males > 0 and females > 0: gender_score += min(males, females) / max(males, females)
        for i, member_id in enumerate(group_members):
            member_prefs = members_info.get(member_id)
            if member_prefs:
                preferred_id = member_prefs.get('preferred_member_id');
                avoided_id = member_prefs.get('avoided_member_id')
                for j in range(i + 1, len(group_members)):
                    other_member_id = group_members[j];
                    total_pairs += 1
                    pair = tuple(sorted((member_id, other_member_id)));
                    meet_count = meeting_history.get(pair, 0)
                    new_face_score += 1 / (meet_count + 1)
                    if other_member_id == preferred_id and meet_count < RECENT_MEETING_THRESHOLD: preference_score += 1
                    other_prefs = members_info.get(other_member_id)
                    if other_prefs and other_prefs.get(
                        'preferred_member_id') == member_id and meet_count < RECENT_MEETING_THRESHOLD: preference_score += 1
                    if other_member_id == avoided_id: preference_score -= 1.5
                    if other_prefs and other_prefs.get('avoided_member_id') == member_id: preference_score -= 1.5
    norm_new_face = new_face_score / total_pairs if total_pairs > 0 else 0
    max_pref_score = len(today_final_attendees_ids) * 2;
    norm_pref = (preference_score + max_pref_score) / (max_pref_score * 2) if max_pref_score > 0 else 0
    presenters_per_group = [sum(1 for mid in g if mid in TODAY_PRESENTER_IDS) for g in groups.values()]
    presenter_score = 1 / (np.var(presenters_per_group) + 0.1) if len(presenters_per_group) > 0 else 0
    return gender_score, norm_new_face, presenter_score, norm_pref, size_penalty


# --- 5. 돌연변이 방식 및 유사도 측정 함수 정의 ---

def move_mutation(individual):  # (이전과 동일)
    individual, = tools.mutUniformInt(individual, low=0, up=num_groups - 1, indpb=0.05)
    for i, member_id in attendee_id_map.items():
        if member_id in guest_to_host_map:
            host_id = guest_to_host_map[member_id]
            host_idx = list(attendee_id_map.keys())[list(attendee_id_map.values()).index(host_id)]
            individual[i] = individual[host_idx]
    return individual,


def swap_same_gender_mutation(individual):  # (이전과 동일)
    try:
        idx1 = random.randrange(len(individual))
        if attendee_id_map[idx1] in guest_to_host_map or attendee_id_map[
            idx1] in guest_to_host_map.values(): return individual,
        group1 = individual[idx1];
        gender1 = idx_to_gender_map[idx1]
        possible_swap_indices = [
            i for i, g in enumerate(individual)
            if g != group1 and idx_to_gender_map.get(i) == gender1 and
               attendee_id_map[i] not in guest_to_host_map and attendee_id_map[i] not in guest_to_host_map.values()
        ]
        if not possible_swap_indices: return individual,
        idx2 = random.choice(possible_swap_indices)
        individual[idx1], individual[idx2] = individual[idx2], individual[idx1]
    except Exception:
        return individual,
    return individual,


def combined_mutation(individual):  # (이전과 동일)
    if random.random() < 0.5:
        return move_mutation(individual)
    else:
        return swap_same_gender_mutation(individual)


# ★★★ 유사도(거리) 계산 함수 추가 ★★★
def hamming_distance(ind1, ind2):
    """두 조합(individual)이 얼마나 다른지 계산 (해밍 거리)"""
    return sum(c1 != c2 for c1, c2 in zip(ind1, ind2))


# --- 6. 알고리즘 실행 로직 ---

def run_ga_for_philosophy(weights, philosophy_name, num_results=3):
    print(f"\n>>> 실행: '{philosophy_name}' 조합을 생성합니다...")
    creator.create(f"Fitness_{philosophy_name}", base.Fitness, weights=weights)
    creator.create(f"Individual_{philosophy_name}", list, fitness=getattr(creator, f"Fitness_{philosophy_name}"))
    toolbox = base.Toolbox()
    toolbox.register("individual", tools.initRepeat, getattr(creator, f"Individual_{philosophy_name}"),
                     lambda: random.randint(0, num_groups - 1), n=num_attendees)
    toolbox.register("population", tools.initRepeat, list, toolbox.individual)
    toolbox.register("evaluate", evaluate)
    toolbox.register("mate", tools.cxTwoPoint)
    toolbox.register("mutate", combined_mutation)
    toolbox.register("select", tools.selTournament, tournsize=3)

    pop_size, num_generation, mut_prob = 800, 200, 0.4
    pop = toolbox.population(n=pop_size)
    hall_of_fame = tools.HallOfFame(20)  # 명예의 전당 크기를 늘려 더 많은 후보 확보
    algorithms.eaSimple(pop, toolbox, cxpb=0.7, mutpb=mut_prob, ngen=num_generation,
                        stats=None, halloffame=hall_of_fame, verbose=False)

    valid_solutions = [ind for ind in hall_of_fame if ind.fitness.values[4] == 0]
    if not valid_solutions: return [], weights

    def calculate_total_score(ind): return sum(v * w for v, w in zip(ind.fitness.values, weights))

    # 점수 순으로 먼저 정렬
    sorted_solutions = sorted(valid_solutions, key=calculate_total_score, reverse=True)

    return sorted_solutions, weights


# ★★★ 다양성을 고려하여 최종 후보를 선택하는 함수 추가 ★★★
def select_diverse_solutions(sorted_solutions, num_to_select, min_distance):
    if not sorted_solutions:
        return []

    diverse_selection = [sorted_solutions[0]]  # 점수 1등은 무조건 포함

    for sol in sorted_solutions[1:]:
        if len(diverse_selection) >= num_to_select:
            break

        # 현재 후보(sol)가 이미 선택된 조합들과 얼마나 다른지 최소 거리를 계산
        min_dist_to_selection = min(hamming_distance(sol, selected_sol) for selected_sol in diverse_selection)

        # 최소 거리 기준을 통과하면 최종 후보에 추가
        if min_dist_to_selection >= min_distance:
            diverse_selection.append(sol)

    return diverse_selection


def print_solutions(solutions, title, weights):
    # (이전과 동일)
    print(f"\n--- {title} ---")
    if not solutions: print("해당하는 조합이 없습니다."); return
    for i, solution in enumerate(solutions):
        total_score = sum(v * w for v, w in zip(solution.fitness.values, weights))
        print(f"\n--- 조합 {i + 1} (총점: {total_score:.2f}) ---")
        print(f"세부 점수(성비,새만남,발제자,선호도): {[f'{v:.2f}' for v in solution.fitness.values[:4]]}")
        groups = {g: [] for g in range(num_groups)};
        [groups[g].append(attendee_id_map[i]) for i, g in enumerate(solution)]
        for group_id, member_ids in sorted(groups.items()):
            if not member_ids: continue
            group_info_str = [f"'{members_info[mid]['name']}'" + ('(발제자)' if mid in TODAY_PRESENTER_IDS else '') for mid
                              in member_ids]
            print(f"  그룹 {group_id + 1}: {', '.join(group_info_str)}")


def main():
    # 각 철학별로 점수 상위권 후보군을 확보
    gender_solutions_pool, used_weights_gender = run_ga_for_philosophy(weights_gender_first, "성비 우선", 15)
    new_face_solutions_pool, used_weights_new_face = run_ga_for_philosophy(weights_new_face_first, "새로운 만남 우선", 15)

    # ★★★ 다양성 필터링 적용 ★★★
    # 최소 거리: 전체 멤버의 약 20% (튜닝 가능)
    min_dist_threshold = int(len(today_final_attendees_ids) * 0.2)

    final_gender_solutions = select_diverse_solutions(gender_solutions_pool, 3, min_dist_threshold)
    final_new_face_solutions = select_diverse_solutions(new_face_solutions_pool, 3, min_dist_threshold)

    # 결과 출력
    print_solutions(final_gender_solutions, "성비 우선 최적 조합 Top 3", used_weights_gender)
    print_solutions(final_new_face_solutions, "새로운 만남 우선 최적 조합 Top 3", used_weights_new_face)


if __name__ == "__main__":
    main()