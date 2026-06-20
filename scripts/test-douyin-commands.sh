#!/usr/bin/env bash
# 抖音 bridge 指令测试。默认使用已登录的日常 Chrome；独立 profile 仅用于无登录态的 CI。
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
EXT="${ROOT}/extension/dist"
PORT="${HUOKE_LOCAL_PORT:-18766}"
BASE="http://127.0.0.1:${PORT}"
KEYWORD="${1:-装修}"
PAUSE="${HUOKE_TEST_PAUSE_SEC:-6}"
# existing = 日常 Chrome（保留抖音登录态）；isolated = 空 profile（无登录）
TEST_MODE="${HUOKE_TEST_MODE:-existing}"
PROFILE="${HUOKE_TEST_CHROME_PROFILE:-/tmp/huoke-ext-test-profile}"
CHROME="${HUOKE_CHROME_BIN:-/Applications/Google Chrome.app/Contents/MacOS/Google Chrome}"
REPORT_DIR="${ROOT}/storage/test-reports"
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
REPORT="${REPORT_DIR}/douyin-commands-${TIMESTAMP}.log"

PASS=0
FAIL=0
CHROME_PID=""

mkdir -p "$REPORT_DIR"

log() {
  echo "[$(date '+%H:%M:%S')] $*" | tee -a "$REPORT"
}

pause() {
  sleep "${1:-$PAUSE}"
}

focus_douyin_tab() {
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
}

cleanup() {
  if [[ -n "$CHROME_PID" ]] && kill -0 "$CHROME_PID" 2>/dev/null; then
    log "关闭测试 Chrome (pid=${CHROME_PID})"
    kill "$CHROME_PID" 2>/dev/null || true
    sleep 1
  fi
}
trap cleanup EXIT

bridge_cmd() {
  local action="$1"
  local payload="${2:-{}}"
  local timeout_ms="${3:-45000}"
  curl -fsS -X POST "${BASE}/bridge/command" \
    -H 'Content-Type: application/json' \
    -d "{\"action\":\"${action}\",\"payload\":${payload},\"wait\":true,\"timeout_ms\":${timeout_ms}}"
}

run_case() {
  local id="$1"
  local title="$2"
  local action="$3"
  local payload="${4:-{}}"
  local timeout_ms="${5:-45000}"
  local assert="${6:-}"

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
    log "✗ FAIL — 无 result"
    FAIL=$((FAIL + 1))
    return 1
  fi
  if [[ -n "$assert" ]] && ! echo "$resp" | jq -e "$assert" >/dev/null 2>&1; then
    log "✗ FAIL — 断言: ${assert}"
    FAIL=$((FAIL + 1))
    return 1
  fi
  log "✓ PASS"
  PASS=$((PASS + 1))
  pause
}

log "=== 抖音指令测试（mode=${TEST_MODE}）==="
log "EXT=${EXT}"
log "报告: ${REPORT}"

if [[ ! -f "${EXT}/manifest.json" ]]; then
  log "✗ extension/dist 不存在，请先: cd extension && npm run build"
  exit 1
fi

if ! curl -fsS "${BASE}/health" | jq -e '.ok' >/dev/null; then
  log "✗ local-service 未运行（端口 ${PORT}）"
  exit 1
fi

if [[ "$TEST_MODE" == "isolated" ]]; then
  mkdir -p "$PROFILE"
  log "启动独立 Chrome（无登录态，仅适合无账号场景）"
  "$CHROME" \
    --user-data-dir="$PROFILE" \
    --disable-extensions-except="$EXT" \
    --load-extension="$EXT" \
    --no-first-run \
    --no-default-browser-check \
    "https://www.douyin.com/" >/dev/null 2>&1 &
  CHROME_PID=$!
  log "Chrome pid=${CHROME_PID}，等待页面与插件连接…"
  pause 15
else
  log "使用日常 Chrome（保留抖音登录态）"
  log "前提：chrome://extensions 已加载 ${EXT}，且角标显示 OK"
  focus_douyin_tab
  pause 3
fi

CLIENTS="$(curl -fsS "${BASE}/bridge/status" | jq -r '.connected_clients')"
log "connected_clients=${CLIENTS}"
if [[ "$CLIENTS" == "0" ]]; then
  log "✗ 插件未连接 WebSocket"
  if [[ "$TEST_MODE" != "isolated" ]]; then
    log "请在日常 Chrome 打开 chrome://extensions → 加载 extension/dist"
  fi
  exit 1
