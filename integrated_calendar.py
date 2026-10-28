"""Read-only calendar adapter. Room availability stays on its public API."""
from datetime import datetime, time
from urllib.parse import urlencode

from flask import jsonify, render_template, request, session
from home_overview import KST, load_seminar_context
from topic_lifecycle import topic_event_deadline


def seminar_calendar_events(context):
    term = context.get('term') or {}
    events = []
    for row in context['sessions']:
        week_id = row.get('seminar_week_id')
        week = context['weeks'].get(week_id, {})
        events.append(dict(type='seminar', start=row['meeting_date'][:10],
                           title=('본 세미나' if row.get('day_type') == 'thu' else '추가 세미나') + ' · ' + (week.get('book_title') or row.get('book_title') or '도서 미정'),
                           url='/seminars?' + urlencode(dict(term_id=term.get('id', ''), week_id=week_id or '', session_id=row['id'])) + '#session-' + str(row['id']),
                           id='seminar-' + str(row['id']), allDay=True))
    for row in context['topics'].values():
        deadline = topic_event_deadline(row)
        if not deadline:
            continue
        events.append(dict(type='deadline', start=datetime.combine(deadline, time(), KST).isoformat(),
                           title='발제문 마감 · ' + (context['weeks'].get(row.get('seminar_week_id'), {}).get('book_title') or '도서 미정'),
                           url=('/shared_topics?' + urlencode(dict(token=row['share_token']))) if row.get('share_token') and row.get('open') else '/seminars?' + urlencode(dict(term_id=term.get('id', ''), week_id=row.get('seminar_week_id', ''))) + '#topic-' + str(row.get('seminar_week_id') or ''),
                           id='deadline-' + str(row['id']), status=row.get('status_label', ''), allDay=False))
    return events


def init_calendar_routes(app, get_db, login_required):
    @app.after_request
    def protect_calendar(response):
        if request.path in ('/calendar', '/api/calendar/seminars'):
            response.headers['Cache-Control'] = 'no-store'
            response.headers['Referrer-Policy'] = 'no-referrer'
        return response

    @app.get('/calendar')
    def lms_calendar():
        return render_template('integrated_calendar.html', calendar_today=datetime.now(KST).date().isoformat(),
                               calendar_member=bool(session.get('user_id')), calendar_term=request.args.get('term_id', ''))

    @app.get('/api/calendar/seminars')
    @login_required(role='ANY')
    def calendar_seminars():
        try:
            from home_overview import decorate_topic_submission_states
            db = get_db()
            context = load_seminar_context(db, request.args.get('term_id'))
            decorate_topic_submission_states(db, session['user_id'], list(context['topics'].values()))
            return jsonify(events=seminar_calendar_events(context), term=(context.get('term') or {}).get('name', ''))
        except Exception:
            app.logger.exception('Calendar seminar lookup failed')
            return jsonify(error='세미나 일정을 불러오지 못했어요. 다시 시도해주세요.'), 503
