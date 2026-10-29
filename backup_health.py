"""Read only the sanitized local backup status, for existing admin notifications."""
from datetime import datetime, timedelta
import json
import os
from pathlib import Path


def backup_notice(now, path=None):
    path = path or os.environ.get('BACKUP_STATUS_FILE')
    if not path:
        return None
    try:
        record = json.loads(Path(path).read_text(encoding='utf-8'))
        if record.get('version') != 1:
            raise ValueError('Unknown status format')
        last = datetime.fromisoformat(record['last_success']) if record.get('last_success') else None
        if record.get('ok') is True and last and last.tzinfo and timedelta(0) <= now-last < timedelta(hours=36):
            return None
        stamp = record.get('failure_since') or record.get('last_success')
        event = datetime.fromisoformat(stamp).strftime('%Y%m%dT%H%M%S') if stamp else 'missing'
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        event = 'unavailable'
    return {'event_key':'server-backup:'+event, 'title':'서버 백업 확인 필요',
            'body':'외부 백업이 실패했거나 36시간 이상 완료되지 않았습니다. 서버 관리자에게 확인을 요청해 주세요. 정상 백업이 완료되면 이 알림은 자동으로 해결됩니다.',
            'url':'/notifications'}
