#!/usr/bin/env bash
# 抖音 Chrome 插件分步测试（独立窗口，节奏较慢，避免触发风控）
set -uo pipefail

PORT="${HUOKE_LOCAL_PORT:-18766}"
BASE="http://127.0.0.1:${PORT}"
KEYWORD="${1:-装修}"
PAUSE="${HUOKE_TEST_PAUSE_SEC:-8}"
REPORT_DIR="${HUOKE_TEST_REPORT_DIR:-storage/test-reports}"
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
REPORT="${REPORT_DIR}/douyin-extension-cases-${TIMESTAMP}.log"

PASS=0
FAIL=0
SKIP=0

mkdir -p "$REPORT_DIR"

log() {
  local line="[$(date '+%H:%M:%S')] $*"
  echo "$line" | tee -a "$REPORT"
}

pause() {
  local sec="${1:-$PAUSE}"
  log "… 等待 ${sec}s"
  sleep "$sec"
}

focus_douyin_window() {
  osascript <<'APPLESCRIPT' 2>/dev/null || true
tell application "Google Chrome"
  activate
  set found to false
  repeat with w in windows
    repeat with t in tabs of w
      if (URL of t as text) contains "douyin.com" then
        set index of w to 1
        set active tab index of w to (index of t)
        set found to true
        exit repeat
      end if
    end repeat
    if found then exit repeat
  end repeat
end tell
APPLESCRIPT
  sleep 1
}

open_douyin_window() {
  log "在已有 Chrome 配置中打开抖音标签（保留登录态）"
  osascript <<'APPLESCRIPT' 2>/dev/null || true
tell application "Google Chrome"
  activate
  set found to false
  repeat with w in windows
    repeat with t in tabs of w
      if (URL of t as text) contains "douyin.com" then
        set index of w to 1
        set active tab index of w to (index of t)
        set found to true
        exit repeat
      end if
    end repeat
    if found then exit repeat
  end repeat
  if not found then
    if (count of windows) = 0 then
      make new window
    end if
    tell window 1
      make new tab with properties {URL:"https://www.douyin.com/"}
    end tell
  end if
end tell
APPLESCRIPT
  pause 12
  focus_douyin_window
}

bridge_cmd() {
  local action="$1"
  local payload="${2:-{}}"
  local timeout_ms="${3:-45000}"
  curl -fsS -X POST "${BASE}/bridge/command" \
    -H 'Content-Type: application/json' \
    -d "{\"action\":\"${action}\",\"payload\":${payload},\"wait\":true,\"timeout_ms\":${timeout_ms}}" 2>/dev/null
}

run_case() {
  local id="$1"
  local title="$2"
  local action="$3"
  local payload="${4:-{}}"
  local timeout_ms="${5:-45000}"

  log ""
  log "━━ CASE ${id}: ${title}"
  focus_douyin_window
  pause 3

  local resp
  if ! resp="$(bridge_cmd "$action" "$payload" "$timeout_ms")"; then
    log "✗ FAIL — curl 请求失败"
    FAIL=$((FAIL + 1))
    return 1
  fi

  echo "$resp" | tee -a "$REPORT" | jq . 2>/dev/null || echo "$resp" | tee -a "$REPORT"

  local err
  err="$(echo "$resp" | jq -r '.error // empty' 2>/dev/null || true)"
  if [[ -n "$err" ]]; then
    log "✗ FAIL — ${err}"
    FAIL=$((FAIL + 1))
    return 1
  fi

  local has_result
  has_result="$(echo "$resp" | jq 'has("result")' 2>/dev/null || echo false)"
  if [[ "$has_result" != "true" ]]; then
    log "✗ FAIL — 无 result（命令可能未送达 content script）"
    FAIL=$((FAIL + 1))
    return 1
  fi

  log "✓ PASS"
  PASS=$((PASS + 1))
  pause
}

