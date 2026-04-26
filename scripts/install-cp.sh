#!/usr/bin/env bash
# install-cp.sh — install the Maestro control plane via Docker Compose.
#
# Usage:
#   curl -fsSL https://github.com/EnzinoBB/Maestro/releases/latest/download/install-cp.sh | sudo bash
#   curl -fsSL …/install-cp.sh | sudo bash -s -- --port 9000 --version v0.2.0
#
# Flags:
#   --version <tag>     Image version to pin (default: latest)
#   --port <N>          Host port (default: 8000)
#   --data-dir <path>   Named volume source path (default: docker-managed)
#   --no-docker-install Fail instead of auto-installing Docker
#   --upgrade           Pull new image, restart, preserve volume
#   --auto-update       Install a systemd timer that runs --upgrade weekly
#                       (Sundays 04:00 local). Use --auto-update=off on a
#                       previously-installed system to remove the timer.
#   --uninstall         Stop + remove container; keep volume
#   --purge             With --uninstall: also remove volume and install dir
set -euo pipefail

VERSION="latest"
PORT="8000"
DATA_DIR=""
NO_DOCKER_INSTALL=""
MODE="install"
PURGE=""
AUTO_UPDATE=""    # "" | "on" | "off"

INSTALL_DIR="/opt/maestro-cp"
IMAGE="ghcr.io/enzinobb/maestro-cp"
TIMER_UNIT="maestro-cp-update.timer"
SERVICE_UNIT="maestro-cp-update.service"

usage() {
  sed -n '2,18p' "$0" | sed 's/^# \{0,1\}//'
  exit "${1:-0}"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --version)           VERSION="$2"; shift 2;;
    --port)              PORT="$2"; shift 2;;
    --data-dir)          DATA_DIR="$2"; shift 2;;
    --no-docker-install) NO_DOCKER_INSTALL="1"; shift;;
    --upgrade)           MODE="upgrade"; shift;;
    --auto-update)       AUTO_UPDATE="on"; shift;;
    --auto-update=on)    AUTO_UPDATE="on"; shift;;
    --auto-update=off)   AUTO_UPDATE="off"; shift;;
    --uninstall)         MODE="uninstall"; shift;;
    --purge)             PURGE="1"; shift;;
    -h|--help)           usage 0;;
    *) echo "unknown argument: $1" >&2; usage 2;;
  esac
done

require_root() {
  if [[ $EUID -ne 0 ]]; then
    echo "This installer must run as root (prefix with sudo)." >&2
    exit 1
  fi
}

ensure_compose_plugin() {
  # Install the Docker Compose v2 plugin when it's missing. We try, in order:
  #   1) apt-get        (Debian / Ubuntu)
  #   2) dnf or yum     (RHEL / Fedora / Rocky / Alma / Amazon Linux)
  #   3) standalone CLI plugin binary into /usr/libexec/docker/cli-plugins/
  #
  # Returns 0 when 'docker compose version' works at the end.
  if docker compose version >/dev/null 2>&1; then
    return 0
  fi
  echo "'docker compose' v2 is missing — attempting to install the plugin …"
  if command -v apt-get >/dev/null 2>&1; then
    DEBIAN_FRONTEND=noninteractive apt-get update -y >/dev/null 2>&1 || true
    if DEBIAN_FRONTEND=noninteractive apt-get install -y docker-compose-plugin >/dev/null 2>&1; then
      :
    else
      echo "  apt-get failed for docker-compose-plugin (likely missing Docker apt repo)." >&2
    fi
  elif command -v dnf >/dev/null 2>&1; then
    dnf install -y docker-compose-plugin >/dev/null 2>&1 || true
  elif command -v yum >/dev/null 2>&1; then
    yum install -y docker-compose-plugin >/dev/null 2>&1 || true
  fi
  if docker compose version >/dev/null 2>&1; then
    return 0
  fi
  # Last resort: drop the standalone plugin binary into the cli-plugins dir.
  # https://docs.docker.com/compose/install/linux/#install-the-plugin-manually
  echo "  Falling back to standalone plugin download …"
  local arch
  arch="$(uname -m)"
  case "$arch" in
    x86_64|amd64) arch="x86_64";;
    aarch64|arm64) arch="aarch64";;
    *) echo "  unsupported arch for compose plugin fallback: $arch" >&2; return 1;;
  esac
  local plugin_dir="/usr/libexec/docker/cli-plugins"
  mkdir -p "$plugin_dir"
  local url="https://github.com/docker/compose/releases/latest/download/docker-compose-linux-${arch}"
  if curl -fsSL --connect-timeout 10 --max-time 120 "$url" -o "$plugin_dir/docker-compose"; then
    chmod 0755 "$plugin_dir/docker-compose"
  else
    echo "  could not download $url" >&2
    return 1
  fi
  docker compose version >/dev/null 2>&1
}

