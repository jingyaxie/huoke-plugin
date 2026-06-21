#!/usr/bin/env bash
# 无浏览器模拟测试：mock WebSocket 插件 + 复杂任务 + 实验室 API
# 用法: npm run simulate  或  bash scripts/simulate-tasks.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PORT="${HUOKE_SIM_PORT:-18767}"
BASE="http://127.0.0.1:${PORT}"
WS="ws://127.0.0.1:${PORT}/ws"
DATA_DIR="${ROOT}/storage/sim-test"
PASS=0
FAIL=0
LS_PID=""
MOCK_PID=""

cleanup() {
  [[ -n "$MOCK_PID" ]] && kill "$MOCK_PID" 2>/dev/null || true
  [[ -n "$LS_PID" ]] && kill "$LS_PID" 2>/dev/null || true
}
trap cleanup EXIT

ok()   { echo "  ✓ $*"; PASS=$((PASS + 1)); }
bad()  { echo "  ✗ $*" >&2; FAIL=$((FAIL + 1)); }

wait_http() {
  local path="$1" tries="${2:-30}"
  for _ in $(seq 1 "$tries"); do
    if curl -fsS -m 2 "${BASE}${path}" >/dev/null 2>&1; then
      return 0
    fi
    sleep 0.2
  done
  return 1
}

wait_bridge() {
  for _ in $(seq 1 40); do
    local n
    n="$(curl -fsS "${BASE}/bridge/status" | python3 -c "import sys,json; print(json.load(sys.stdin).get('connected_clients',0))")"
    if [[ "$n" != "0" ]]; then
      return 0
    fi
    sleep 0.2
  done
  return 1
}

wait_job() {
  local job_id="$1" want="${2:-completed}" max="${3:-120}"
  for _ in $(seq 1 "$max"); do
    local status
    status="$(curl -fsS "${BASE}/api/douyin/jobs/${job_id}" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status',''))")"
    if [[ "$status" == "$want" || "$status" == "failed" ]]; then
      echo "$status"
      return 0
    fi
    sleep 0.25
  done
  echo "timeout"
  return 1
}

wait_outreach_task() {
  local task_id="$1" max="${2:-120}"
  for _ in $(seq 1 "$max"); do
    local status pending
    status="$(curl -fsS "${BASE}/api/douyin/outreach/tasks/${task_id}" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status',''))")"
    pending="$(curl -fsS "${BASE}/api/douyin/outreach/tasks/${task_id}/items?limit=500" | python3 -c "import sys,json; d=json.load(sys.stdin); print(sum(1 for i in d.get('items',[]) if i.get('status') in ('pending','running')))")"
    if [[ "$status" == "completed" || "$status" == "failed" || "$status" == "paused" ]] && [[ "$pending" == "0" ]]; then
      echo "$status"
      return 0
    fi
    sleep 0.25
  done
  echo "timeout"
  return 1
}

lab_action() {
  local id="$1" payload="${2:-{}}"
  curl -fsS -X POST "${BASE}/api/plugin-lab/actions/${id}" \
    -H 'Content-Type: application/json' \
    -d "${payload}"
}

echo "=== Huoke 模拟测试（无浏览器）==="
echo "PORT=${PORT} DATA=${DATA_DIR}"
echo ""

echo "[1/6] 构建 mock-extension + local-service"
(cd "$ROOT/local-service" && cargo build --quiet --bin huoke-local-service --bin mock-extension)
ok "cargo build"

echo "[2/6] 启动 isolated local-service (HUOKE_SIMULATE=1)"
rm -rf "$DATA_DIR"
mkdir -p "$DATA_DIR"
HUOKE_SIMULATE=1 HUOKE_LOCAL_PORT="$PORT" HUOKE_DATA_DIR="$DATA_DIR" \
  "$ROOT/local-service/target/debug/huoke-local-service" >/tmp/huoke-sim-service.log 2>&1 &
