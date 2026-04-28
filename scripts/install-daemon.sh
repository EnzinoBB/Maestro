#!/usr/bin/env bash
# install-daemon.sh — install, upgrade, or uninstall the Maestro daemon.
#
# Typical install (binary + service):
#   curl -fsSL https://playmaestro.cloud/install-daemon.sh | sudo bash -s -- \
#     --host-id api-01 --token <TOKEN>
#
# Or via GitHub:
#   curl -fsSL https://github.com/EnzinoBB/Maestro/releases/latest/download/install-daemon.sh | \
#     sudo bash -s -- --cp-url https://cp.example --host-id api-01 --token <TOKEN>
#
# Flags:
#   --cp-url <url>       Control plane URL (also determines binary source).
#                        If omitted, uses DEFAULT_CP_URL baked into the script.
#   --host-id <id>       Identifier for this host (default: `hostname -s`)
#   --token <token>      Shared daemon token (required for install)
#   --version <tag>      Pin binary version; default: fetch from CP, fallback to GitHub latest
#   --from-github        Force GitHub as binary source
#   --insecure           Accept self-signed TLS / http CP (sets daemon insecure flag)
#   --upgrade            Download new binary, restart service
#   --auto-update        Install a systemd timer that runs --upgrade weekly
#                        (Sundays 04:30 local). Use --auto-update=off to remove.
#   --uninstall          Stop + remove service and binary
#   --purge              With --uninstall: also remove config and state dir
set -euo pipefail

# DEFAULT_CP_URL is string-substituted by the CP's /install-daemon.sh endpoint.
# Leave empty in the repo copy; CI ensures this line survives unchanged.
DEFAULT_CP_URL=""

GITHUB_LATEST="https://github.com/EnzinoBB/Maestro/releases/latest/download"
GITHUB_RELEASE_FMT="https://github.com/EnzinoBB/Maestro/releases/download/%s"

CP_URL=""
HOST_ID=""
TOKEN=""
VERSION=""
FROM_GITHUB=""
INSECURE=""
MODE="install"
PURGE=""
AUTO_UPDATE=""

# Track whether each identity-related flag was explicitly provided. Used by
# --upgrade to decide whether to rewrite the config. Without this we cannot
# distinguish "operator did not pass --token" (keep the existing one) from
# "operator passed --token ''" (which we treat the same — non-empty wins).
TOKEN_GIVEN=""
HOST_ID_GIVEN=""
CP_URL_GIVEN=""
INSECURE_GIVEN=""

UPDATE_TIMER_UNIT="maestro-daemon-update.timer"
UPDATE_SERVICE_UNIT="maestro-daemon-update.service"

usage() {
  sed -n '2,22p' "$0" | sed 's/^# \{0,1\}//'
  exit "${1:-0}"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --cp-url)      CP_URL="$2"; CP_URL_GIVEN="1"; shift 2;;
    --host-id)     HOST_ID="$2"; HOST_ID_GIVEN="1"; shift 2;;
    --token)       TOKEN="$2"; TOKEN_GIVEN="1"; shift 2;;
    --version)     VERSION="$2"; shift 2;;
    --from-github) FROM_GITHUB="1"; shift;;
    --insecure)    INSECURE="1"; INSECURE_GIVEN="1"; shift;;
    --upgrade)         MODE="upgrade"; shift;;
    --auto-update)     AUTO_UPDATE="on"; shift;;
    --auto-update=on)  AUTO_UPDATE="on"; shift;;
    --auto-update=off) AUTO_UPDATE="off"; shift;;
    --uninstall)       MODE="uninstall"; shift;;
    --purge)           PURGE="1"; shift;;
    -h|--help)         usage 0;;
    *) echo "unknown argument: $1" >&2; usage 2;;
  esac
done

[[ -z "$CP_URL" ]] && CP_URL="$DEFAULT_CP_URL"

# ---- Platform detection ------------------------------------------------------
OS_NAME="$(uname -s)"
ARCH_NAME="$(uname -m)"
case "$ARCH_NAME" in
  x86_64|amd64) ARCH="amd64";;
  aarch64|arm64) ARCH="arm64";;
  *) echo "unsupported arch: $ARCH_NAME" >&2; exit 2;;
esac
case "$OS_NAME" in
  Linux)  OS="linux";  SERVICE_KIND="systemd";;
  Darwin) OS="darwin"; SERVICE_KIND="launchd";;
  *) echo "unsupported OS: $OS_NAME" >&2; exit 2;;
