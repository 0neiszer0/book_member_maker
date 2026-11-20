"""Staff privacy summaries and primary-admin-only purge operations."""
from uuid import UUID

from flask import jsonify, make_response, render_template, request
from postgrest.exceptions import APIError


CONFIRMATION = '파기 확인'


def init_privacy_cleanup_routes(app, get_db, login_required, primary_admin_check):
    def purge_payload():
        if not primary_admin_check():
            return None, (jsonify(status='error', message='개인정보 파기는 관리자만 할 수 있습니다.'), 403)
        data = request.get_json(silent=True)
        if not isinstance(data, dict) or data.get('confirm') != CONFIRMATION:
            return None, (jsonify(status='error', message='파기 확인 문구를 정확히 입력해주세요.'), 400)
        return data, None

    @app.get('/admin/privacy')
    @login_required(role='admin')
    def admin_privacy_cleanup():
        can_purge = primary_admin_check()
        try:
            summary = get_db().rpc('privacy_cleanup_summary', {}).execute().data
        except APIError:
            app.logger.error('Privacy cleanup summary failed')
            summary = None
        response = make_response(render_template(
            'admin_privacy_cleanup.html', summary=summary, can_purge=can_purge,
        ), 200 if summary is not None else 503)
        response.cache_control.no_store = True
        return response

    @app.post('/api/admin/privacy/purge-inactive-members')
    @login_required(role='admin')
    def admin_privacy_purge_inactive_members():
        _, error = purge_payload()
        if error:
            return error
        try:
            count = get_db().rpc('purge_inactive_member_privacy', {}).execute().data
        except APIError:
            app.logger.error('Inactive member privacy purge failed')
            return jsonify(status='error', message='비활성 회원의 개인정보를 파기하지 못했습니다.'), 500
        return jsonify(status='success', purged_count=count)

    @app.post('/api/admin/privacy/purge-recruitment-applicants')
    @login_required(role='admin')
    def admin_privacy_purge_recruitment_applicants():
        data, error = purge_payload()
        if error:
            return error
        campaign = data.get('campaign_id')
        scope = data.get('scope')
        try:
            campaign_id = str(UUID(campaign)) if isinstance(campaign, str) else None
        except ValueError:
            campaign_id = None
        if not campaign_id or scope not in ('rejected', 'all'):
            return jsonify(status='error', message='모집 차수와 파기 범위를 확인해주세요.'), 400
        try:
            result = get_db().rpc('purge_recruitment_applicant_privacy', {
                'p_campaign': campaign_id, 'p_scope': scope,
            }).execute().data or {}
        except APIError:
            app.logger.error('Recruitment applicant privacy purge failed')
            return jsonify(status='error', message='지원자 개인정보를 파기하지 못했습니다.'), 500
        state = result.get('state')
        if state == 'missing':
            return jsonify(status='error', message='모집 차수를 찾을 수 없습니다.'), 404
        if state == 'active':
            return jsonify(status='error', message='모집 링크를 닫은 뒤 전체 지원자를 파기할 수 있습니다.'), 409
        if state != 'success':
            return jsonify(status='error', message='파기 범위를 확인해주세요.'), 400
        return jsonify(status='success', purged_count=result['purged_count'])
