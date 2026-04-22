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
#   --uninstall         Stop + remove container; keep volume
#   --purge             With --uninstall: also remove volume and install dir
set -euo pipefail

VERSION="latest"
PORT="8000"
DATA_DIR=""
NO_DOCKER_INSTALL=""
MODE="install"
PURGE=""

INSTALL_DIR="/opt/maestro-cp"
IMAGE="ghcr.io/enzinobb/maestro-cp"

usage() {
  sed -n '2,15p' "$0" | sed 's/^# \{0,1\}//'
  exit "${1:-0}"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --version)           VERSION="$2"; shift 2;;
    --port)              PORT="$2"; shift 2;;
    --data-dir)          DATA_DIR="$2"; shift 2;;
    --no-docker-install) NO_DOCKER_INSTALL="1"; shift;;
    --upgrade)           MODE="upgrade"; shift;;
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
  if ! docker compose version >/dev/null 2>&1; then
    echo "Docker installed but 'docker compose' v2 is not available. Install it manually." >&2
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
  docker compose -f $INSTALL_DIR/docker-compose.yml logs control-plane | grep -A1 "GENERATED MAESTRO DAEMON TOKEN"

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

case "$MODE" in
  install)   do_install;;
  upgrade)   do_upgrade;;
  uninstall) do_uninstall;;
esac
