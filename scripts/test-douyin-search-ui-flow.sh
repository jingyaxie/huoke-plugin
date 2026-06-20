#!/usr/bin/env bash
# 测试抖音搜索 UI 流程：点搜索框 → 逐字输入 → 提交 → 筛选一周内 → 逐个点击视频
# 使用日常 Chrome（保留登录态），不启动独立 profile
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PORT="${HUOKE_LOCAL_PORT:-18766}"
BASE="http://127.0.0.1:${PORT}"
KEYWORD="${1:-装修}"
MAX_VIDEOS="${2:-3}"
PAUSE="${HUOKE_TEST_PAUSE_SEC:-4}"
REPORT_DIR="${ROOT}/storage/test-reports"
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
REPORT="${REPORT_DIR}/douyin-search-ui-${TIMESTAMP}.log"

mkdir -p "$REPORT_DIR"
PASS=0
FAIL=0

log() { echo "[$(date '+%H:%M:%S')] $*" | tee -a "$REPORT"; }
pause() { sleep "${1:-$PAUSE}"; }

bridge_cmd() {
  local action="$1"
  local payload="${2:-{}}"
  local timeout_ms="${3:-120000}"
  curl -fsS -X POST "${BASE}/bridge/command" \
    -H 'Content-Type: application/json' \
    -d "{\"action\":\"${action}\",\"payload\":${payload},\"wait\":true,\"timeout_ms\":${timeout_ms}}"
}

run_step() {
  local id="$1" title="$2" action="$3" payload="${4:-{}}" timeout_ms="${5:-120000}" assert="${6:-}"
  log ""
  log "━━ ${id}: ${title}"
  pause 2
  local resp err
  if ! resp="$(bridge_cmd "$action" "$payload" "$timeout_ms")"; then
    log "✗ FAIL — 请求失败"
    FAIL=$((FAIL + 1))
    return 1
  fi
  echo "$resp" | tee -a "$REPORT" | jq . 2>/dev/null || echo "$resp" | tee -a "$REPORT"
  err="$(echo "$resp" | jq -r '.error // empty' 2>/dev/null || true)"
  if [[ -n "$err" ]]; then
    log "✗ FAIL — ${err}"
    FAIL=$((FAIL + 1))
    return 1
  fi
  if [[ "$(echo "$resp" | jq 'has("result")' 2>/dev/null)" != "true" ]]; then
    log "✗ FAIL — 无 result（插件可能未重载，请到 chrome://extensions 重新加载 Huoke）"
    FAIL=$((FAIL + 1))
    return 1
  fi
  if [[ -n "$assert" ]] && ! echo "$resp" | jq -e "$assert" >/dev/null 2>&1; then
    log "✗ FAIL — 断言失败: ${assert}"
    FAIL=$((FAIL + 1))
    return 1
  fi
  log "✓ PASS"
  PASS=$((PASS + 1))
  pause
}

log "=== 抖音搜索 UI 流程测试（日常 Chrome）==="
log "keyword=${KEYWORD} max_videos=${MAX_VIDEOS}"
log "报告: ${REPORT}"

if ! curl -fsS "${BASE}/health" | jq -e '.ok' >/dev/null; then
  log "✗ local-service 未运行"
  exit 1
fi

CLIENTS="$(curl -fsS "${BASE}/bridge/status" | jq -r '.connected_clients')"
if [[ "$CLIENTS" == "0" ]]; then
  log "✗ 插件未连接 — 请在日常 Chrome 加载 extension/dist"
  exit 1
fi

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
pause 2

DIAG="$(bridge_cmd "huoke.diag.tabs" "{}" 30000)"
PING_VER="$(echo "$DIAG" | jq -r '.result.tabs[] | select(.active==true) | .ping.version // empty' 2>/dev/null | head -1)"
if [[ -z "$PING_VER" ]]; then
  log "⚠ 插件 content script 是旧版（ping 无 version）"
  log "  必须: chrome://extensions → Huoke 获客助手 → 重新加载 → 刷新抖音页 F5"
  log "  dist 路径: ${ROOT}/extension/dist"
  open -a "Google Chrome" "chrome://extensions" 2>/dev/null || true
  exit 1
fi
log "content script version=${PING_VER}"

# 回到精选首页，便于点顶栏搜索框
run_step "S0" "打开精选首页" "douyin.url.navigate" '{"url":"https://www.douyin.com/jingxuan"}' 60000
pause 5

run_step "S1" "点击搜索框并逐字输入关键词" "douyin.search.type" "{\"keyword\":\"${KEYWORD}\"}" 180000 '.result.typed == true'
run_step "S2" "提交搜索" "douyin.search.submit" "{\"keyword\":\"${KEYWORD}\"}" 180000 '.result.navigated == true'
run_step "S3" "筛选一周内" "douyin.search.filter_time" '{"days":7}' 120000 '.result.applied == true'
run_step "S4" "列出搜索视频" "douyin.search.list_videos" '{"max":10}' 60000 '.result.count >= 1'
run_step "S5" "逐个点击视频（返回列表）" "douyin.search.browse_videos" "{\"max\":${MAX_VIDEOS},\"pause_ms\":2500}" 300000 '.result.browsed >= 1'

log ""
log "=== 汇总 PASS=${PASS} FAIL=${FAIL} ==="
log "报告: ${REPORT}"
[[ "$FAIL" -eq 0 ]]