assert_field() {
  local id="$1"
  local title="$2"
  local action="$3"
  local payload="$4"
  local jq_expr="$5"
  local timeout_ms="${6:-45000}"

  log ""
  log "━━ CASE ${id}: ${title}"
  focus_douyin_window
  pause 3

  local resp
  if ! resp="$(bridge_cmd "$action" "$payload" "$timeout_ms")"; then
    log "✗ FAIL — curl 请求失败"
    FAIL=$((FAIL + 1))
    return 1
  fi

  echo "$resp" | tee -a "$REPORT" | jq . 2>/dev/null || echo "$resp" | tee -a "$REPORT"

  if echo "$resp" | jq -e "$jq_expr" >/dev/null 2>&1; then
    log "✓ PASS"
    PASS=$((PASS + 1))
    pause
    return 0
  fi

  log "✗ FAIL — 断言未满足: ${jq_expr}"
  FAIL=$((FAIL + 1))
  pause
  return 1
}

log "=== 抖音插件分步测试 ==="
log "BASE=${BASE} KEYWORD=${KEYWORD} PAUSE=${PAUSE}s"
log "报告: ${REPORT}"

log ""
log "━━ 前置检查"
if ! curl -fsS "${BASE}/health" | jq -e '.ok == true' >/dev/null; then
  log "✗ local-service 不可用"
  exit 1
fi
CLIENTS="$(curl -fsS "${BASE}/bridge/status" | jq -r '.connected_clients')"
log "connected_clients=${CLIENTS}"
if [[ "$CLIENTS" == "0" ]]; then
  log "✗ 插件未连接，请先在 chrome://extensions 加载 extension/dist 并重新加载"
  exit 1
fi
log "⚠ 若刚执行过 npm run build，请先在 chrome://extensions 点「重新加载」Huoke 插件"
pause 3

open_douyin_window

# ── A. 基础探测 ──
assert_field "A1" "页面信息 get_page_info" "get_page_info" "{}" \
  '.result.platform == "douyin"'

assert_field "A2" "平台检测 platform.detect" "platform.detect" "{}" \
  '.result.platform == "douyin"'

assert_field "A3" "抖音页类型 douyin.page.detect" "douyin.page.detect" "{}" \
  '.result.pageKind != null'

# ── B. 网络 Hook ──
run_case "B1" "启用 network hook" "network.hook.enable" \
  '{"patterns":["/aweme/","/comment/","/search/"]}'

assert_field "B2" "Hook 状态应为 enabled" "network.hook.status" "{}" \
  '.result.enabled == true'

# ── C. 导航 ──
run_case "C1" "关键词搜索导航 douyin.search.navigate" "douyin.search.navigate" \
  "{\"keyword\":\"${KEYWORD}\"}" 60000
pause 10

assert_field "C2" "搜索页 pageKind=search" "douyin.page.detect" "{}" \
  '.result.pageKind == "search"'

run_case "C3" "重复搜索（应 already_on_page）" "douyin.search.navigate" \
  "{\"keyword\":\"${KEYWORD}\"}"

# ── D. 滚动（轻量）──
run_case "D1" "评论区滚动 2 轮（搜索页容错）" "douyin.comments.scroll" '{"rounds":2}' 60000

# ── E. 采集任务（小规模）──
log ""
log "━━ CASE E1: 创建关键词采集任务（limit_videos=2, max_comments=15）"
JOB_JSON="$(curl -fsS -X POST "${BASE}/api/douyin/jobs" \
  -H 'Content-Type: application/json' \
  -d "{\"keyword\":\"${KEYWORD}\",\"name\":\"分步测试-${TIMESTAMP}\",\"limit_videos\":2,\"max_comments_per_video\":15}")"
echo "$JOB_JSON" | tee -a "$REPORT" | jq .
JOB_ID="$(echo "$JOB_JSON" | jq -r '.job.id // empty')"
if [[ -z "$JOB_ID" ]]; then
  log "✗ FAIL — 创建任务失败"
  FAIL=$((FAIL + 1))