esac

# ---- Paths -------------------------------------------------------------------
if [[ "$OS" == "linux" ]]; then
  BIN_DST="/usr/local/bin/maestrod"
  CFG_DIR="/etc/maestrod"
  WORK_DIR="/var/lib/maestrod"
  UNIT_FILE="/etc/systemd/system/maestro-daemon.service"
else
  BIN_DST="/usr/local/bin/maestrod"
  CFG_DIR="/usr/local/etc/maestrod"
  WORK_DIR="/usr/local/var/maestrod"
  PLIST_FILE="/Library/LaunchDaemons/com.maestro.daemon.plist"
fi
CFG_FILE="$CFG_DIR/config.yaml"

require_root() {
  if [[ $EUID -ne 0 ]]; then
    echo "This installer must run as root (prefix with sudo)." >&2
    exit 1
  fi
}

# ---- Download binary + verify checksum --------------------------------------
download_binary() {
  local tmpdir
  tmpdir="$(mktemp -d)"
  # Expand $tmpdir NOW (double quotes), not when the trap fires: the local
  # may be out of scope by then, and `set -u` would explode with
  # "tmpdir: unbound variable". The early expansion is intentional (SC2064
  # is suppressed via the directive below).
  # shellcheck disable=SC2064
  trap "rm -rf -- '$tmpdir'" RETURN
  local binary_name="maestrod-${OS}-${ARCH}"
  local base_url checksum_url

  if [[ -n "$FROM_GITHUB" || -z "$CP_URL" ]]; then
    if [[ -n "$VERSION" ]]; then
      # shellcheck disable=SC2059
      base_url="$(printf "$GITHUB_RELEASE_FMT" "$VERSION")"
    else
      base_url="$GITHUB_LATEST"
    fi
  else
    base_url="${CP_URL%/}/dist"
  fi
  checksum_url="${base_url}/SHA256SUMS"

  echo "Downloading $binary_name from $base_url …"
  curl -fsSL --retry 3 --retry-delay 2 --retry-connrefused \
       --connect-timeout 10 --max-time 300 \
       "${base_url}/${binary_name}" -o "$tmpdir/$binary_name"
  curl -fsSL --retry 3 --retry-delay 2 --retry-connrefused \
       --connect-timeout 10 --max-time 60 \
       "$checksum_url" -o "$tmpdir/SHA256SUMS"

  echo "Verifying SHA256 …"
  # --ignore-missing lets sha256sum verify only the files we actually
  # downloaded, without needing a fragile grep on the SUMS format.
  (cd "$tmpdir" && sha256sum --ignore-missing -c SHA256SUMS) || {
    echo "Checksum mismatch for $binary_name — aborting" >&2
    exit 6
  }

  install -m 0755 "$tmpdir/$binary_name" "$BIN_DST"
}

# ---- Write config -----------------------------------------------------------
write_config() {
  mkdir -p "$CFG_DIR" "$WORK_DIR"
  chmod 0750 "$CFG_DIR"
  local systemd_flag="true"
  [[ "$OS" == "darwin" ]] && systemd_flag="false"
  # gorilla/websocket requires ws:// or wss:// schemes. Translate from the
  # http(s):// we accepted on --cp-url.
  local ws_endpoint="${CP_URL%/}/ws/daemon"
  ws_endpoint="${ws_endpoint/#http:\/\//ws://}"
  ws_endpoint="${ws_endpoint/#https:\/\//wss://}"
  cat > "$CFG_FILE" <<EOF
host_id: ${HOST_ID}
endpoint: ${ws_endpoint}
token: ${TOKEN}
working_dir: ${WORK_DIR}
state_path: ${WORK_DIR}/state.db
docker_enabled: true
systemd_enabled: ${systemd_flag}
insecure: ${INSECURE:-false}
metrics_interval_sec: 30
EOF
  chmod 0600 "$CFG_FILE"
}

# ---- Service install (systemd) ----------------------------------------------
install_systemd() {
  cat > "$UNIT_FILE" <<EOF
[Unit]
Description=Maestro daemon (maestrod)
After=network-online.target docker.service
Wants=network-online.target

[Service]
Type=simple
ExecStart=${BIN_DST} --config ${CFG_FILE}
Restart=always
RestartSec=5
User=root
Group=root
LimitNOFILE=65536

[Install]
WantedBy=multi-user.target
EOF
  systemctl daemon-reload
  systemctl enable --now maestro-daemon.service
}