ensure_docker() {
  if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1 \
       && docker info >/dev/null 2>&1; then
    return 0
  fi
  if [[ -n "$NO_DOCKER_INSTALL" ]]; then
    echo "Docker or 'docker compose' v2 is missing / not running and --no-docker-install is set." >&2
    exit 3
  fi
  if ! command -v docker >/dev/null 2>&1; then
    echo "Installing Docker via get.docker.com …"
    curl -fsSL https://get.docker.com | sh
  fi
  if ! ensure_compose_plugin; then
    echo "Failed to install 'docker compose' v2 automatically." >&2
    echo "Tried: apt/dnf/yum 'docker-compose-plugin' package + standalone plugin download." >&2
    echo "Install it manually for your distro and re-run." >&2
    exit 3
  fi
  # Start the daemon if it's installed but not running.
  if command -v systemctl >/dev/null 2>&1; then
    systemctl enable --now docker >/dev/null 2>&1 || true
  fi
  if ! docker info >/dev/null 2>&1; then
    echo "Docker is installed but the daemon is not responsive. Start it manually and re-run." >&2
    exit 3
  fi
}

render_compose() {
  mkdir -p "$INSTALL_DIR"
  local vol_spec="cp-data:/data"
  local named_volume="1"
  if [[ -n "$DATA_DIR" ]]; then
    mkdir -p "$DATA_DIR"
    vol_spec="${DATA_DIR}:/data"
    named_volume=""
  fi
  cat > "$INSTALL_DIR/docker-compose.yml" <<EOF
services:
  control-plane:
    image: ${IMAGE}:${VERSION}
    restart: unless-stopped
    ports:
      - "${PORT}:8000"
    environment:
      MAESTRO_DB: /data/cp.db
      MAESTRO_LOG_LEVEL: INFO
    volumes:
      - ${vol_spec}
EOF
  if [[ -n "$named_volume" ]]; then
    cat >> "$INSTALL_DIR/docker-compose.yml" <<EOF
volumes:
  cp-data:
EOF
  fi
}

wait_healthy() {
  local tries=30
  while (( tries > 0 )); do
    if curl -fsS "http://localhost:${PORT}/healthz" >/dev/null 2>&1; then
      return 0
    fi
    sleep 2; tries=$((tries-1))
  done
  echo "CP did not become healthy within 60s. Last logs:" >&2
  (cd "$INSTALL_DIR" && docker compose logs --tail 50) >&2 || true
  return 4
}

