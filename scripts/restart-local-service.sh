#!/usr/bin/env bash
# 重启 local-service（保留数据目录，不重建插件）
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=scripts/lib/common.sh
source "$ROOT/scripts/lib/common.sh"

PORT="${HUOKE_LOCAL_PORT:-18766}"
DATA_DIR="${HUOKE_DATA_DIR:-$ROOT/storage/local-service}"
PID_FILE="$ROOT/storage/extension-dev/local-service.pid"
LOG_FILE="${HUOKE_LOCAL_LOG:-$ROOT/storage/extension-dev/local-service.log}"

mkdir -p "$ROOT/storage/extension-dev" "$DATA_DIR"

echo "=== 重启 local-service (端口 ${PORT}) ==="

if port_listening "$PORT"; then
  echo ">>> 停止旧进程"
  kill_port "$PORT"
  sleep 0.5
fi

if [[ -f "$PID_FILE" ]]; then
  old_pid="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [[ -n "$old_pid" ]] && kill -0 "$old_pid" 2>/dev/null; then
    kill "$old_pid" 2>/dev/null || true
    sleep 0.3
  fi
  rm -f "$PID_FILE"
fi

echo ">>> 编译 release"
cd "$ROOT/local-service"
cargo build --release --bin huoke-local-service --quiet

echo ">>> 启动 local-service"
nohup env \
  HUOKE_DATA_DIR="$DATA_DIR" \
  HUOKE_LOCAL_PORT="$PORT" \
  "$ROOT/local-service/target/release/huoke-local-service" \
  >>"$LOG_FILE" 2>&1 &
LS_PID=$!
echo "$LS_PID" > "$PID_FILE"

wait_url "http://127.0.0.1:${PORT}/health" "local-service" 60

if curl -fsS -m 5 -X POST "http://127.0.0.1:${PORT}/api/runtime/init" >/dev/null 2>&1; then
  echo "  ✓ 运行环境已初始化"
fi

echo ""
echo "local-service 已重启 (pid=${LS_PID}, log=${LOG_FILE})"
