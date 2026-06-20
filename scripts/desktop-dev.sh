#!/usr/bin/env bash
# Tauri 桌面开发：static(18765) + local-service(18766)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=scripts/lib/common.sh
source "$ROOT/scripts/lib/common.sh"

PORT_STATIC="${HUOKE_DESKTOP_PORT:-18765}"
PORT_LOCAL="${HUOKE_LOCAL_PORT:-18766}"

kill_port "$PORT_STATIC"
kill_port "$PORT_LOCAL"

if [[ ! -f "$ROOT/frontend/dist/index.html" ]]; then
  echo "构建前端 dist..."
  cd "$ROOT/frontend"
  if [[ ! -d node_modules ]]; then npm install; fi
  VITE_LOCAL_SERVICE_URL="http://127.0.0.1:${PORT_LOCAL}" npm run build
fi

LS_BIN="$ROOT/local-service/target/debug/huoke-local-service"
if [[ ! -x "$LS_BIN" ]]; then
  LS_BIN="$ROOT/local-service/target/release/huoke-local-service"
fi
if [[ ! -x "$LS_BIN" ]]; then
  echo "编译 local-service..."
  (cd "$ROOT/local-service" && cargo build)
  LS_BIN="$ROOT/local-service/target/debug/huoke-local-service"
fi

HUOKE_DATA_DIR="${HUOKE_DATA_DIR:-$ROOT/storage/local-service}" \
  HUOKE_LOCAL_PORT="$PORT_LOCAL" \
  "$LS_BIN" &
LS_PID=$!

cd "$ROOT/frontend"
npx vite preview --host 127.0.0.1 --port "$PORT_STATIC" &
STATIC_PID=$!

cleanup() {
  kill "$LS_PID" "$STATIC_PID" 2>/dev/null || true
}
trap cleanup EXIT

echo "等待服务就绪..."
for _ in $(seq 1 60); do
  if curl -fsS "http://127.0.0.1:${PORT_STATIC}/" >/dev/null 2>&1 \
    && curl -fsS "http://127.0.0.1:${PORT_LOCAL}/health" >/dev/null 2>&1; then
    echo "desktop dev 就绪: UI=${PORT_STATIC} local-service=${PORT_LOCAL}"
    exit 0
  fi
  if ! kill -0 "$LS_PID" 2>/dev/null; then
    echo "local-service 启动失败" >&2
    exit 1
  fi
  sleep 0.5
done

echo "desktop dev 启动超时" >&2
exit 1
