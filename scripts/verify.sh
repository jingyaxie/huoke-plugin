#!/usr/bin/env bash
# 插件架构一键验证
# 用法: bash scripts/verify.sh  或  npm run verify
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PORT="${HUOKE_LOCAL_PORT:-18766}"
BASE="http://127.0.0.1:${PORT}"
PASS=0
FAIL=0
SKIP=0

ok()   { echo "  ✓ $*"; PASS=$((PASS + 1)); }
bad()  { echo "  ✗ $*" >&2; FAIL=$((FAIL + 1)); }
skip() { echo "  ~ $*"; SKIP=$((SKIP + 1)); }

echo "=== Huoke 验证 ==="
echo "BASE=$BASE"
echo ""

echo "[1/5] 构建产物"
if [[ -f "$ROOT/extension/dist/manifest.json" ]]; then
  ok "extension/dist/manifest.json"
else
  bad "extension/dist 缺失 — 运行: npm run setup"
fi

LS_BIN="$ROOT/local-service/target/debug/huoke-local-service"
LS_RELEASE="$ROOT/local-service/target/release/huoke-local-service"
if [[ -x "$LS_BIN" || -x "$LS_RELEASE" ]]; then
  ok "local-service 二进制存在"
else
  skip "local-service 未构建 — npm run setup 会 cargo build"
fi

if [[ -d "$ROOT/frontend/node_modules" ]]; then
  ok "frontend 依赖已安装"
else
  skip "frontend node_modules 缺失"
fi
echo ""

echo "[2/5] local-service 健康"
if curl -fsS -m 5 "${BASE}/health" | grep -q '"ok":true'; then
  ok "GET /health"
else
  bad "GET /health 失败 — 运行: npm run dev"
  echo ""
  echo "结果: ${PASS} 通过, ${FAIL} 失败, ${SKIP} 跳过"
  exit 1
fi

echo "[3/5] 插件桥接"
STATUS_JSON="$(curl -fsS -m 5 "${BASE}/bridge/status" 2>/dev/null || echo '{}')"
CLIENTS="$(echo "$STATUS_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin).get('connected_clients',0))" 2>/dev/null || echo 0)"
if [[ "$CLIENTS" != "0" ]]; then
  ok "插件已连接 (clients=${CLIENTS})"
else
  skip "插件未连接 — 在 Chrome 加载 extension/dist 并打开抖音页"
fi
echo ""

echo "[4/5] REST API"
for path in /api/douyin/jobs /api/douyin/quota /api/douyin/outreach/tasks; do
  if curl -fsS -m 5 "${BASE}${path}" >/dev/null 2>&1; then
    ok "GET ${path}"
  else
    bad "GET ${path} 失败"
  fi
done
echo ""

echo "[5/5] 环境"
# shellcheck source=scripts/lib/common.sh
source "$ROOT/scripts/lib/common.sh"
if CHROME="$(find_chrome 2>/dev/null || true)" && [[ -n "$CHROME" ]]; then
  ok "系统 Chrome"
else
  skip "未安装系统 Chrome"
fi
echo ""

echo "=== 结果: ${PASS} 通过, ${FAIL} 失败, ${SKIP} 跳过 ==="
if [[ "$FAIL" -gt 0 ]]; then
  exit 1
fi
echo "基础链路正常。采集冒烟: bash scripts/test-douyin-collect.sh 装修"
exit 0
