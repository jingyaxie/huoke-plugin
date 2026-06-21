#!/usr/bin/env bash
# 本地开发：构建插件 + 启动 local-service
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=scripts/lib/common.sh
source "$ROOT/scripts/lib/common.sh"

PORT="${HUOKE_LOCAL_PORT:-18766}"

echo "=== Huoke Dev ==="
echo ""

if ! command -v cargo >/dev/null 2>&1; then
  echo "未找到 cargo，请安装 Rust: https://rustup.rs" >&2
  exit 1
fi

if ! command -v npm >/dev/null 2>&1; then
  echo "未找到 npm" >&2
  exit 1
fi

echo ">>> 构建 Chrome 插件 (extension/)"
cd "$ROOT/extension"
if [[ ! -d node_modules ]]; then npm install; fi
npm run build
echo "  ✓ extension/dist 已更新"
echo ""

mkdir -p "$ROOT/storage/extension-dev"

if port_listening "$PORT"; then
  echo ">>> 清理端口 ${PORT} 上的旧 local-service"
  kill_port "$PORT"
fi

echo ">>> 启动 local-service (端口 ${PORT})"
cd "$ROOT/local-service"
HUOKE_DATA_DIR="${HUOKE_DATA_DIR:-$ROOT/storage/local-service}" \
  HUOKE_LOCAL_PORT="$PORT" \
  cargo run --release &
LS_PID=$!
echo "$LS_PID" > "$ROOT/storage/extension-dev/local-service.pid"
wait_url "http://127.0.0.1:${PORT}/health" "local-service" 60 || exit 1

if curl -fsS -m 5 -X POST "http://127.0.0.1:${PORT}/api/runtime/init" >/dev/null 2>&1; then
  echo "  ✓ 运行环境已初始化"
fi

echo ""
echo "下一步:"
echo "  1. Chrome → chrome://extensions → 加载 $ROOT/extension/dist"
echo "  2. 打开抖音页面并保持为活动标签"
echo "  3. 管理页: cd frontend && npm run dev  → http://localhost:5173/extension-bridge"
echo "  4. 采集冒烟: bash scripts/test-douyin-collect.sh 装修"
echo ""
echo "验证: npm run verify"
