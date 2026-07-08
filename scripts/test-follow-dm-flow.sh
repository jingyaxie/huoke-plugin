#!/usr/bin/env bash
# 关注/私信自动化冒烟（抖音 + 小红书）
# 默认只做最小 readiness，不发送真实私信。
# 前置: local-service 已启动 + Chrome 已加载 extension/dist 且平台页面已登录
# 用法:
#   JOB_ID=<采集任务ID> npm run test:follow-dm
#   SEND_REAL_DM=1 JOB_ID=<采集任务ID> npm run test:follow-dm
set -euo pipefail

PORT="${HUOKE_LOCAL_PORT:-18766}"
BASE="http://127.0.0.1:${PORT}"
JOB_ID="${JOB_ID:-${1:-}}"
DY_JOB_ID="${DY_JOB_ID:-}"
XHS_JOB_ID="${XHS_JOB_ID:-}"
DY_PROFILE_URL="${DY_PROFILE_URL:-}"
XHS_PROFILE_URL="${XHS_PROFILE_URL:-}"
DM_TEXT="${DM_TEXT:-hi}"
SEND_REAL_DM="${SEND_REAL_DM:-0}"
PASS=0
FAIL=0
SKIP=0

ok() { echo "  ✓ $*"; PASS=$((PASS + 1)); }
bad() { echo "  ✗ $*" >&2; FAIL=$((FAIL + 1)); }
skip() { echo "  - $*"; SKIP=$((SKIP + 1)); }

json_get() {
  python3 -c "import json,sys; d=json.load(sys.stdin); print(${1})"
}

request() {
  local method="$1" url="$2" body="${3:-}"
  if [[ -n "$body" ]]; then
    curl -fsS -X "$method" "$url" -H 'Content-Type: application/json' -d "$body"
  else
    curl -fsS -X "$method" "$url"
  fi
}

pick_latest_job_with_comments() {
  local platform="$1"
  request GET "${BASE}/api/douyin/jobs" | python3 -c '
import json
import sys

platform = sys.argv[1]
jobs = json.load(sys.stdin)
for job in jobs:
    if job.get("platform") == platform and int(job.get("comment_count") or 0) > 0:
        print(job["id"])
        break
' "$platform"
}

profile_url_from_job_comments() {
  local job_id="$1"
  request GET "${BASE}/api/douyin/jobs/${job_id}/comments?limit=20" | python3 -c '
import json
import sys

payload = json.load(sys.stdin)
for comment in payload.get("comments", []):
    url = (comment.get("profile_url") or comment.get("user_url") or "").strip()
    if url:
        print(url)
        break
'
}

resolve_profile_url() {
  local platform="$1" explicit_url="$2" explicit_job_id="$3"
  if [[ -n "$explicit_url" ]]; then
    echo "$explicit_url"
    return 0
  fi

  local job_id="$explicit_job_id"
  if [[ -z "$job_id" && -n "$JOB_ID" ]]; then
    job_id="$JOB_ID"
  fi
  if [[ -z "$job_id" ]]; then
    job_id="$(pick_latest_job_with_comments "$platform")"
  fi
  if [[ -z "$job_id" ]]; then
    return 1
  fi

  profile_url_from_job_comments "$job_id"
}

lab_action() {
  local action="$1" payload="${2:-{}}"
  request POST "${BASE}/api/plugin-lab/actions/${action}" "$payload"
}

readiness() {
  local action="$1"
  request GET "${BASE}/api/plugin-lab/actions/${action}/readiness"
}

bridge_cmd() {
  local action="$1" payload="${2:-{}}"
  request POST "${BASE}/bridge/command" \
    "{\"action\":\"${action}\",\"payload\":${payload},\"wait\":true,\"timeout_ms\":60000}"
}

check_service_and_extension() {
  echo "[1/3] 检查 local-service / 插件连接"
  if ! curl -fsS -m 3 "${BASE}/health" >/dev/null 2>&1; then
    bad "local-service 未响应 ${BASE}/health"
    exit 1
  fi
  ok "local-service /health"

  bridge_cmd "huoke.runtime.init" '{}' >/dev/null
  local status clients
  status="$(request GET "${BASE}/bridge/status")"
  clients="$(echo "$status" | json_get "d.get('extension_clients', d.get('connected_clients', 0))")"
  if [[ "$clients" == "0" ]]; then
    bad "插件未连接，请加载 extension/dist 并确保角标 OK"
    exit 1
  fi
  ok "extension connected (clients=${clients})"
}

open_platform_page() {
  local platform="$1" url="$2"
  local resp
  if ! resp="$(lab_action "open_browser" "{\"platform\":\"${platform}\",\"url\":\"${url}\",\"reuse_existing\":true}" 2>&1)"; then
    echo "$resp"
    return 1
  fi
  if ! echo "$resp" | python3 -c 'import json,sys; d=json.load(sys.stdin); sys.exit(0 if d.get("ok") is True else 1)'; then
    echo "$resp"
    return 1
  fi
}

