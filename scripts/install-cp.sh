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
#   --import-db <path>  Copy an existing CP SQLite DB into the new install
#                       before starting the container. Implies --data-dir
#                       (defaults to /opt/maestro-cp-data) so the imported
#                       DB lives on a host path, not in a docker volume.
#                       Refuses to overwrite a non-empty target.
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
IMPORT_DB=""      # path to an existing cp DB to copy into --data-dir/cp.db

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
    --import-db)         IMPORT_DB="$2"; shift 2;;
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

ensure_docker_apt_repo() {
  # Configure Docker's official apt repository so docker-compose-plugin
  # is available. Idempotent — does nothing if the repo already exists.
  # Requires apt-get + curl + lsb-release-style /etc/os-release info.
  if [[ -f /etc/apt/sources.list.d/docker.list ]] || \
     grep -rqs "download.docker.com" /etc/apt/sources.list.d/ 2>/dev/null; then
    return 0
  fi
  if [[ ! -r /etc/os-release ]]; then
    return 1
  fi
  # shellcheck disable=SC1091
  . /etc/os-release
  local distro="${ID:-}"
  local codename="${VERSION_CODENAME:-}"
  case "$distro" in
    ubuntu|debian) ;;
    *) return 1;;  # Not a Debian-family system; caller will try fallbacks.
  esac
  if [[ -z "$codename" ]]; then
    return 1
  fi
  echo "  Adding Docker's official apt repository for ${distro} ${codename} …"
  DEBIAN_FRONTEND=noninteractive apt-get update -y >/dev/null 2>&1 || true
  DEBIAN_FRONTEND=noninteractive apt-get install -y \
    ca-certificates curl gnupg >/dev/null 2>&1 || true
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL "https://download.docker.com/linux/${distro}/gpg" \
    -o /etc/apt/keyrings/docker.asc 2>/dev/null
  chmod a+r /etc/apt/keyrings/docker.asc 2>/dev/null || true
  local arch
  arch="$(dpkg --print-architecture 2>/dev/null || echo amd64)"
  echo "deb [arch=${arch} signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/${distro} ${codename} stable" \
    > /etc/apt/sources.list.d/docker.list
  DEBIAN_FRONTEND=noninteractive apt-get update -y >/dev/null 2>&1 || true
  return 0
}

ensure_compose_plugin() {
  # Install the Docker Compose v2 plugin when it's missing. We try, in order:
  #   1) apt-get with the Docker official repo wired up if necessary
  #      (Debian / Ubuntu)
  #   2) dnf or yum (RHEL / Fedora / Rocky / Alma / Amazon Linux)
  #   3) standalone CLI plugin binary into /usr/libexec/docker/cli-plugins/
  #
  # Returns 0 when 'docker compose version' works at the end.
  if docker compose version >/dev/null 2>&1; then
    return 0
  fi
  echo "'docker compose' v2 is missing — attempting to install the plugin …"
  if command -v apt-get >/dev/null 2>&1; then
    # First try as-is; on hosts with the Docker repo already configured this
    # one shot succeeds without us touching apt sources.
    if ! DEBIAN_FRONTEND=noninteractive apt-get install -y docker-compose-plugin >/dev/null 2>&1; then
      ensure_docker_apt_repo || true
      DEBIAN_FRONTEND=noninteractive apt-get install -y docker-compose-plugin >/dev/null 2>&1 || true
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
  # Authentication is always required. The login page detects no-admin-yet
  # and offers a "create admin" form on first visit.
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

check_target_port_free() {
  # Refuse to install when the target port is held by something else.
  # Common cause: an old manual uvicorn from Phase-1 development is still
  # running. We list the holder so the operator knows what to stop.
  if ! command -v ss >/dev/null 2>&1; then
    return 0   # can't check; trust docker to surface the issue
  fi
  if ss -ltn "sport = :${PORT}" 2>/dev/null | grep -q LISTEN; then
    echo "Port ${PORT} is already in use." >&2
    echo "Holder(s):" >&2
    sudo -n ss -ltnp "sport = :${PORT}" 2>/dev/null | sed -n '2,$p' >&2 || \
      ss -ltn "sport = :${PORT}" 2>/dev/null | sed -n '2,$p' >&2
    echo "Stop the existing process (e.g. 'sudo pkill -f \"uvicorn app.main:app\"')," >&2
    echo "or re-run with --port <N> to use a different port." >&2
    exit 8
  fi
}

import_existing_db() {
  # When --import-db is set, copy the source DB into the data-dir BEFORE
  # the container starts. We force --data-dir on so the imported file
  # ends up on the host filesystem (named-volume copy is awkward and
  # would need docker cp post-up).
  if [[ -z "$IMPORT_DB" ]]; then
    return 0
  fi
  if [[ ! -r "$IMPORT_DB" ]]; then
    echo "--import-db: source not readable: $IMPORT_DB" >&2
    exit 9
  fi
  if [[ -z "$DATA_DIR" ]]; then
    DATA_DIR="/opt/maestro-cp-data"
    echo "--import-db: no --data-dir given, defaulting to $DATA_DIR"
  fi
  mkdir -p "$DATA_DIR"
  local target="$DATA_DIR/cp.db"
  if [[ -e "$target" && -s "$target" ]]; then
    echo "--import-db: refusing to overwrite non-empty $target" >&2
    echo "Move it out of the way first, or run --uninstall --purge." >&2
    exit 9
  fi
  echo "Importing $IMPORT_DB → $target …"
  install -m 0644 "$IMPORT_DB" "$target"
  # The container runs as root inside, so 0644 is enough for the file.
  # If a future image switches to a non-root user, chown the data dir.
}

do_install() {
  require_root
  if [[ -f "$INSTALL_DIR/docker-compose.yml" ]]; then
    echo "Existing installation detected at $INSTALL_DIR/docker-compose.yml." >&2
    echo "Use --upgrade to change version/port, or --uninstall first." >&2
    exit 6
  fi
  check_target_port_free
  ensure_docker
  import_existing_db
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
