#!/usr/bin/env bash
# Run only inside the approved guest. Does not log in or publish a Funnel.
set -euo pipefail
[[ $(id -u) == 0 ]] || { echo 'Run as root inside the Ubuntu VM'; exit 1; }
source /etc/os-release
[[ "$ID" == ubuntu && "$VERSION_ID" == 24.04 ]] || { echo 'Ubuntu 24.04 required'; exit 1; }
if ! command -v tailscale >/dev/null 2>&1; then
  apt-get update
  apt-get install -y --no-install-recommends ca-certificates curl
  install -d -m 0755 /usr/share/keyrings
  curl --proto '=https' --tlsv1.2 -fsSLo /usr/share/keyrings/tailscale-archive-keyring.gpg \
    https://pkgs.tailscale.com/stable/ubuntu/noble.noarmor.gpg
  curl --proto '=https' --tlsv1.2 -fsSLo /etc/apt/sources.list.d/tailscale.list \
    https://pkgs.tailscale.com/stable/ubuntu/noble.tailscale-keyring.list
  chmod 0644 /usr/share/keyrings/tailscale-archive-keyring.gpg /etc/apt/sources.list.d/tailscale.list
  apt-get update
  apt-get install -y --no-install-recommends tailscale
fi
systemctl enable --now tailscaled
tailscale version
echo 'Package installed. Tailnet enrollment and Funnel publication are separate steps.'
