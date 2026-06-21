#!/usr/bin/env bash
# 真实 Chrome：验证搜索 API 截获（步骤 7/8，优先接口、DOM 兜底）
set -euo pipefail

PORT="${HUOKE_LOCAL_PORT:-18766}"
BASE="http://127.0.0.1:${PORT}"
KEYWORD="${1:-装修}"
REPORT_DIR="${HUOKE_TEST_REPORT_DIR:-storage/test-reports}"
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
REPORT="${REPORT_DIR}/search-api-capture-${TIMESTAMP}.log"

PASS=0
FAIL=0

mkdir -p "$REPORT_DIR"

log() {
  local line="[$(date '+%H:%M:%S')] $*"
  echo "$line" | tee -a "$REPORT"
}

ok()  { log "✓ $*"; PASS=$((PASS + 1)); }
bad() { log "✗ $*"; FAIL=$((FAIL + 1)); }

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

open_douyin_if_needed() {
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
    if (count of windows) = 0 then make new window
    tell window 1 to make new tab with properties {URL:"https://www.douyin.com/"}
  end if
end tell
APPLESCRIPT
  sleep 10
  focus_douyin_window
}

lab() {
  local action_id="$1"
  local payload="${2:-{}}"
  curl -fsS -X POST "${BASE}/api/plugin-lab/actions/${action_id}" \
    -H 'Content-Type: application/json' \
    -d "${payload}" \
    --max-time 120
}

assert_api_capture() {
  local step="$1"
  local resp="$2"

  echo "$resp" | tee -a "$REPORT" | jq . 2>/dev/null || echo "$resp" | tee -a "$REPORT"

  local err ok method count api_count has_raw
  err="$(echo "$resp" | jq -r '.error // empty' 2>/dev/null || true)"
  ok="$(echo "$resp" | jq -r '.ok // false' 2>/dev/null || echo false)"
  method="$(echo "$resp" | jq -r '.capture_method // .data.capture_method // empty' 2>/dev/null || true)"
  count="$(echo "$resp" | jq -r '.count // (.items | length) // 0' 2>/dev/null || echo 0)"
  api_count="$(echo "$resp" | jq -r '.api_count // 0' 2>/dev/null || echo 0)"

  if [[ -n "$err" || "$ok" != "true" ]]; then
    bad "${step} — 请求失败: ${err:-ok=false}"
    return 1
  fi

  if [[ "$count" -lt 1 ]]; then
    bad "${step} — 无搜索结果 (count=0)"
    return 1
  fi

  has_raw="$(echo "$resp" | jq '[.items[]? // .results[]?] | map(select(.source == "api" and (.raw_aweme != null))) | length' 2>/dev/null || echo 0)"

  if [[ "$method" == "api" ]]; then
    ok "${step} — capture_method=api, count=${count}, raw_aweme_items=${has_raw}"
    echo "$resp" | jq -r '.items[0] // .results[0] // {} | {source, click_by, aweme_id, title, author, has_raw_aweme: (.raw_aweme != null)}' | tee -a "$REPORT"
    return 0
  fi

  if [[ "$method" == "dom" ]]; then
    bad "${step} — 未截获 API，已降级 DOM (count=${count}, dom_count=${api_count})"
    echo "$resp" | jq -r '.message // empty' | tee -a "$REPORT"
    return 1
  fi

  bad "${step} — 未知 capture_method=${method:-none}, count=${count}"
  return 1
}

log "=== 搜索 API 截获验证（真实 Chrome）==="
log "BASE=${BASE} KEYWORD=${KEYWORD}"
log "报告: ${REPORT}"
log "提示: 若刚 npm run build，请先在 chrome://extensions 重新加载 Huoke 插件"

if ! curl -fsS "${BASE}/health" | jq -e '.ok == true' >/dev/null; then
  bad "local-service 不可用 (${BASE})"
  exit 1
fi

CLIENTS="$(curl -fsS "${BASE}/bridge/status" | jq -r '.connected_clients')"
log "connected_clients=${CLIENTS}"
if [[ "$CLIENTS" == "0" ]]; then
  bad "插件未连接 — 请加载 extension/dist 并确认角标 OK"
  exit 1
fi

open_douyin_if_needed

log ""
log "━━ 步骤 1: 打开抖音 + 定位搜索框"
focus_douyin_window
lab open_browser '{"platform":"douyin","reuse_existing":true,"reset_to_start":true}' | jq -c '{ok,error}' | tee -a "$REPORT"
sleep 3
focus_douyin_window
lab find_search_box '{"platform":"douyin"}' | jq -c '{ok,error}' | tee -a "$REPORT"
sleep 2

log ""
log "━━ 步骤 2: 输入关键词"
focus_douyin_window
lab input_search_text "{\"platform\":\"douyin\",\"search_text\":\"${KEYWORD}\"}" | jq -c '{ok,error}' | tee -a "$REPORT"
sleep 2

log ""
log "━━ 步骤 3: 点击搜索（步骤 7，应优先 API 截获）"
focus_douyin_window
STEP7="$(lab click_search_btn '{}')"
assert_api_capture "步骤7 click_search_btn" "$STEP7" || true
sleep 3

log ""
log "━━ 步骤 4: 获取搜索结果（步骤 8，应优先 API 截获）"
focus_douyin_window
STEP8="$(lab fetch_search_results '{"limit":20}')"
assert_api_capture "步骤8 fetch_search_results" "$STEP8" || true

log ""
log "━━ 步骤 5: 校验首条数据字段"
SAMPLE="$(echo "$STEP8" | jq -c '.items[0] // .results[0] // empty')"
if [[ -n "$SAMPLE" && "$SAMPLE" != "null" ]]; then
  echo "$SAMPLE" | jq '{source, click_by, aweme_id, title, author, url, raw_aweme_keys: (.raw_aweme | keys? // [])}' | tee -a "$REPORT"
  SOURCE="$(echo "$SAMPLE" | jq -r '.source // empty')"
  AWEME="$(echo "$SAMPLE" | jq -r '.aweme_id // empty')"
  if [[ "$SOURCE" == "api" && "$AWEME" =~ ^[0-9]{8,22}$ ]]; then
    ok "首条结果格式正确 (source=api, aweme_id=${AWEME})"
  else
    bad "首条结果格式异常 source=${SOURCE} aweme_id=${AWEME}"
  fi
else
  bad "无首条样例数据"
fi

log ""
log "=== 汇总 PASS=${PASS} FAIL=${FAIL} ==="
log "报告: ${REPORT}"

if [[ "$FAIL" -gt 0 ]]; then
  log ""
  log "排查建议:"
  log "  1. chrome://extensions 重新加载 Huoke 插件"
  log "  2. 保持抖音标签页为当前活动窗口"
  log "  3. 确认已登录抖音，搜索「${KEYWORD}」有结果"
  log "  4. 若 events=0，检查 injected network-hook 是否注入"
  exit 1
fi

log "搜索 API 截获验证通过。"
