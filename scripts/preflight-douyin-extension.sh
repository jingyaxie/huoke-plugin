#!/usr/bin/env bash
# 快速检查：插件 WebSocket + 抖音 content script 是否可用
set -euo pipefail

PORT="${HUOKE_LOCAL_PORT:-18766}"
BASE="http://127.0.0.1:${PORT}"

echo "1) local-service health"
curl -fsS "${BASE}/health" | jq .

echo ""
echo "2) bridge clients"
STATUS="$(curl -fsS "${BASE}/bridge/status")"
echo "$STATUS" | jq .
CLIENTS="$(echo "$STATUS" | jq -r '.connected_clients')"
if [[ "$CLIENTS" == "0" ]]; then
  echo "✗ 插件未连接 WebSocket — 请加载 extension/dist"
  exit 1
fi

echo ""
echo "3) 聚焦抖音标签并探测 content script"
osascript <<'APPLESCRIPT' 2>/dev/null || true
tell application "Google Chrome"
  activate
  repeat with w in windows
    repeat with t in tabs of w
      if (URL of t as text) contains "douyin.com" then
        set index of w to 1
        set active tab index of w to (index of t)
        exit repeat
      end if
    end repeat
  end repeat
end tell
APPLESCRIPT
sleep 2

RESP="$(curl -fsS -X POST "${BASE}/bridge/command" \
  -H 'Content-Type: application/json' \
  -d '{"action":"get_page_info","payload":{},"wait":true,"timeout_ms":45000}')"
echo "$RESP" | jq .

if echo "$RESP" | jq -e '.result.platform == "douyin"' >/dev/null 2>&1; then
  PING_VER="$(curl -fsS -X POST "${BASE}/bridge/command" \
    -H 'Content-Type: application/json' \
    -d '{"action":"huoke.diag.tabs","payload":{},"wait":true,"timeout_ms":30000}' \
    | jq -r '.result.tabs[] | select(.active==true) | .ping.version // empty' 2>/dev/null | head -1)"
  if [[ -n "$PING_VER" ]]; then
    echo "✓ content script 正常 (version=${PING_VER})"
  else
    echo "✓ content script 正常（建议 chrome://extensions 重新加载插件以获取最新指令）"
  fi
  exit 0
fi

ERR="$(echo "$RESP" | jq -r '.error // "unknown"')"
echo "✗ content script 不可用: ${ERR}"
echo ""
echo "请执行："
echo "  1. chrome://extensions → Huoke → 重新加载（若刚 build 过必须做）"
echo "  2. 刷新抖音页面（F5）"
echo "  3. 再运行: bash scripts/preflight-douyin-extension.sh"
exit 1
