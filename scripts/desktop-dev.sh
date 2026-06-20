#!/usr/bin/env bash
# Tauri 开发前启动后端（beforeDevCommand）
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=scripts/dev-common.sh
source "$ROOT/scripts/dev-common.sh"
# shellcheck source=scripts/desktop-common.sh
source "$ROOT/scripts/desktop-common.sh"

BACKEND_PORT="${BACKEND_PORT:-$HUOKE_DESKTOP_PORT}"

"$ROOT/scripts/desktop-run-backend.sh" &
BACKEND_PID=$!

echo "等待后端就绪 (http://127.0.0.1:${BACKEND_PORT})..."
if dev_wait_backend "$BACKEND_PORT" "$BACKEND_PID" 90; then
  echo "后端已就绪 (pid=${BACKEND_PID})"
  exit 0
fi

kill "$BACKEND_PID" 2>/dev/null || true
exit 1