do_install() {
  require_root
  if [[ -f "$INSTALL_DIR/docker-compose.yml" ]]; then
    echo "Existing installation detected at $INSTALL_DIR/docker-compose.yml." >&2
    echo "Use --upgrade to change version/port, or --uninstall first." >&2
    exit 6
  fi
  ensure_docker
  render_compose
  # Preserve a copy of this script at $INSTALL_DIR so admins can re-invoke
  # --upgrade / --uninstall without re-downloading. Skip if we were piped
  # from stdin (curl | bash) — in that case $0 won't be a real file.
  if [[ -f "$0" ]]; then
    install -m 0755 "$0" "$INSTALL_DIR/install-cp.sh"
  fi
  (cd "$INSTALL_DIR" && docker compose pull && docker compose up -d)
  wait_healthy
  cat <<EOF

Maestro Control Plane is running.
  UI:          http://<this-host>:${PORT}
  Health:      http://<this-host>:${PORT}/healthz
  Compose:     $INSTALL_DIR/docker-compose.yml

To retrieve the auto-generated daemon token:
  docker compose -f $INSTALL_DIR/docker-compose.yml exec control-plane cat /data/daemon-token
  (or from first-boot logs: docker compose -f $INSTALL_DIR/docker-compose.yml logs control-plane | grep -A1 "GENERATED MAESTRO DAEMON TOKEN")

EOF
}

do_upgrade() {
  require_root
  if [[ ! -f "$INSTALL_DIR/docker-compose.yml" ]]; then
    echo "$INSTALL_DIR/docker-compose.yml not found; run install first." >&2
    exit 5
  fi
  # Rewrite compose with possibly new --version or --port before pulling.
  render_compose
  (cd "$INSTALL_DIR" && docker compose pull && docker compose up -d)
  wait_healthy
  echo "Upgrade complete."
}

do_uninstall() {
  require_root
  if [[ -f "$INSTALL_DIR/docker-compose.yml" ]]; then
    if [[ -n "$PURGE" ]]; then
      (cd "$INSTALL_DIR" && docker compose down -v)
      rm -rf "$INSTALL_DIR"
      echo "Purged: containers, volumes, $INSTALL_DIR."
    else
      (cd "$INSTALL_DIR" && docker compose down)
      echo "Stopped. Volume and $INSTALL_DIR preserved. Use --uninstall --purge to wipe."
    fi
  else
    echo "Nothing to uninstall ($INSTALL_DIR missing)."
  fi
}

install_auto_update_timer() {
  if ! command -v systemctl >/dev/null 2>&1; then
    echo "  systemd not available; --auto-update needs systemd." >&2
    return 1
  fi
  cat > "/etc/systemd/system/${SERVICE_UNIT}" <<EOF
[Unit]
Description=Maestro Control Plane self-upgrade (latest image)
After=network-online.target docker.service
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=${INSTALL_DIR}/install-cp.sh --upgrade --port ${PORT}
EOF
  cat > "/etc/systemd/system/${TIMER_UNIT}" <<EOF
[Unit]
Description=Maestro Control Plane weekly update

[Timer]
OnCalendar=Sun *-*-* 04:00:00
Persistent=true
RandomizedDelaySec=30m

[Install]
WantedBy=timers.target
EOF
  systemctl daemon-reload
  systemctl enable --now "${TIMER_UNIT}"
  echo "Auto-update timer installed: $(systemctl list-timers --no-pager "${TIMER_UNIT}" | sed -n '2p')"
}

remove_auto_update_timer() {
  if ! command -v systemctl >/dev/null 2>&1; then return 0; fi
  systemctl disable --now "${TIMER_UNIT}" 2>/dev/null || true
  rm -f "/etc/systemd/system/${TIMER_UNIT}" "/etc/systemd/system/${SERVICE_UNIT}"
  systemctl daemon-reload || true
  echo "Auto-update timer removed."
}

apply_auto_update_flag() {
  case "$AUTO_UPDATE" in
    on)  install_auto_update_timer;;
    off) remove_auto_update_timer;;
    "")  : ;;
  esac
}

case "$MODE" in
  install)   do_install; apply_auto_update_flag;;
  upgrade)   do_upgrade; apply_auto_update_flag;;
  uninstall) remove_auto_update_timer; do_uninstall;;
esac