LS_PID=$!
wait_http "/health" || { bad "local-service 未启动"; cat /tmp/huoke-sim-service.log; exit 1; }
ok "local-service /health"

HUOKE_LOCAL_PORT="$PORT" HUOKE_WS_URL="$WS" \
  "$ROOT/local-service/target/debug/mock-extension" >/tmp/huoke-sim-mock.log 2>&1 &
MOCK_PID=$!
wait_bridge || { bad "mock extension 未连接"; cat /tmp/huoke-sim-mock.log; exit 1; }
ok "mock extension connected"

echo ""
echo "[3/6] 插件实验室 API（全步骤）"
for action in open_browser find_search_box input_search_text click_filter_btn click_filter_overlay click_search_btn swipe_page fetch_search_results click_search_video click_comment_btn scroll_and_collect_comments reply_comment send_comment click_comment_avatar click_follow_btn click_dm_btn input_dm_text send_dm close_video_detail; do
  case "$action" in
    open_browser) payload='{"platform":"douyin","reuse_existing":true}' ;;
    find_search_box|input_search_text) payload='{"platform":"douyin","search_text":"装修"}' ;;
    click_filter_overlay) payload='{"days":7}' ;;
    input_search_text) payload='{"platform":"douyin","search_text":"北京 装修"}' ;;
    reply_comment) payload='{"reply_text":"模拟回复","comment_id":"sim_c1","comment_text":"模拟"}' ;;
    input_dm_text|send_dm) payload='{"dm_text":"模拟私信"}' ;;
    *) payload='{}' ;;
  esac
  resp="$(lab_action "$action" "$payload")"
  if echo "$resp" | python3 -c "import sys,json; d=json.load(sys.stdin); sys.exit(0 if d.get('ok') else 1)"; then
    ok "plugin-lab ${action}"
  else
    bad "plugin-lab ${action}: $resp"
  fi
done

echo ""
echo "[4/6] 复杂关键词采集 + 内联触达"
KW_JOB="$(curl -fsS -X POST "${BASE}/api/douyin/jobs" \
  -H 'Content-Type: application/json' \
  -d '{
    "keyword":"北京 装修",
    "name":"sim-keyword-complex",
    "limit_videos":3,
    "max_comments_per_video":20,
    "target_count":12,
    "region_name":"北京",
    "publish_time_range":"7d",
    "comment_days":7,
    "auto_start":true,
    "auto_outreach":true,
    "comment_presets":[{"id":"r1","content":"您好，想了解装修吗？"}],
    "dm_presets":[{"id":"d1","content":"私信了解详情"}],
    "interaction":{
      "comment_dm_percentage":40,
      "comment_dm_interval_seconds_min":1,
      "comment_dm_interval_seconds_max":2,
      "follow_per_day":3,
      "dm_per_day":3
    }
  }')"
KW_ID="$(echo "$KW_JOB" | python3 -c "import sys,json; print(json.load(sys.stdin)['job']['id'])")"
KW_STATUS="$(wait_job "$KW_ID" completed 160)"
VCOUNT="$(curl -fsS "${BASE}/api/douyin/jobs/${KW_ID}/videos" | python3 -c "import sys,json; print(len(json.load(sys.stdin).get('videos',[])))")"
CCOUNT="$(curl -fsS "${BASE}/api/douyin/jobs/${KW_ID}/comments?limit=200" | python3 -c "import sys,json; print(len(json.load(sys.stdin).get('comments',[])))")"
if [[ "$KW_STATUS" == "completed" && "$VCOUNT" -ge 1 && "$CCOUNT" -ge 1 ]]; then
  ok "keyword job ${KW_ID} status=${KW_STATUS} videos=${VCOUNT} comments=${CCOUNT}"
else
  bad "keyword job ${KW_ID} status=${KW_STATUS} videos=${VCOUNT} comments=${CCOUNT}"
  curl -fsS "${BASE}/api/douyin/jobs/${KW_ID}" | python3 -m json.tool || true
