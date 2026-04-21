#!/usr/bin/env bash
# install-daemon.sh — install rcad as a systemd service on a Linux host.
#
# Usage:
#   sudo ./install-daemon.sh \
#     --endpoint ws://cp.example:8000/ws/daemon \
#     --host-id api-server \
#     --token SHARED_TOKEN \
#     [--binary ./dist/rcad-linux-amd64] \
#     [--insecure]
set -euo pipefail

ENDPOINT=""
HOSTID=""
TOKEN=""
BINARY=""
INSECURE=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --endpoint) ENDPOINT="$2"; shift 2;;
    --host-id) HOSTID="$2"; shift 2;;
    --token) TOKEN="$2"; shift 2;;
    --binary) BINARY="$2"; shift 2;;
    --insecure) INSECURE="true"; shift;;
    -h|--help)
      grep '^#' "$0" | sed -n '1,20p' | sed 's/^# \?//'; exit 0;;
    *) echo "unknown argument: $1" >&2; exit 2;;
  esac
done

if [[ -z "$ENDPOINT" || -z "$HOSTID" ]]; then
  echo "Missing required --endpoint or --host-id" >&2
  exit 2
fi

if [[ $EUID -ne 0 ]]; then
  echo "This installer must run as root (prefix with sudo)." >&2
  exit 1
fi

BIN_DST="/usr/local/bin/rcad"
CFG_DIR="/etc/rcad"
CFG_FILE="$CFG_DIR/config.yaml"
UNIT_FILE="/etc/systemd/system/rca-daemon.service"
WORK_DIR="/var/lib/rcad"

if [[ -n "$BINARY" ]]; then
  install -o root -g root -m 0755 "$BINARY" "$BIN_DST"
elif [[ ! -x "$BIN_DST" ]]; then
  echo "No --binary given and $BIN_DST missing; provide --binary" >&2
  exit 2
fi

mkdir -p "$CFG_DIR" "$WORK_DIR"
chmod 0750 "$CFG_DIR"

cat > "$CFG_FILE" <<EOF
host_id: ${HOSTID}
endpoint: ${ENDPOINT}
token: ${TOKEN}
working_dir: ${WORK_DIR}
state_path: ${WORK_DIR}/state.db
docker_enabled: true
systemd_enabled: true
insecure: ${INSECURE:-false}
metrics_interval_sec: 30
EOF
chmod 0640 "$CFG_FILE"

cat > "$UNIT_FILE" <<'EOF'
[Unit]
Description=RCA daemon (rcad)
After=network-online.target docker.service
Wants=network-online.target

[Service]
Type=simple
ExecStart=/usr/local/bin/rcad --config /etc/rcad/config.yaml
Restart=always
RestartSec=5
User=root
Group=root
LimitNOFILE=65536

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now rca-daemon.service
sleep 1
systemctl --no-pager status rca-daemon.service | head -20 || true
echo "rcad installed and started."
