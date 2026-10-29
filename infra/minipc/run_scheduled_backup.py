"""Systemd entry point, installed independently of the running web release."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from infra.minipc.backup import check_config, run_backup, command
from infra.minipc.backup_maintenance import prune_verified, record_health

STATUS = '/var/lib/bookmembers-health/backup.json'

if __name__ == '__main__':
    try:
        config, app = check_config('/etc/book_member_maker/backup.env')
        run_backup(config, app)
        prune_verified(config, command)
        record_health(STATUS, True)
        print('OK: scheduled backup verified; retention completed')
    except Exception:
        try:
            record_health(STATUS, False)
        except Exception:
            pass
        raise SystemExit('FAIL: automatic backup needs administrator attention')
