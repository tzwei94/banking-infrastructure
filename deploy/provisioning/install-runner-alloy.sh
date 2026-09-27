#!/usr/bin/env bash
set -euo pipefail
[[ $EUID == 0 ]] || { echo 'Run through administrative SSM' >&2; exit 1; }
cd "$(dirname "$0")/.."
version=${1:?Usage: install-runner-alloy.sh VERSION SHA256}
checksum=${2:?}
[[ $version =~ ^[0-9]+\.[0-9]+\.[0-9]+$ && $checksum =~ ^[a-f0-9]{64}$ ]] || exit 2
[[ -s /etc/alloy/runner.env ]] || { echo 'First provision root-only /etc/alloy/runner.env with METRICS_URL, TELEMETRY_USERNAME, TELEMETRY_PASSWORD' >&2; exit 1; }
chmod 600 /etc/alloy/runner.env
scratch=$(mktemp -d)
trap 'rm -rf "$scratch"' EXIT
curl --fail --silent --show-error --location "https://github.com/grafana/alloy/releases/download/v$version/alloy-linux-amd64.zip" -o "$scratch/alloy.zip"
printf '%s  %s\n' "$checksum" "$scratch/alloy.zip" | sha256sum -c -
unzip -q "$scratch/alloy.zip" -d "$scratch"
install -m 755 "$scratch/alloy-linux-amd64" /usr/local/bin/alloy
id alloy &>/dev/null || useradd --system --home-dir /var/lib/alloy --shell /sbin/nologin alloy
install -d -o alloy -g alloy -m 750 /var/lib/alloy
install -m 644 monitoring/runner.alloy /etc/alloy/runner.alloy
cat > /etc/systemd/system/banking-alloy.service <<'UNIT'
[Unit]
Description=Banking runner host metrics
After=network-online.target
Wants=network-online.target
[Service]
User=alloy
Group=alloy
EnvironmentFile=/etc/alloy/runner.env
ExecStart=/usr/local/bin/alloy run --server.http.listen-addr=127.0.0.1:12345 --storage.path=/var/lib/alloy /etc/alloy/runner.alloy
Restart=on-failure
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/var/lib/alloy
MemoryMax=256M
[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable --now banking-alloy