fi

echo ""
echo "[5/6] 手动任务 + 触达队列 + dry-run 回复"
MAN_JOB="$(curl -fsS -X POST "${BASE}/api/douyin/jobs" \
  -H 'Content-Type: application/json' \
  -d '{
    "job_type":"manual",
    "intent":"video_detail",
    "input_url":"https://www.douyin.com/video/7123456789012345678",
    "name":"sim-manual-video",
    "limit_videos":1,
    "max_comments_per_video":10,
    "target_count":5,
    "auto_start":true,
    "auto_outreach":false
  }')"
MAN_ID="$(echo "$MAN_JOB" | python3 -c "import sys,json; print(json.load(sys.stdin)['job']['id'])")"
MAN_STATUS="$(wait_job "$MAN_ID" completed 120)"
if [[ "$MAN_STATUS" == "completed" ]]; then
  ok "manual video job ${MAN_ID}"
else
  bad "manual job ${MAN_ID} status=${MAN_STATUS}"
fi

OUT_TASK="$(curl -fsS -X POST "${BASE}/api/douyin/outreach/tasks" \
  -H 'Content-Type: application/json' \
  -d "{\"source_job_id\":\"${KW_ID}\",\"name\":\"sim-outreach\",\"reply_text\":\"模拟触达\",\"max_items\":3,\"interval_ms\":500,\"daily_quota\":20}")"
TASK_ID="$(echo "$OUT_TASK" | python3 -c "import sys,json; print(json.load(sys.stdin)['task']['id'])")"
curl -fsS -X POST "${BASE}/api/douyin/outreach/tasks/${TASK_ID}/start" >/dev/null
OT_STATUS="$(wait_outreach_task "$TASK_ID" 160)"
DONE_ITEMS="$(curl -fsS "${BASE}/api/douyin/outreach/tasks/${TASK_ID}/items?limit=20" | python3 -c "import sys,json; print(sum(1 for i in json.load(sys.stdin).get('items',[]) if i.get('status')=='completed'))")"
if [[ "$OT_STATUS" == "completed" && "$DONE_ITEMS" -ge 1 ]]; then
  ok "outreach task ${TASK_ID} completed items=${DONE_ITEMS}"
else
  bad "outreach task ${TASK_ID} status=${OT_STATUS} done=${DONE_ITEMS}"
fi

SAMPLE="$(curl -fsS "${BASE}/api/douyin/jobs/${KW_ID}/comments?limit=1" | python3 -c "import sys,json; c=json.load(sys.stdin).get('comments',[]); print(json.dumps(c[0] if c else {}))")"
if [[ "$SAMPLE" != "{}" ]]; then
  AWEME="$(echo "$SAMPLE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('aweme_id',''))")"
  CID="$(echo "$SAMPLE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('comment_id',''))")"
  CTEXT="$(echo "$SAMPLE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('content',''))")"
  REPLY="$(curl -fsS -X POST "${BASE}/api/douyin/reply" -H 'Content-Type: application/json' \
    -d "{\"aweme_id\":\"${AWEME}\",\"comment_id\":\"${CID}\",\"comment_text\":\"${CTEXT}\",\"reply_text\":\"dry\",\"dry_run\":true}")"
  if echo "$REPLY" | python3 -c "import sys,json; sys.exit(0 if json.load(sys.stdin).get('ok') else 1)"; then
    ok "reply dry_run API"
  else
    bad "reply dry_run: $REPLY"
  fi
else
  bad "no sample comment for dry_run"
fi

echo ""
echo "[6/6] 汇总"
echo "PASS=${PASS} FAIL=${FAIL}"
if [[ "$FAIL" -gt 0 ]]; then
  echo "logs: /tmp/huoke-sim-service.log /tmp/huoke-sim-mock.log"
  exit 1
fi
echo "全部模拟测试通过（未打开真实浏览器）。"
exit 0
