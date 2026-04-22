#!/bin/sh
# docker-entrypoint.sh — bootstrap MAESTRO_DAEMON_TOKEN on first start.
# Precedence:
#   1. MAESTRO_DAEMON_TOKEN env var set by the admin  → use as-is.
#   2. /data/daemon-token file exists                → read it.
#   3. Generate random 32-byte hex, persist, print banner.
set -eu

TOKEN_FILE="${MAESTRO_TOKEN_FILE:-/data/daemon-token}"

if [ -n "${MAESTRO_DAEMON_TOKEN:-}" ]; then
    : # admin-provided token, nothing to do
elif [ -s "$TOKEN_FILE" ]; then
    MAESTRO_DAEMON_TOKEN="$(cat "$TOKEN_FILE")"
    export MAESTRO_DAEMON_TOKEN
else
    umask 077
    mkdir -p "$(dirname "$TOKEN_FILE")"
    MAESTRO_DAEMON_TOKEN="$(python -c 'import secrets; print(secrets.token_hex(32))')"
    printf '%s' "$MAESTRO_DAEMON_TOKEN" > "$TOKEN_FILE"
    chmod 600 "$TOKEN_FILE"
    export MAESTRO_DAEMON_TOKEN
    cat <<EOF
===========================================================
  GENERATED MAESTRO DAEMON TOKEN (save this, shown once):
    $MAESTRO_DAEMON_TOKEN
  Also stored at $TOKEN_FILE inside the container.
===========================================================
EOF
fi

exec "$@"