else
  log "✓ PASS job_id=${JOB_ID}"
  PASS=$((PASS + 1))
  pause 5

  log ""
  log "━━ CASE E2: 启动采集（需保持抖音窗口在前台）"
  focus_douyin_window
  START_JSON="$(curl -fsS -X POST "${BASE}/api/douyin/jobs/${JOB_ID}/start")"
  echo "$START_JSON" | tee -a "$REPORT" | jq .

  log "轮询采集进度（每 10s，最多 5 分钟）"
  COLLECT_OK=0
  for i in $(seq 1 30); do
    focus_douyin_window
    JOB="$(curl -fsS "${BASE}/api/douyin/jobs/${JOB_ID}")"
    STATUS="$(echo "$JOB" | jq -r '.status')"
    VIDEOS="$(echo "$JOB" | jq -r '.video_count')"
    COMMENTS="$(echo "$JOB" | jq -r '.comment_count')"
    log "  [${i}/30] status=${STATUS} videos=${VIDEOS} comments=${COMMENTS}"
    if [[ "$STATUS" == "completed" ]]; then
      COLLECT_OK=1
      echo "$JOB" | jq '{status, video_count, comment_count, error}' | tee -a "$REPORT"
      break
    fi
    if [[ "$STATUS" == "failed" ]]; then
      echo "$JOB" | jq '{status, error}' | tee -a "$REPORT"
      break
    fi
    sleep 10
  done

  if [[ "$COLLECT_OK" == "1" ]]; then
    log "✓ PASS 采集完成"
    PASS=$((PASS + 1))
  else
    log "✗ FAIL 采集未完成"
    FAIL=$((FAIL + 1))
  fi
  pause 8

  log ""
  log "━━ CASE E3: 查看视频/评论样例"
  VCOUNT="$(curl -fsS "${BASE}/api/douyin/jobs/${JOB_ID}/videos" | jq '.videos | length')"
  CCOUNT="$(curl -fsS "${BASE}/api/douyin/jobs/${JOB_ID}/comments?limit=5" | jq '.comments | length')"
  log "videos=${VCOUNT} comments(sample)=${CCOUNT}"
  if [[ "$VCOUNT" -gt 0 ]]; then
    log "✓ PASS 有视频数据"
    PASS=$((PASS + 1))
  else
    log "✗ FAIL 无视频"
    FAIL=$((FAIL + 1))
  fi
  pause 8
fi

# ── F. 回复 dry-run（有评论才测）──
if [[ -n "${JOB_ID:-}" ]]; then
  SAMPLE="$(curl -fsS "${BASE}/api/douyin/jobs/${JOB_ID}/comments?limit=1" | jq '.comments[0] // empty')"
  if [[ -n "$SAMPLE" && "$SAMPLE" != "null" ]]; then
    AWEME_ID="$(echo "$SAMPLE" | jq -r '.aweme_id')"
    COMMENT_ID="$(echo "$SAMPLE" | jq -r '.comment_id // .cid // empty')"
    COMMENT_TEXT="$(echo "$SAMPLE" | jq -r '.content // .text // empty' | head -c 40)"
    VIDEO_URL="https://www.douyin.com/video/${AWEME_ID}"
    log ""
    log "━━ CASE F1: 回复 dry_run（不真正发送）"
    focus_douyin_window
    REPLY_PAYLOAD="$(jq -nc \
      --arg url "$VIDEO_URL" \
      --arg aid "$AWEME_ID" \
      --arg cid "$COMMENT_ID" \
      --arg text "$COMMENT_TEXT" \
      '{video_url:$url, aweme_id:$aid, comment_id:$cid, comment_text:$text, reply_text:"[测试]感谢分享～", dry_run:true, scroll_rounds:2}')"
    REPLY_RESP="$(bridge_cmd "douyin.comment.reply" "$REPLY_PAYLOAD" 90000)"
    echo "$REPLY_RESP" | tee -a "$REPORT" | jq .
    if echo "$REPLY_RESP" | jq -e '.error == null' >/dev/null 2>&1; then
      log "✓ PASS dry_run 回复"
      PASS=$((PASS + 1))
    else
      log "✗ FAIL dry_run 回复"
      FAIL=$((FAIL + 1))
    fi
    pause 10
  else
    log "━━ CASE F1: 跳过 dry_run（无评论样例）"
    SKIP=$((SKIP + 1))
  fi
fi

# ── G. 清理 Hook ──
run_case "G1" "关闭 network hook" "network.hook.disable" "{}"

log ""
log "=== 测试汇总 ==="
log "PASS=${PASS} FAIL=${FAIL} SKIP=${SKIP}"
log "报告: ${REPORT}"
if [[ -n "${JOB_ID:-}" ]]; then
  log "采集任务 ID: ${JOB_ID}"
fi

if [[ "$FAIL" -gt 0 ]]; then
  exit 1
fi
