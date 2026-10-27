#!/usr/bin/env bash
# Run inside the approved Ubuntu VM after copying a validated source archive.
set -euo pipefail
if [[ $(id -u) != 0 ]]; then echo 'Run as root inside the Ubuntu VM'; exit 1; fi
source /etc/os-release
[[ "$ID" == ubuntu && "$VERSION_ID" == 24.04 ]] || { echo 'Ubuntu 24.04 required'; exit 1; }
[[ -f /opt/book_member_maker/requirements.txt ]] || { echo 'Copy the verified commit first'; exit 1; }
apt-get update
apt-get install -y --no-install-recommends python3.12 python3.12-venv git ca-certificates
id bookapp >/dev/null 2>&1 || useradd --system --home-dir /opt/book_member_maker --shell /usr/sbin/nologin bookapp
python3.12 -m venv /opt/book_member_maker/.venv
/opt/book_member_maker/.venv/bin/pip install -r /opt/book_member_maker/requirements.txt
install -d -m 0700 -o root -g root /etc/book_member_maker
install -m 0644 /opt/book_member_maker/infra/minipc/bookmembers.service /etc/systemd/system/bookmembers.service
systemctl daemon-reload
if [[ ! -f /etc/book_member_maker/app.env ]]; then
  echo 'Create root-owned 0600 app.env locally; preserve the existing Flask secret. Service not started.'
  exit 0
fi
[[ $(stat -c '%U:%G:%a' /etc/book_member_maker/app.env) == root:root:600 ]] || { echo 'app.env permissions must be root:root 600'; exit 1; }
systemctl enable --now bookmembers.service
# No Funnel publication or tailnet changes here; each requires approval.
