#!/usr/bin/env bash
# 插件架构本地开发：Rust local-service + extension 构建提示
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PORT="${HUOKE_LOCAL_PORT:-18766}"

echo "=== Huoke Extension Dev ==="
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
if [[ ! -d node_modules ]]; then
  npm install
fi
npm run build
echo "  ✓ extension/dist 已更新"
echo ""

if lsof -iTCP:"${PORT}" -sTCP:LISTEN -P -n >/dev/null 2>&1; then
  echo ">>> local-service 已在端口 ${PORT} 运行"
else
  echo ">>> 启动 local-service (端口 ${PORT})"
  cd "$ROOT/local-service"
  HUOKE_LOCAL_PORT="$PORT" cargo run &
  LS_PID=$!
  echo "$LS_PID" > "$ROOT/storage/extension-dev/local-service.pid"
  for _ in $(seq 1 30); do
    if curl -fsS "http://127.0.0.1:${PORT}/health" >/dev/null 2>&1; then
      echo "  ✓ local-service 就绪"
      break
    fi
    sleep 0.5
  done
fi

echo ""
echo "下一步:"
echo "  1. Chrome 打开 chrome://extensions"
echo "  2. 开启「开发者模式」"
echo "  3. 「加载已解压的扩展程序」→ $ROOT/extension/dist"
echo "  4. 打开抖音页面，执行:"
echo "     curl -X POST http://127.0.0.1:${PORT}/bridge/command -H 'Content-Type: application/json' -d '{\"action\":\"get_page_info\",\"payload\":{},\"wait\":true}'"
echo "  5. 关键词采集（需抖音页为当前活动标签）:"
echo "     bash scripts/test-douyin-collect.sh 装修"
echo ""
echo "文档: docs/technical/extension-architecture.md"
