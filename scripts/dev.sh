#!/usr/bin/env bash
# 本地开发一键启动：后端 (8000) + Vite 前端 (5173)
# 用法: bash scripts/dev.sh
#       bash scripts/dev.sh --reload   # API 热重载（会打断长浏览器任务）
# 停止: bash scripts/dev.sh --stop
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=scripts/dev-common.sh
source "$ROOT/scripts/dev-common.sh"

BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"
LOG_DIR="${ROOT}/storage/dev"
BACKEND_LOG="${LOG_DIR}/backend.log"
FRONTEND_LOG="${LOG_DIR}/frontend.log"
BACKEND_PID="${LOG_DIR}/backend.pid"
FRONTEND_PID="${LOG_DIR}/frontend.pid"

mkdir -p "$LOG_DIR"

stop_all() {
  for pf in "$BACKEND_PID" "$FRONTEND_PID"; do
    if [[ -f "$pf" ]]; then
      pid="$(cat "$pf" 2>/dev/null || true)"
      if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
        kill "$pid" 2>/dev/null || true
        echo "已停止 PID ${pid} ($(basename "$pf" .pid))"
      fi
      rm -f "$pf"
    fi
  done
}

HUOKE_BACKEND_RELOAD="${HUOKE_BACKEND_RELOAD:-0}"
if [[ "${1:-}" == "--stop" ]]; then
  stop_all
  exit 0
fi
if [[ "${1:-}" == "--reload" ]]; then
  HUOKE_BACKEND_RELOAD=1
  shift
fi

echo "=== Huoke 本地开发 ==="

if [[ "$HUOKE_BACKEND_RELOAD" == "1" ]] && dev_port_listen "$BACKEND_PORT"; then
  echo "  · --reload：重启后端以开启热重载..."
  if [[ -f "$BACKEND_PID" ]]; then
    pid="$(cat "$BACKEND_PID" 2>/dev/null || true)"
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
    fi
    rm -f "$BACKEND_PID"
  fi
  # 兜底：停掉仍占用端口的 uvicorn/reloader 进程
  pids="$(lsof -tiTCP:"${BACKEND_PORT}" -sTCP:LISTEN 2>/dev/null || true)"
  if [[ -n "$pids" ]]; then
    kill $pids 2>/dev/null || true
    sleep 1
  fi
fi

if dev_port_listen "$BACKEND_PORT"; then
  echo "  · 后端已在端口 ${BACKEND_PORT}（未加 --reload 则保持当前进程）"
else
  echo "  · 启动后端..."
  nohup env BACKEND_PORT="$BACKEND_PORT" HUOKE_BACKEND_RELOAD="$HUOKE_BACKEND_RELOAD" \
    bash "$ROOT/scripts/dev-native.sh" >>"$BACKEND_LOG" 2>&1 &
  echo $! >"$BACKEND_PID"
  dev_wait_health "http://127.0.0.1:${BACKEND_PORT}/api/health" "后端" "$BACKEND_LOG"
fi

if dev_port_listen "$FRONTEND_PORT"; then
  echo "  · 前端已在端口 ${FRONTEND_PORT}"
else
  echo "  · 启动前端..."
  (
    cd "$ROOT/frontend"
    nohup npm run dev -- --host 127.0.0.1 --port "$FRONTEND_PORT" >>"$FRONTEND_LOG" 2>&1
  ) &
  echo $! >"$FRONTEND_PID"
  for _ in $(seq 1 45); do
    if dev_port_listen "$FRONTEND_PORT"; then
      echo "  ✓ 前端就绪"
      break
    fi
    sleep 1
  done
fi

echo ""
echo "前端:     http://127.0.0.1:${FRONTEND_PORT}/"
echo "API 文档: http://127.0.0.1:${BACKEND_PORT}/docs"
echo "日志:     ${LOG_DIR}/"
echo "停止:     bash scripts/dev.sh --stop"
if [[ "$HUOKE_BACKEND_RELOAD" == "1" ]]; then
  echo "热重载:   已开启（改 backend 代码会自动重启 API；长浏览器任务可能被打断）"
else
  echo "热重载:   bash scripts/dev.sh --reload  (默认稳定模式，不打断浏览器任务)"
fi