# ---- Service install (launchd) ----------------------------------------------
install_launchd() {
  cat > "$PLIST_FILE" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.maestro.daemon</string>
  <key>ProgramArguments</key>
    <array>
      <string>${BIN_DST}</string>
      <string>--config</string>
      <string>${CFG_FILE}</string>
    </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>/var/log/maestro-daemon.out.log</string>
  <key>StandardErrorPath</key><string>/var/log/maestro-daemon.err.log</string>
</dict>
</plist>
EOF
  chmod 0644 "$PLIST_FILE"
  launchctl unload "$PLIST_FILE" 2>/dev/null || true
  launchctl load "$PLIST_FILE"
}

# ---- Service control (both) -------------------------------------------------
service_start() {
  if [[ "$SERVICE_KIND" == "systemd" ]]; then install_systemd
  else install_launchd; fi
}

service_stop() {
  if [[ "$SERVICE_KIND" == "systemd" ]]; then
    systemctl disable --now maestro-daemon.service 2>/dev/null || true
    rm -f "$UNIT_FILE"
    systemctl daemon-reload
  else
    launchctl unload "$PLIST_FILE" 2>/dev/null || true
    rm -f "$PLIST_FILE"
  fi
}

service_status_ok() {
  if [[ "$SERVICE_KIND" == "systemd" ]]; then
    systemctl is-active --quiet maestro-daemon.service
  else
    launchctl list | grep -q com.maestro.daemon
  fi
}

wait_running() {
  local tries=10
  while (( tries > 0 )); do
    if service_status_ok; then return 0; fi
    sleep 1; tries=$((tries-1))
  done
  echo "daemon did not start within 10s; recent logs:" >&2
  if [[ "$SERVICE_KIND" == "systemd" ]]; then
    journalctl -u maestro-daemon.service -n 30 --no-pager >&2 || true
  else
    tail -n 30 /var/log/maestro-daemon.err.log 2>/dev/null >&2 || true
  fi
  return 7
}

