"""Flask 세션 인증을 사용하는 범용 게시판 모듈."""

import re
import uuid
from datetime import datetime, timezone

from flask import Blueprint, render_template, request, jsonify, session, redirect, url_for, flash
from werkzeug.utils import secure_filename


ROLE_LEVEL = {'member': 0, 'officer': 1, 'admin': 2}
IMAGE_TYPES = {'image/jpeg': 'jpg', 'image/png': 'png', 'image/webp': 'webp', 'image/gif': 'gif'}


def init_board_routes(app, supabase, login_required):
    bp = Blueprint('boards', __name__)

    def allowed(required):
        return ROLE_LEVEL.get(session.get('user_role') or '', -1) >= ROLE_LEVEL.get(required, 99)

    def load_board(slug, include_inactive=False):
        query = supabase.table('boards').select('*').eq('slug', slug)
        if not include_inactive:
            query = query.eq('is_active', True)
        rows = query.execute().data or []
        return rows[0] if rows else None

    def member_map(ids):
        member_ids = list({int(value) for value in ids if value is not None})
        if not member_ids:
            return {}
        rows = supabase.table('members').select('id, name, department, student_id') \
            .in_('id', member_ids).execute().data or []
        return {row['id']: row for row in rows}

    def signed_url(path):
        result = supabase.storage.from_('board-uploads').create_signed_url(path, 3600)
        if isinstance(result, dict):
            return result.get('signedURL') or result.get('signedUrl') or result.get('signed_url')
        return getattr(result, 'signed_url', None) or getattr(result, 'signedURL', None)

    def upload_images(post_id, files, start_order=0):
        images = [file for file in files if file and file.filename]
        if len(images) > 5:
            raise ValueError('이미지는 글 하나당 최대 5개까지 올릴 수 있습니다.')
        uploaded, rows = [], []
        try:
            for offset, file in enumerate(images):
                mime = (file.mimetype or '').lower()
                extension = IMAGE_TYPES.get(mime)
                if not extension:
                    raise ValueError('JPG, PNG, WebP, GIF 이미지만 올릴 수 있습니다.')
                content = file.read()
                if not content or len(content) > 10 * 1024 * 1024:
                    raise ValueError('이미지는 파일당 10MB 이하여야 합니다.')
                path = f"posts/{post_id}/{uuid.uuid4().hex}.{extension}"
                supabase.storage.from_('board-uploads').upload(
                    path, content, {'content-type': mime, 'upsert': 'false'}
                )
                uploaded.append(path)
                rows.append({
                    'post_id': post_id, 'storage_path': path,
                    'original_name': secure_filename(file.filename) or f'image.{extension}',
                    'mime_type': mime, 'byte_size': len(content),
                    'display_order': start_order + offset,
                })
            if rows:
                supabase.table('post_attachments').insert(rows).execute()
            return rows
        except Exception:
            if uploaded:
                try:
                    supabase.storage.from_('board-uploads').remove(uploaded)
                except Exception:
                    app.logger.warning('게시판 이미지 롤백 실패', exc_info=True)
            raise

    def targets(board_type):
        if board_type == 'seminar_review':
            return supabase.table('history').select('id, date, book_title').order('date', desc=True).execute().data or []
        if board_type == 'brick_book_review':
            return supabase.table('brick_books').select('id, title').order('created_at', desc=True).execute().data or []
        return []

    def validate_post(board, form):
        title = (form.get('title') or '').strip()
        content = (form.get('content') or '').strip()
        if not title or len(title) > 200:
            raise ValueError('제목은 1~200자로 입력해주세요.')
        if not content or len(content) > 50000:
            raise ValueError('본문은 1~50,000자로 입력해주세요.')
        payload = {'title': title, 'content': content, 'history_id': None, 'brick_book_id': None}
        if board['board_type'] == 'seminar_review':
            target_id = (form.get('history_id') or '').strip()
            if not target_id or not (supabase.table('history').select('id').eq('id', target_id).execute().data or []):
                raise ValueError('후기를 작성한 세미나를 선택해주세요.')
            payload['history_id'] = target_id
        elif board['board_type'] == 'brick_book_review':
            target_id = (form.get('brick_book_id') or '').strip()
            if not target_id or not (supabase.table('brick_books').select('id').eq('id', target_id).execute().data or []):
                raise ValueError('후기를 작성한 벽돌책을 선택해주세요.')
            payload['brick_book_id'] = target_id
        return payload

    @app.context_processor
    def board_navigation():
        if not session.get('user_role'):
            return {'nav_boards': []}
        try:
            rows = supabase.table('boards').select('name, slug, read_role').eq('is_active', True) \
                .order('display_order').order('name').execute().data or []
            return {'nav_boards': [row for row in rows if allowed(row['read_role'])]}
        except Exception:
            return {'nav_boards': []}

    @bp.route('/boards')
    @login_required()
    def index():
        rows = supabase.table('boards').select('*').eq('is_active', True) \
            .order('display_order').order('name').execute().data or []
        return render_template('boards_index.html', boards=[row for row in rows if allowed(row['read_role'])])

    @bp.route('/board/<slug>')
    @login_required()
    def board_list(slug):
        board = load_board(slug)
        if not board or not allowed(board['read_role']):
            flash('게시판을 찾을 수 없거나 읽기 권한이 없습니다.', 'danger')
            return redirect(url_for('boards.index'))
        page = max(1, request.args.get('page', 1, type=int))
        search = re.sub(r'[^0-9A-Za-z가-힣ㄱ-ㅎㅏ-ㅣ\s-]', '', (request.args.get('q') or '').strip())[:80]
        query = supabase.table('posts').select('*').eq('board_id', board['id']).is_('deleted_at', 'null')
        if search:
            query = query.or_(f"title.ilike.%{search}%,content.ilike.%{search}%")
        rows = query.order('is_pinned', desc=True).order('created_at', desc=True) \
            .range((page - 1) * 20, page * 20).execute().data or []
        has_next, posts = len(rows) > 20, rows[:20]
        members = member_map(post['author_id'] for post in posts)
        for post in posts:
            post['author'] = members.get(post['author_id'], {'name': '알 수 없음'})
        return render_template('board_list.html', board=board, posts=posts, page=page,
                               has_next=has_next, q=search, can_write=allowed(board['write_role']))

    @bp.route('/board/<slug>/write', methods=['GET', 'POST'])
    @login_required()
    def write(slug):
        board = load_board(slug)
        if not board or not allowed(board['write_role']):
            flash('글을 작성할 권한이 없습니다.', 'danger')
            return redirect(url_for('boards.index'))
        target_rows = targets(board['board_type'])
        if request.method == 'POST':
            created = None
            try:
                payload = validate_post(board, request.form)
                payload.update({'board_id': board['id'], 'author_id': session['user_id']})
                created = supabase.table('posts').insert(payload).execute().data[0]
                upload_images(created['id'], request.files.getlist('images'))
                flash('글을 등록했습니다.', 'success')
                return redirect(url_for('boards.post_detail', slug=slug, post_id=created['id']))
            except Exception as exc:
                if created:
                    supabase.table('posts').update({'deleted_at': datetime.now(timezone.utc).isoformat()}) \
                        .eq('id', created['id']).execute()
                flash(str(exc), 'danger')
        return render_template('board_form.html', board=board, post=None, targets=target_rows)

    @bp.route('/board/<slug>/<post_id>')
    @login_required()
    def post_detail(slug, post_id):
        board = load_board(slug)
        if not board or not allowed(board['read_role']):
            return redirect(url_for('boards.index'))
        rows = supabase.table('posts').select('*').eq('id', post_id).eq('board_id', board['id']) \
            .is_('deleted_at', 'null').execute().data or []
        if not rows:
            flash('글을 찾을 수 없습니다.', 'danger')
            return redirect(url_for('boards.board_list', slug=slug))
        post = rows[0]
        comments = supabase.table('post_comments').select('*').eq('post_id', post_id) \
            .is_('deleted_at', 'null').order('created_at').execute().data or []
        attachments = supabase.table('post_attachments').select('*').eq('post_id', post_id) \
            .order('display_order').execute().data or []
        members = member_map([post['author_id']] + [comment['author_id'] for comment in comments])
        post['author'] = members.get(post['author_id'], {'name': '알 수 없음'})
        for comment in comments:
            comment['author'] = members.get(comment['author_id'], {'name': '알 수 없음'})
        for attachment in attachments:
            attachment['signed_url'] = signed_url(attachment['storage_path'])
        target_label = None
        if post.get('history_id'):
            target = supabase.table('history').select('date, book_title').eq('id', post['history_id']).execute().data or []
            if target:
                target_label = f"{target[0]['date']} · {target[0].get('book_title') or '세미나'}"
        elif post.get('brick_book_id'):
            target = supabase.table('brick_books').select('title').eq('id', post['brick_book_id']).execute().data or []
            if target:
                target_label = target[0]['title']
        can_edit = int(post['author_id']) == int(session['user_id']) or session.get('user_role') == 'admin'
        return render_template('board_post.html', board=board, post=post, comments=comments,
                               attachments=attachments, target_label=target_label, can_edit=can_edit)

    @bp.route('/board/<slug>/<post_id>/edit', methods=['GET', 'POST'])
    @login_required()
    def edit(slug, post_id):
        board = load_board(slug)
        if not board:
            return redirect(url_for('boards.index'))
        rows = supabase.table('posts').select('*').eq('id', post_id).eq('board_id', board['id']) \
            .is_('deleted_at', 'null').execute().data or []
        if not rows:
            return redirect(url_for('boards.board_list', slug=slug))
        post = rows[0]
        if int(post['author_id']) != int(session['user_id']) and session.get('user_role') != 'admin':
            flash('수정할 권한이 없습니다.', 'danger')
            return redirect(url_for('boards.post_detail', slug=slug, post_id=post_id))
        if request.method == 'POST':
            try:
                payload = validate_post(board, request.form)
                payload['updated_at'] = datetime.now(timezone.utc).isoformat()
                existing = supabase.table('post_attachments').select('id').eq('post_id', post_id).execute().data or []
                new_files = [file for file in request.files.getlist('images') if file and file.filename]
                if len(existing) + len(new_files) > 5:
                    raise ValueError('기존 이미지를 포함해 최대 5개까지 올릴 수 있습니다.')
                supabase.table('posts').update(payload).eq('id', post_id).execute()
                upload_images(post_id, new_files, len(existing))
                flash('글을 수정했습니다.', 'success')
                return redirect(url_for('boards.post_detail', slug=slug, post_id=post_id))
            except Exception as exc:
                flash(str(exc), 'danger')
        return render_template('board_form.html', board=board, post=post, targets=targets(board['board_type']))

    @bp.route('/api/board/posts/<post_id>/delete', methods=['POST'])
    @login_required()
    def delete_post(post_id):
        rows = supabase.table('posts').select('author_id').eq('id', post_id).is_('deleted_at', 'null').execute().data or []
        if not rows:
            return jsonify({'status': 'error', 'message': '글을 찾을 수 없습니다.'}), 404
        if int(rows[0]['author_id']) != int(session['user_id']) and session.get('user_role') != 'admin':
            return jsonify({'status': 'error', 'message': '권한이 없습니다.'}), 403
        supabase.table('posts').update({'deleted_at': datetime.now(timezone.utc).isoformat()}).eq('id', post_id).execute()
        return jsonify({'status': 'success'})

    @bp.route('/api/board/posts/<post_id>/comments', methods=['POST'])
    @login_required()
    def create_comment(post_id):
        content = ((request.json or {}).get('content') or '').strip()
        if not content or len(content) > 5000:
            return jsonify({'status': 'error', 'message': '댓글은 1~5,000자로 입력해주세요.'}), 400
        posts = supabase.table('posts').select('board_id').eq('id', post_id).is_('deleted_at', 'null').execute().data or []
        if not posts:
            return jsonify({'status': 'error', 'message': '글을 찾을 수 없습니다.'}), 404
        boards = supabase.table('boards').select('*').eq('id', posts[0]['board_id']).execute().data or []
        if not boards or not boards[0]['allow_comments'] or not allowed(boards[0]['read_role']):
            return jsonify({'status': 'error', 'message': '댓글을 작성할 수 없습니다.'}), 403
        row = supabase.table('post_comments').insert({
            'post_id': post_id, 'author_id': session['user_id'], 'content': content
        }).execute().data[0]
        return jsonify({'status': 'success', 'comment': row})

    @bp.route('/api/board/comments/<comment_id>/delete', methods=['POST'])
    @login_required()
    def delete_comment(comment_id):
        rows = supabase.table('post_comments').select('author_id').eq('id', comment_id) \
            .is_('deleted_at', 'null').execute().data or []
        if not rows:
            return jsonify({'status': 'error', 'message': '댓글을 찾을 수 없습니다.'}), 404
        if int(rows[0]['author_id']) != int(session['user_id']) and session.get('user_role') != 'admin':
            return jsonify({'status': 'error', 'message': '권한이 없습니다.'}), 403
        supabase.table('post_comments').update({'deleted_at': datetime.now(timezone.utc).isoformat()}) \
            .eq('id', comment_id).execute()
        return jsonify({'status': 'success'})

    def strict_admin():
        return session.get('user_role') == 'admin'

    def board_definition(data):
        name, slug = (data.get('name') or '').strip(), (data.get('slug') or '').strip().lower()
        board_type = data.get('board_type') or 'general'
        read_role, write_role = data.get('read_role') or 'member', data.get('write_role') or 'member'
        if not name or not re.fullmatch(r'[a-z0-9][a-z0-9-]{1,48}', slug):
            raise ValueError('이름과 영문 소문자·숫자·하이픈으로 된 주소를 입력해주세요.')
        if board_type not in ('general', 'seminar_review', 'brick_book_review'):
            raise ValueError('지원하지 않는 게시판 유형입니다.')
        if read_role not in ROLE_LEVEL or write_role not in ROLE_LEVEL:
            raise ValueError('지원하지 않는 권한입니다.')
        return {
            'name': name, 'slug': slug, 'board_type': board_type,
            'read_role': read_role, 'write_role': write_role,
            'allow_comments': data.get('allow_comments', True) is True,
            'is_active': data.get('is_active', True) is True,
            'display_order': int(data.get('display_order') or 0),
            'updated_at': datetime.now(timezone.utc).isoformat(),
        }

    @bp.route('/admin/boards')
    @login_required(role='admin')
    def admin_index():
        if not strict_admin():
            flash('회장만 게시판을 관리할 수 있습니다.', 'danger')
            return redirect(url_for('boards.index'))
        rows = supabase.table('boards').select('*').order('display_order').order('name').execute().data or []
        deleted = supabase.table('posts').select('id, title, board_id, deleted_at').order('deleted_at', desc=True) \
            .limit(100).execute().data or []
        deleted = [post for post in deleted if post.get('deleted_at')]
        board_names = {row['id']: row['name'] for row in rows}
        for post in deleted:
            post['board_name'] = board_names.get(post['board_id'], '게시판')
        return render_template('admin_boards.html', boards=rows, deleted_posts=deleted)

    @bp.route('/api/admin/boards/create', methods=['POST'])
    @login_required(role='admin')
    def admin_create():
        if not strict_admin():
            return jsonify({'status': 'error', 'message': '권한이 없습니다.'}), 403
        try:
            created = supabase.table('boards').insert(board_definition(request.json or {})).execute().data[0]
            return jsonify({'status': 'success', 'board': created})
        except Exception as exc:
            return jsonify({'status': 'error', 'message': str(exc)}), 400

    @bp.route('/api/admin/boards/<board_id>/update', methods=['POST'])
    @login_required(role='admin')
    def admin_update(board_id):
        if not strict_admin():
            return jsonify({'status': 'error', 'message': '권한이 없습니다.'}), 403
        try:
            supabase.table('boards').update(board_definition(request.json or {})).eq('id', board_id).execute()
            return jsonify({'status': 'success'})
        except Exception as exc:
            return jsonify({'status': 'error', 'message': str(exc)}), 400

    @bp.route('/api/admin/boards/reorder', methods=['POST'])
    @login_required(role='admin')
    def admin_reorder():
        if not strict_admin():
            return jsonify({'status': 'error', 'message': '권한이 없습니다.'}), 403
        for idx, board_id in enumerate((request.json or {}).get('board_ids') or []):
            supabase.table('boards').update({'display_order': (idx + 1) * 10}).eq('id', board_id).execute()
        return jsonify({'status': 'success'})

    @bp.route('/api/admin/board/posts/<post_id>/restore', methods=['POST'])
    @login_required(role='admin')
    def admin_restore_post(post_id):
        if not strict_admin():
            return jsonify({'status': 'error', 'message': '권한이 없습니다.'}), 403
        supabase.table('posts').update({'deleted_at': None}).eq('id', post_id).execute()
        return jsonify({'status': 'success'})

    app.register_blueprint(bp)
