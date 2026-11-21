"""Dues settings, accepted applicant checklist, and public result display."""
from datetime import datetime, timezone

from flask import jsonify, request, session
from postgrest.exceptions import APIError

from recruitment_results import normalize_applicant_name, normalize_student_id


DUES_SETTINGS_LIMITS = {
    'dues_account_info': 300,
    'dues_amount': 80,
    'dues_contact_phone': 40,
    'dues_guide_note': 1000,
}


def init_recruitment_dues_routes(app, get_db, login_required):
    @app.template_global()
    def accepted_applicant_dues(campaign, result):
        # The existing portal supplies only the public decision. Fetch payment
        # status after its rate-limited exact match, with the same match criteria.
        if (request.endpoint != 'applicant_result_portal' or request.method != 'POST'
                or not result or result.get('status') != 'accepted'):
            return None
        try:
            rows = get_db().table('recruitment_applicants').select('dues_paid_at') \
                .eq('campaign_id', campaign['id']).eq('result_status', 'accepted') \
                .eq('name_key', normalize_applicant_name(request.form.get('name'))) \
                .eq('student_id', normalize_student_id(request.form.get('student_id'))) \
                .limit(1).execute().data or []
        except APIError:
            app.logger.warning('Recruitment dues status unavailable')
            return None
        return rows[0] if rows else None

    @app.get('/api/admin/recruitment-results/<uuid:campaign_id>/dues')
    @login_required(role='admin')
    def admin_recruitment_dues_roster(campaign_id):
        applicants = []
        page_size = 500
        while True:
            offset = len(applicants)
            page = get_db().table('recruitment_applicants').select('id,name,student_id,dues_paid_at') \
                .eq('campaign_id', str(campaign_id)).eq('result_status', 'accepted') \
                .order('name').order('id').range(offset, offset + page_size - 1).execute().data or []
            applicants.extend(page)
            if len(page) < page_size:
                break
        response = jsonify(status='success', applicants=applicants)
        response.cache_control.no_store = True
        return response

    @app.post('/api/admin/recruitment-results/<uuid:campaign_id>/dues-settings')
    @login_required(role='admin')
    def admin_recruitment_dues_settings(campaign_id):
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify(status='error', message='회비 입금 안내를 확인해주세요.'), 400
        fields = {}
        for field, limit in DUES_SETTINGS_LIMITS.items():
            if field not in data:
                continue
            value = data[field]
            if not isinstance(value, str) or len(value.strip()) > limit or '\x00' in value:
                return jsonify(status='error', message='회비 안내 내용의 형식과 길이를 확인해주세요.'), 400
            fields[field] = value.strip() or None
        if not fields:
            return jsonify(status='error', message='저장할 회비 입금 안내가 없습니다.'), 400
        rows = get_db().table('recruitment_campaigns').update(fields) \
            .eq('id', str(campaign_id)).execute().data or []
        if not rows:
            return jsonify(status='error', message='모집 차수를 찾을 수 없습니다.'), 404
        return jsonify(status='success')

    @app.post('/api/admin/recruitment-results/<uuid:campaign_id>/applicants/<uuid:applicant_id>/dues')
    @login_required(role='admin')
    def admin_recruitment_toggle_dues(campaign_id, applicant_id):
        applicants = get_db().table('recruitment_applicants')
        campaign_id, applicant_id = str(campaign_id), str(applicant_id)
        rows = applicants.select('result_status,dues_paid_at').eq('campaign_id', campaign_id) \
            .eq('id', applicant_id).limit(1).execute().data or []
        if not rows:
            return jsonify(status='error', message='지원자를 찾을 수 없습니다.'), 404
        if rows[0]['result_status'] != 'accepted':
            return jsonify(status='error', message='합격자의 입금만 확인할 수 있습니다.'), 409
        previous = rows[0].get('dues_paid_at')
        paid_at = None if previous else datetime.now(timezone.utc).isoformat()
        query = applicants.update({
            'dues_paid_at': paid_at,
            'dues_checked_by': session['user_id'] if paid_at else None,
        }).eq('campaign_id', campaign_id).eq('id', applicant_id).eq('result_status', 'accepted')
        query = query.eq('dues_paid_at', previous) if previous else query.is_('dues_paid_at', 'null')
        updated = query.execute().data or []
        if not updated:
            return jsonify(status='error', message='입금 상태가 바뀌었습니다. 목록을 다시 확인해주세요.'), 409
        return jsonify(status='success', dues_paid=bool(paid_at), dues_paid_at=paid_at)