# ---- Modes ------------------------------------------------------------------
do_install() {
  require_root
  if [[ -f "$CFG_FILE" ]]; then
    echo "Existing installation detected at $CFG_FILE." >&2
    echo "  - To rotate the token / change host-id / change cp-url:" >&2
    echo "      sudo $0 --upgrade --token <NEW> --host-id <NEW> --cp-url <NEW>" >&2
    echo "    (any flag you don't pass keeps its current value)" >&2
    echo "  - To start over:" >&2
    echo "      sudo $0 --uninstall --purge" >&2
    exit 6
  fi
  [[ -z "$HOST_ID" ]] && HOST_ID="$(hostname -s)"
  if [[ -z "$TOKEN" ]]; then
    echo "--token is required (read the CP logs: GENERATED MAESTRO DAEMON TOKEN)" >&2
    exit 2
  fi
  if [[ -z "$CP_URL" ]]; then
    echo "--cp-url is required (or invoke via an enroll URL served by the CP)" >&2
    exit 2
  fi
  if [[ ! "$CP_URL" =~ ^https?:// ]]; then
    echo "--cp-url must start with http:// or https:// (got: $CP_URL)" >&2
    exit 2
  fi
  download_binary
  write_config
  service_start
  wait_running
  echo "maestrod installed and running (host_id=$HOST_ID, endpoint=$CP_URL)."
}

do_upgrade() {
  require_root
  if [[ ! -f "$CFG_FILE" ]]; then
    echo "$CFG_FILE not found; run install first." >&2
    exit 5
  fi
  # Derive CP_URL from existing config if not overridden.
  # Config stores ws://host/ws/daemon; download_binary needs http(s)://host.
  if [[ -z "$CP_URL" ]]; then
    CP_URL="$(awk -F': *' '/^endpoint:/ {print $2; exit}' "$CFG_FILE" | sed 's#/ws/daemon$##')"
    CP_URL="${CP_URL/#ws:\/\//http://}"
    CP_URL="${CP_URL/#wss:\/\//https://}"
  fi
  # Download + verify BEFORE stopping the service. If the download or
  # checksum fails we must leave the running daemon untouched; install(8)
  # overwrites the binary atomically via unlink+rename, and Linux keeps
  # the running inode around until the process exits.
  download_binary
  # If the operator passed any identity flag, rewrite the config so the
  # restarted daemon picks up the new value. Fields they didn't pass keep
  # their existing value (read back from the current config). This makes
  # `--upgrade --token <NEW>` the supported way to rotate a token after
  # CP regeneration, which previously required --uninstall + --install.
  if [[ -n "${TOKEN_GIVEN}${HOST_ID_GIVEN}${CP_URL_GIVEN}${INSECURE_GIVEN}" ]]; then
    if [[ -z "$HOST_ID_GIVEN" ]]; then
      HOST_ID="$(awk -F': *' '/^host_id:/ {print $2; exit}' "$CFG_FILE")"
    fi
    if [[ -z "$TOKEN_GIVEN" ]]; then
      # Tokens may legitimately contain shell-special chars; awk on the
      # first space-delimited field after the colon is correct for the
      # narrow set of values we write here (hex / base64url).
      TOKEN="$(awk -F': *' '/^token:/ {print $2; exit}' "$CFG_FILE")"
    fi
    if [[ -z "$INSECURE_GIVEN" ]]; then
      _existing_insecure="$(awk -F': *' '/^insecure:/ {print $2; exit}' "$CFG_FILE")"
      [[ "$_existing_insecure" == "true" ]] && INSECURE="1"
    fi
    write_config
  fi
  if [[ "$SERVICE_KIND" == "systemd" ]]; then
    systemctl restart maestro-daemon.service
  else
    launchctl unload "$PLIST_FILE" 2>/dev/null || true
    launchctl load "$PLIST_FILE"
  fi
  wait_running
  echo "maestrod upgraded."
}

do_uninstall() {
  require_root
  service_stop
  rm -f "$BIN_DST"
  if [[ -n "$PURGE" ]]; then
    rm -rf "$CFG_DIR" "$WORK_DIR"
    echo "Purged: binary, service unit, config, state."
  else
    echo "Removed binary and service. Config and state preserved. Use --purge to wipe."
  fi
}

install_auto_update_timer() {
  if [[ "$SERVICE_KIND" != "systemd" ]]; then
    echo "  --auto-update currently supports systemd only (this host is $SERVICE_KIND)." >&2
    return 1
  fi
  # Persist enough context so the timer can re-invoke the installer with the
  # same CP_URL. We keep CP_URL in /etc/maestrod/installer.env (no secrets).
  mkdir -p "$CFG_DIR"
  printf 'CP_URL=%q\n' "$CP_URL" > "$CFG_DIR/installer.env"
  chmod 0600 "$CFG_DIR/installer.env"

  # Cache the installer script so the timer doesn't depend on network DNS at
  # launch (only the binary download needs network).
  install -m 0755 "$0" "/usr/local/sbin/maestro-install-daemon.sh" 2>/dev/null || \
    cp -f "$0" "/usr/local/sbin/maestro-install-daemon.sh" 2>/dev/null || true

  cat > "/etc/systemd/system/${UPDATE_SERVICE_UNIT}" <<EOF
[Unit]
Description=Maestro daemon self-upgrade (latest binary)
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
EnvironmentFile=$CFG_DIR/installer.env
ExecStart=/usr/local/sbin/maestro-install-daemon.sh --upgrade --cp-url \${CP_URL}
EOF
  cat > "/etc/systemd/system/${UPDATE_TIMER_UNIT}" <<EOF
[Unit]
Description=Maestro daemon weekly update

[Timer]
OnCalendar=Sun *-*-* 04:30:00
Persistent=true
RandomizedDelaySec=30m

[Install]
WantedBy=timers.target
EOF
  systemctl daemon-reload
  systemctl enable --now "${UPDATE_TIMER_UNIT}"
  echo "Auto-update timer installed: $(systemctl list-timers --no-pager "${UPDATE_TIMER_UNIT}" | sed -n '2p')"
}

remove_auto_update_timer() {
  if [[ "$SERVICE_KIND" != "systemd" ]]; then return 0; fi
  systemctl disable --now "${UPDATE_TIMER_UNIT}" 2>/dev/null || true
  rm -f "/etc/systemd/system/${UPDATE_TIMER_UNIT}" "/etc/systemd/system/${UPDATE_SERVICE_UNIT}"
  rm -f "/usr/local/sbin/maestro-install-daemon.sh"
  rm -f "$CFG_DIR/installer.env" 2>/dev/null || true
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
