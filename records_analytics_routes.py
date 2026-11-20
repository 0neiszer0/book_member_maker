"""기록 허브·세미나 기록 조회·통계 라우트를 별도 모듈로 관리한다.

기존 app.py 에 있던 4개 라우트(HTML 4개)를 한데 모아 `init_records_analytics_routes`로
등록한다. 다른 모듈(records_activity_routes 등)과 동일하게 `get_supabase` 콜백을 통해
테스트 패치가 항상 동작하도록 내부에서 `db()` 헬퍼로 Supabase 클라이언트를 얻는다.

학기 필터/장르/성별 정규화/출석 매트릭스 등 기존 app.py 헬퍼는 인자로 주입받아 재사용한다.
예외는 로그에만 남기고 클라이언트에는 원문 예외(str(e))를 절대 노출하지 않는다.
"""
import math
from datetime import date

from flask import flash, redirect, render_template, request, url_for


# HTML 뷰 공통 오류 플래시: 원문 예외를 노출하지 않는다.
SAFE_VIEW_ERROR = '기록을 불러오는 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요.'


def init_records_analytics_routes(app, get_supabase, login_required, get_term_range,
                                  get_terms_for_filter, load_genres, normalize_gender,
                                  meeting_details_from_history, effective_group_history_rows,
                                  build_attendance_matrix):
    def db():
        return get_supabase()

    # --- 기록 허브 ---
    @app.route('/records')
    @login_required(role="admin")
    def records_hub():
        try:
            seminar_count = db().table('history').select('id', count='exact').execute().count or 0
            bb_count = db().table('brick_books').select('id', count='exact').execute().count or 0
            sg_count = db().table('study_groups').select('id', count='exact').execute().count or 0
            member_count = db().table('members').select('id', count='exact').eq('is_active', True).execute().count or 0
        except Exception as e:
            app.logger.error("records_hub count error: %s", e, exc_info=True)
            seminar_count = bb_count = sg_count = member_count = 0
        return render_template('records_hub.html',
                               seminar_count=seminar_count, brick_book_count=bb_count,
                               study_group_count=sg_count, member_count=member_count)

    # --- 세미나 ---
    @app.route('/records/seminars')
    @login_required(role="admin")
    def records_seminars():
        term_id = request.args.get('term_id') or ''
        page = max(1, request.args.get('page', 1, type=int))
        page_size = 100
        try:
            q = db().table('history').select('*', count='exact').order('date', desc=True)
            start, end, _ = get_term_range(term_id)
            if start and end:
                q = q.gte('date', start).lte('date', end)
            history_response = q.range((page - 1) * page_size, page * page_size - 1).execute()
            history = history_response.data or []
            total_history = history_response.count if history_response.count is not None else len(history)
            total_pages = max(1, math.ceil(total_history / page_size))
            for row in history:
                groups = row.get('groups') or []
                present = []
                for g in groups:
                    if isinstance(g, list):
                        present.extend(g)
                    elif isinstance(g, str):
                        present.append(g)
                row['present_count'] = len(present)
                row['group_count'] = len(groups) if groups and isinstance(groups[0], list) else 0
                row['facilitator_count'] = len(row.get('facilitators') or [])

            # 6개월 단위 버킷 그룹화 (예: "2025년 상반기", "2025년 하반기")
            buckets = []  # [{'key': str, 'label': str, 'rows': [..]}]
            seen = {}
            for row in history:
                try:
                    d = date.fromisoformat(row['date'])
                    from lms_learning import academic_period
                    key, label = academic_period(d)
                except Exception:
                    key, label = 'unknown', '날짜 미상'
                if key not in seen:
                    seen[key] = {'key': key, 'label': label, 'rows': []}
                    buckets.append(seen[key])
                seen[key]['rows'].append(row)
            # history는 이미 date desc 정렬이므로 buckets도 자연스럽게 최신순
            genres = load_genres()
            terms = get_terms_for_filter()
        except Exception as e:
            app.logger.error("records_seminars error: %s", e, exc_info=True)
            flash(SAFE_VIEW_ERROR, 'danger')
            history, genres, terms, buckets = [], [], [], []
            total_history, total_pages = 0, 1
        return render_template('records_seminars.html', history=history, genres=genres,
                               terms=terms, selected_term_id=term_id, buckets=buckets,
                               page=page, total_pages=total_pages, total_history=total_history)

    @app.route('/records/seminars/<history_id>')
    @login_required(role="admin")
    def records_seminar_detail(history_id):
        try:
            row = db().table('history').select('*').eq('id', history_id).single().execute().data
            groups = row.get('groups') or []
            all_present = []
            for g in groups:
                if isinstance(g, list):
                    all_present.extend(g)
                elif isinstance(g, str):
                    all_present.append(g)
            member_map = {}
            if all_present:
                mres = db().table('members').select('id, name, gender').in_('name', list(set(all_present))).execute().data or []
                member_map = {m['name']: m['id'] for m in mres}
            else:
                mres = []
            member_genders = {m['name']: normalize_gender(m.get('gender')) for m in mres}
            genres = load_genres()
            all_members = db().table('members').select('id, name, gender') \
                .eq('is_active', True).order('name').execute().data or []
            for member in all_members:
                member['gender_code'] = normalize_gender(member.get('gender'))
                member_genders.setdefault(member['name'], member['gender_code'])
            meeting_history = meeting_details_from_history(
                effective_group_history_rows(), before_date=row.get('date'), exclude_history_id=history_id
            )
            return render_template('records_seminar_detail.html',
                                   row=row, groups=groups, member_map=member_map,
                                   genres=genres, total_present=len(all_present),
                                   all_members=all_members, member_genders=member_genders,
                                   meeting_history=meeting_history)
        except Exception as e:
            app.logger.error("records_seminar_detail error: %s", e, exc_info=True)
            flash(SAFE_VIEW_ERROR, 'danger')
            return redirect(url_for('records_seminars'))

    # --- 통계 ---
    @app.route('/records/analytics')
    @login_required(role="admin")
    def records_analytics():
        term_id = request.args.get('term_id') or ''
        try:
            start, end, _ = get_term_range(term_id)
            hq = db().table('history').select('id, date, genre, present, book_title')
            if start and end:
                hq = hq.gte('date', start).lte('date', end)
            history = hq.order('date').execute().data or []
            genre_counts, monthly_counts = {}, {}
            for row in history:
                g = row.get('genre') or '미분류'
                genre_counts[g] = genre_counts.get(g, 0) + 1
                d = row.get('date')
                if d:
                    ym = str(d)[:7]
                    monthly_counts[ym] = monthly_counts.get(ym, 0) + 1

            attendance_members, attendance_sessions, attendance_matrix = build_attendance_matrix(start, end)
            attendance_counts = {
                member['id']: sum(
                    1 for session_item in attendance_sessions
                    if attendance_matrix.get(member['id'], {}).get(session_item['key'])
                )
                for member in attendance_members
            }
            visible_attendance_members = [
                member for member in attendance_members
                if member.get('is_active') or attendance_counts.get(member['id'], 0) > 0
            ]
            # Ranking also uses confirmed actual attendance, never the saved group plan.
            top_attendees = sorted(
                [(member['name'], attendance_counts.get(member['id'], 0)) for member in attendance_members
                 if attendance_counts.get(member['id'], 0) > 0],
                key=lambda item: (-item[1], item[0]),
            )[:15]

            # 벽돌책/소모임 월별 세션 카운트 (학기 필터 적용)
            bb_monthly, sg_monthly = {}, {}
            try:
                bbq = db().table('brick_book_sessions').select('meeting_date')
                if start and end:
                    bbq = bbq.gte('meeting_date', start).lte('meeting_date', end)
                bb_sess = bbq.execute().data or []
                for s in bb_sess:
                    ym = str(s.get('meeting_date') or '')[:7]
                    if ym: bb_monthly[ym] = bb_monthly.get(ym, 0) + 1
            except Exception: pass
            try:
                sgq = db().table('study_group_sessions').select('meeting_date')
                if start and end:
                    sgq = sgq.gte('meeting_date', start).lte('meeting_date', end)
                sg_sess = sgq.execute().data or []
                for s in sg_sess:
                    ym = str(s.get('meeting_date') or '')[:7]
                    if ym: sg_monthly[ym] = sg_monthly.get(ym, 0) + 1
            except Exception: pass

            # 벽돌책/소모임 카운트: 학기 내 세션이 있는 것만
            if start and end:
                bb_count = len({s.get('brick_book_id') for s in (db().table('brick_book_sessions')
                    .select('brick_book_id, meeting_date').gte('meeting_date', start).lte('meeting_date', end)
                    .execute().data or [])})
                sg_count = len({s.get('study_group_id') for s in (db().table('study_group_sessions')
                    .select('study_group_id, meeting_date').gte('meeting_date', start).lte('meeting_date', end)
                    .execute().data or [])})
            else:
                bb_count = db().table('brick_books').select('id', count='exact').execute().count or 0
                sg_count = db().table('study_groups').select('id', count='exact').execute().count or 0

            terms = get_terms_for_filter()
            return render_template('records_analytics.html',
                                   total_seminars=len(history),
                                   total_brick_books=bb_count,
                                   total_study_groups=sg_count,
                                   genre_counts=genre_counts,
                                   monthly_counts=dict(sorted(monthly_counts.items())),
                                   bb_monthly=dict(sorted(bb_monthly.items())),
                                   sg_monthly=dict(sorted(sg_monthly.items())),
                                   top_attendees=top_attendees,
                                   attendance_members=visible_attendance_members,
                                   attendance_sessions=attendance_sessions,
                                   attendance_matrix=attendance_matrix,
                                   attendance_counts=attendance_counts,
                                   attendance_start_date=start or '',
                                   attendance_end_date=end or '',
                                   terms=terms, selected_term_id=term_id)
        except Exception as e:
            app.logger.error("records_analytics error: %s", e, exc_info=True)
            flash(SAFE_VIEW_ERROR, 'danger')
            return redirect(url_for('records_hub'))