expect_ready() {
  local label="$1" action="$2"
  local resp
  if ! resp="$(readiness "$action" 2>/dev/null)"; then
    bad "${label}: readiness 请求失败"
    return 1
  fi
  if echo "$resp" | python3 -c 'import json,sys; sys.exit(0 if json.load(sys.stdin).get("ok") is True else 1)'; then
    ok "${label}"
    return 0
  fi
  local msg
  msg="$(echo "$resp" | json_get "d.get('message') or d.get('error') or ''")"
  bad "${label}: ${msg}"
  return 1
}

expect_not_ready() {
  local label="$1" action="$2" expected="$3"
  local resp msg
  if ! resp="$(readiness "$action" 2>/dev/null)"; then
    bad "${label}: readiness 请求失败"
    return 1
  fi
  msg="$(echo "$resp" | json_get "d.get('message') or d.get('error') or ''")"
  if echo "$resp" | python3 -c 'import json,sys; sys.exit(0 if json.load(sys.stdin).get("ok") is False else 1)' \
    && [[ "$msg" == *"$expected"* ]]; then
    ok "${label}: ${msg}"
    return 0
  fi
  bad "${label}: 期望不可执行且包含「${expected}」，实际「${msg}」"
  return 1
}

run_douyin() {
  echo ""
  echo "[2/3] 抖音关注 / 私信"
  local profile_url
  profile_url="$(resolve_profile_url "douyin" "$DY_PROFILE_URL" "$DY_JOB_ID" || true)"
  if [[ -z "$profile_url" ]]; then
    bad "未找到抖音评论用户主页链接，请先完成采集任务，或传 JOB_ID/DY_JOB_ID/DY_PROFILE_URL"
    return 0
  fi
  echo "  profile_url=${profile_url}"
  if ! open_platform_page "douyin" "$profile_url"; then
    bad "打开抖音评论用户主页失败"
    return 0
  fi
  sleep 3

  expect_ready "抖音关注按钮就绪" "click_follow_btn" || return 0
  expect_ready "抖音私信按钮就绪" "click_dm_btn" || return 0

  if [[ "$SEND_REAL_DM" != "1" ]]; then
    skip "跳过真实私信发送（设置 SEND_REAL_DM=1 才会执行一次 click/input/send）"
    return 0
  fi

  lab_action "click_dm_btn" '{}' >/dev/null
  expect_ready "抖音私信输入框就绪" "input_dm_text" || return 0
  lab_action "input_dm_text" "{\"dm_text\":\"${DM_TEXT}\"}" >/dev/null
  local sent
  sent="$(lab_action "send_dm" "{\"dm_text\":\"${DM_TEXT}\"}")"
  if echo "$sent" | python3 -c 'import json,sys; sys.exit(0 if json.load(sys.stdin).get("ok") is True else 1)'; then
    ok "抖音私信发送"
  else
    local msg
    msg="$(echo "$sent" | json_get "d.get('message') or d.get('error') or ''")"
    bad "抖音私信发送失败: ${msg}"
  fi
}

run_xiaohongshu() {
  echo ""
  echo "[3/3] 小红书关注 / 私信能力边界"
  local profile_url
  profile_url="$(resolve_profile_url "xiaohongshu" "$XHS_PROFILE_URL" "$XHS_JOB_ID" || true)"
  if [[ -z "$profile_url" ]]; then
    skip "未找到小红书评论用户主页链接，跳过；可传 XHS_JOB_ID 或 XHS_PROFILE_URL"
    return 0
  fi
  echo "  profile_url=${profile_url}"
  if ! open_platform_page "xiaohongshu" "$profile_url"; then
    bad "打开小红书评论用户主页失败"
    return 0
  fi
  sleep 3

  expect_ready "小红书关注动作页面就绪" "click_follow_btn" || true
  expect_not_ready "小红书私信动作应被拦截" "click_dm_btn" "小红书不支持插件私信" || true
}

echo "=== 关注 / 私信自动化冒烟 ==="
echo "BASE=${BASE}"
echo "JOB_ID=${JOB_ID:-自动选择最近有评论的任务}"
echo "DY_PROFILE_URL=${DY_PROFILE_URL:-从抖音评论构建}"
echo "XHS_PROFILE_URL=${XHS_PROFILE_URL:-从小红书评论构建}"
echo "SEND_REAL_DM=${SEND_REAL_DM}"
echo ""

check_service_and_extension
run_douyin
run_xiaohongshu

echo ""
echo "========== 汇总 =========="
echo "PASS=${PASS}  FAIL=${FAIL}  SKIP=${SKIP}"
if [[ "$FAIL" -gt 0 ]]; then
  exit 1
fi
echo "关注/私信自动化冒烟通过。"