fi

focus_douyin_tab
pause 2

DIAG="$(bridge_cmd "huoke.diag.tabs" "{}" 30000)"
echo "$DIAG" | tee -a "$REPORT" | jq '.result.tabs[] | select(.active==true) | {url,ping}' 2>/dev/null || true
PING_VER="$(echo "$DIAG" | jq -r '.result.tabs[] | select(.active==true) | .ping.version // empty' 2>/dev/null | head -1)"
if [[ -z "$PING_VER" ]]; then
  log "⚠ content script 可能是旧版（ping 无 version）"
  log "  请执行: chrome://extensions → Huoke → 重新加载，然后刷新抖音页（F5）"
fi

# ── 基础 ──
run_case "A1" "get_page_info" "get_page_info" "{}" 30000 '.result.platform == "douyin"'
run_case "A2" "platform.detect" "platform.detect" "{}" 30000 '.result.platform == "douyin"'
run_case "A3" "douyin.page.detect" "douyin.page.detect" "{}" 30000 '.result.pageKind != null'

# ── Hook ──
run_case "B1" "network.hook.enable" "network.hook.enable" '{"patterns":["/aweme/","/comment/","/search/"]}' 30000
run_case "B2" "network.hook.status" "network.hook.status" "{}" 30000 '.result.enabled == true'

# ── 导航 ──
run_case "C1" "douyin.search.navigate" "douyin.search.navigate" "{\"keyword\":\"${KEYWORD}\"}" 60000
pause 8
run_case "C2" "搜索页检测" "douyin.page.detect" "{}" 30000 '.result.pageKind == "search"'
run_case "C3" "重复搜索 already_on_page" "douyin.search.navigate" "{\"keyword\":\"${KEYWORD}\"}" 30000 '.result.navigated == false'
run_case "C4" "点击搜索结果第一个视频" "douyin.search.open_video" '{"index":0}' 90000 '.result.clicked == true'

# ── 滚动 ──
run_case "D1" "douyin.comments.scroll x2" "douyin.comments.scroll" '{"rounds":2}' 60000 '.result.rounds == 2'

# ── 采集 API（小规模）──
log ""
log "━━ E1: 创建采集任务"
JOB_JSON="$(curl -fsS -X POST "${BASE}/api/douyin/jobs" \
  -H 'Content-Type: application/json' \
  -d "{\"keyword\":\"${KEYWORD}\",\"name\":\"指令测试-${TIMESTAMP}\",\"limit_videos\":2,\"max_comments_per_video\":10}")"
echo "$JOB_JSON" | tee -a "$REPORT" | jq .
JOB_ID="$(echo "$JOB_JSON" | jq -r '.job.id // empty')"
if [[ -z "$JOB_ID" ]]; then
  log "✗ FAIL 创建任务"
  FAIL=$((FAIL + 1))
else
  log "✓ PASS job_id=${JOB_ID}"
  PASS=$((PASS + 1))
  pause 4
  log "━━ E2: 启动采集"
  curl -fsS -X POST "${BASE}/api/douyin/jobs/${JOB_ID}/start" | tee -a "$REPORT" | jq .
  for i in $(seq 1 24); do
    JOB="$(curl -fsS "${BASE}/api/douyin/jobs/${JOB_ID}")"
    ST="$(echo "$JOB" | jq -r '.status')"
    V="$(echo "$JOB" | jq -r '.video_count')"
    C="$(echo "$JOB" | jq -r '.comment_count')"
    log "  [${i}/24] status=${ST} videos=${V} comments=${C}"
    [[ "$ST" == "completed" || "$ST" == "failed" ]] && break
    pause 10
  done
  if [[ "$ST" == "completed" && "$V" -gt 0 ]]; then
    log "✓ PASS 采集"
    PASS=$((PASS + 1))
  else
    log "✗ FAIL 采集 status=${ST} videos=${V}"
    FAIL=$((FAIL + 1))
  fi
fi

# ── 清理 ──
run_case "G1" "network.hook.disable" "network.hook.disable" "{}" 30000 '.result.enabled == false'

log ""
log "=== 汇总 PASS=${PASS} FAIL=${FAIL} ==="
log "报告: ${REPORT}"
[[ -n "${JOB_ID:-}" ]] && log "job_id=${JOB_ID}"

[[ "$FAIL" -eq 0 ]]
