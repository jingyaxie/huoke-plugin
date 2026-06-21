#!/usr/bin/env bash
# 详细模拟测试：Bridge 通信 + 全 API + 任务编排 + 日志审计（无浏览器）
# 用法: bash scripts/simulate-detailed.sh
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
SERVICE_LOG="/tmp/huoke-sim-service.log"
MOCK_LOG="/tmp/huoke-sim-mock.log"

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
    curl -fsS -m 2 "${BASE}${path}" >/dev/null 2>&1 && return 0
    sleep 0.2
  done
  return 1
}

wait_bridge() {
  for _ in $(seq 1 40); do
    local n
    n="$(curl -fsS "${BASE}/bridge/status" | python3 -c "import sys,json; print(json.load(sys.stdin).get('connected_clients',0))")"
    [[ "$n" != "0" ]] && return 0
    sleep 0.2
  done
  return 1
}

wait_job() {
  local job_id="$1" want="${2:-completed}" max="${3:-160}"
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
  local task_id="$1" max="${2:-160}"
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
  local id="$1" payload="$2"
  [[ -z "$payload" ]] && payload='{}'
  curl -fsS -X POST "${BASE}/api/plugin-lab/actions/${id}" \
    -H 'Content-Type: application/json' \
    -d "${payload}"
}

bridge_cmd() {
  local action="$1" payload="$2" do_wait="${3:-true}"
  [[ -z "$payload" ]] && payload='{}'
  python3 -c 'import json,sys,urllib.request
action,payload_raw,do_wait,base=sys.argv[1],sys.argv[2],sys.argv[3],sys.argv[4]
payload=json.loads(payload_raw)
body=json.dumps({"action":action,"payload":payload,"wait":do_wait=="true","timeout_ms":15000}).encode()
req=urllib.request.Request(base+"/bridge/command",data=body,headers={"Content-Type":"application/json"})
print(urllib.request.urlopen(req,timeout=20).read().decode())' \
    "$action" "$payload" "$do_wait" "$BASE"
}

check_json() {
  local desc="$1" body="$2" py="$3"
  if echo "$body" | python3 -c "$py" 2>/dev/null; then
    ok "$desc"
  else
    bad "$desc"
    echo "    response: $(echo "$body" | head -c 300)" >&2
  fi
}

echo "=== Huoke 详细模拟测试（无浏览器）==="
echo "PORT=${PORT}  DATA=${DATA_DIR}"
echo ""

# ── 1. 构建 & 启动 ─────────────────────────────────────────────
echo "[1/8] 构建并启动 isolated local-service + mock extension"
(cd "$ROOT/local-service" && cargo build --quiet --bin huoke-local-service --bin mock-extension)
ok "cargo build"

rm -rf "$DATA_DIR"
mkdir -p "$DATA_DIR"
: > "$SERVICE_LOG"
: > "$MOCK_LOG"

HUOKE_SIMULATE=1 HUOKE_LOCAL_PORT="$PORT" HUOKE_DATA_DIR="$DATA_DIR" \
  "$ROOT/local-service/target/debug/huoke-local-service" >"$SERVICE_LOG" 2>&1 &
LS_PID=$!
wait_http "/health" || { bad "local-service 未启动"; cat "$SERVICE_LOG"; exit 1; }
ok "local-service 已监听 ${PORT}"

HUOKE_LOCAL_PORT="$PORT" HUOKE_WS_URL="$WS" \
  "$ROOT/local-service/target/debug/mock-extension" >"$MOCK_LOG" 2>&1 &
MOCK_PID=$!
wait_bridge || { bad "mock extension 未连接 WS"; cat "$MOCK_LOG"; exit 1; }
ok "mock extension WebSocket 已连接"

# ── 2. 基础服务 & Bridge 通信 ───────────────────────────────────
echo ""
echo "[2/8] 基础服务 & Bridge 插件通信"

HEALTH="$(curl -fsS "${BASE}/health")"
check_json "GET /health ok + version" "$HEALTH" \
  "import sys,json; d=json.load(sys.stdin); assert d.get('ok') and d.get('service')=='huoke-local-service' and d.get('version')"

BRIDGE="$(curl -fsS "${BASE}/bridge/status")"
check_json "GET /bridge/status connected_clients>=1" "$BRIDGE" \
  "import sys,json; d=json.load(sys.stdin); assert d.get('connected_clients',0)>=1 and d.get('ws_path')=='/ws'"

PING="$(curl -fsS -X POST "${BASE}/bridge/ping")"
check_json "POST /bridge/ping queued" "$PING" \
  "import sys,json; d=json.load(sys.stdin); assert d.get('queued') is True"

HOOK="$(bridge_cmd "network.hook.enable" '{"patterns":["/aweme/","/comment/"]}' true)"
check_json "bridge network.hook.enable → result.enabled" "$HOOK" \
  "import sys,json; d=json.load(sys.stdin); r=d.get('result') or {}; assert d.get('error') is None and (r.get('enabled') is True or r.get('data',{}).get('enabled') is True or r.get('simulated') is True)"

HOOK_ST="$(bridge_cmd "network.hook.status" '{}' true)"
check_json "bridge network.hook.status 有响应" "$HOOK_ST" \
  "import sys,json; d=json.load(sys.stdin); assert d.get('result') is not None"

SWIPE="$(bridge_cmd "plugin_lab.swipe_page" '{"direction":"down","distance":900}' true)"
check_json "bridge plugin_lab.swipe_page round-trip" "$SWIPE" \
  "import sys,json; d=json.load(sys.stdin); r=d.get('result') or {}; assert d.get('error') is None and (r.get('ok') is True or r.get('data',{}).get('ok') is True or r.get('simulated') is True)"

# fire-and-forget（不等待）
BCAST="$(bridge_cmd "ping" '{}' false)"
check_json "bridge broadcast ping (wait=false)" "$BCAST" \
  "import sys,json; d=json.load(sys.stdin); assert d.get('queued') is True and d.get('result') is None"

# ── 3. 插件实验室 API 深度验证 ──────────────────────────────────
echo ""
echo "[3/8] 插件实验室 API（20 步骤 + 响应结构）"

LAB_ST="$(curl -fsS "${BASE}/api/plugin-lab/status")"
check_json "GET /api/plugin-lab/status 20 actions" "$LAB_ST" \
  "import sys,json; d=json.load(sys.stdin); assert d.get('ok') and len(d.get('supported_actions',[]))==20 and d.get('connected_clients',0)>=1"

INVALID="$(curl -sS -o /tmp/sim-invalid.json -w '%{http_code}' -X POST "${BASE}/api/plugin-lab/actions/not_exist" -H 'Content-Type: application/json' -d '{}')"
if [[ "$INVALID" == "404" ]]; then
  ok "plugin-lab 未知 action 返回 404"
else
  bad "plugin-lab 未知 action 应 404，实际 ${INVALID}"
fi

for action in open_browser find_search_box input_search_text click_filter_btn click_filter_overlay click_search_btn swipe_page fetch_search_results click_search_video click_comment_btn scroll_and_collect_comments reply_comment send_comment click_comment_avatar click_follow_btn click_dm_btn input_dm_text send_dm close_video_detail; do
  case "$action" in
    open_browser) payload='{"platform":"douyin","reuse_existing":true}' ;;
    find_search_box) payload='{"platform":"douyin"}' ;;
    input_search_text) payload='{"platform":"douyin","search_text":"北京 装修"}' ;;
    click_filter_overlay) payload='{"days":7}' ;;
    reply_comment) payload='{"reply_text":"模拟回复","comment_id":"sim_c1","comment_text":"模拟"}' ;;
    input_dm_text|send_dm) payload='{"dm_text":"模拟私信"}' ;;
    *) payload='{}' ;;
  esac
  resp="$(lab_action "$action" "$payload")"
  check_json "plugin-lab POST ${action}" "$resp" \
    "import sys,json; d=json.load(sys.stdin); assert d.get('ok') and d.get('action')=='${action}' and d.get('data') is not None"
done

# ── 4. 关键词任务（auto_start + 内联触达）────────────────────────
echo ""
echo "[4/8] 复杂关键词采集任务 + 内联触达"

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
check_json "POST /api/douyin/jobs keyword 返回 job+started" "$KW_JOB" \
  "import sys,json; d=json.load(sys.stdin); assert d.get('job',{}).get('id') and d.get('started') is True"

KW_ID="$(echo "$KW_JOB" | python3 -c "import sys,json; print(json.load(sys.stdin)['job']['id'])")"
KW_STATUS="$(wait_job "$KW_ID" completed 160)"
VCOUNT="$(curl -fsS "${BASE}/api/douyin/jobs/${KW_ID}/videos" | python3 -c "import sys,json; print(len(json.load(sys.stdin).get('videos',[])))")"
CCOUNT="$(curl -fsS "${BASE}/api/douyin/jobs/${KW_ID}/comments?limit=200" | python3 -c "import sys,json; print(len(json.load(sys.stdin).get('comments',[])))")"

if [[ "$KW_STATUS" == "completed" && "$VCOUNT" -ge 3 && "$CCOUNT" -ge 12 ]]; then
  ok "keyword job ${KW_ID} completed videos=${VCOUNT} comments=${CCOUNT}"
else
  bad "keyword job ${KW_ID} status=${KW_STATUS} videos=${VCOUNT} comments=${CCOUNT}"
fi

VID_JSON="$(curl -fsS "${BASE}/api/douyin/jobs/${KW_ID}/videos")"
check_json "GET videos 含 aweme_id+video_url" "$VID_JSON" \
  "import sys,json; v=json.load(sys.stdin).get('videos',[]); assert len(v)>=1 and all(x.get('aweme_id') and x.get('video_url') for x in v)"

CMT_JSON="$(curl -fsS "${BASE}/api/douyin/jobs/${KW_ID}/comments?limit=5")"
check_json "GET comments limit=5 生效" "$CMT_JSON" \
  "import sys,json; c=json.load(sys.stdin).get('comments',[]); assert 1<=len(c)<=5 and all(x.get('comment_id') and x.get('content') for x in c)"

JOB_DETAIL="$(curl -fsS "${BASE}/api/douyin/jobs/${KW_ID}")"
check_json "GET job detail status=completed + config" "$JOB_DETAIL" \
  "import sys,json; j=json.load(sys.stdin); assert j.get('status')=='completed' and j.get('config',{}).get('auto_outreach') is True"

# ── 5. 手动 start 任务（验证 POST /jobs/:id/start）──────────────
echo ""
echo "[5/8] 手动 start 关键词任务（auto_start=false）"

PEND_JOB="$(curl -fsS -X POST "${BASE}/api/douyin/jobs" \
  -H 'Content-Type: application/json' \
  -d '{
    "keyword":"北京 团餐",
    "name":"sim-manual-start",
    "limit_videos":2,
    "max_comments_per_video":10,
    "target_count":5,
    "region_name":"北京",
    "comment_days":7,
    "auto_start":false,
    "auto_outreach":false
  }')"
PEND_ID="$(echo "$PEND_JOB" | python3 -c "import sys,json; print(json.load(sys.stdin)['job']['id'])")"
PEND_ST="$(curl -fsS "${BASE}/api/douyin/jobs/${PEND_ID}" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status',''))")"
if [[ "$PEND_ST" == "pending" || "$PEND_ST" == "running" ]]; then
  ok "pending job ${PEND_ID} status=${PEND_ST}"
else
  bad "pending job 期望 pending，实际 ${PEND_ST}"
fi

START_RESP="$(curl -fsS -X POST "${BASE}/api/douyin/jobs/${PEND_ID}/start")"
check_json "POST /jobs/:id/start → running" "$START_RESP" \
  "import sys,json; d=json.load(sys.stdin); assert d.get('status') in ('running','completed')"

PEND_FINAL="$(wait_job "$PEND_ID" completed 120)"
if [[ "$PEND_FINAL" == "completed" ]]; then
  ok "manual-start job ${PEND_ID} completed"
else
  bad "manual-start job ${PEND_ID} status=${PEND_FINAL}"
fi

# ── 6. 手动视频任务 ─────────────────────────────────────────────
echo ""
echo "[6/8] 手动视频任务（video_detail）"

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
MAN_C="$(curl -fsS "${BASE}/api/douyin/jobs/${MAN_ID}/comments?limit=50" | python3 -c "import sys,json; print(len(json.load(sys.stdin).get('comments',[])))")"
if [[ "$MAN_STATUS" == "completed" && "$MAN_C" -ge 5 ]]; then
  ok "manual video job ${MAN_ID} comments=${MAN_C}"
else
  bad "manual video job ${MAN_ID} status=${MAN_STATUS} comments=${MAN_C}"
fi

# 错误路径：manual 缺 input_url → 400
BAD_CODE="$(curl -sS -o /dev/null -w '%{http_code}' -X POST "${BASE}/api/douyin/jobs" \
  -H 'Content-Type: application/json' \
  -d '{"job_type":"manual","auto_start":false}')"
if [[ "$BAD_CODE" == "400" ]]; then
  ok "manual job 缺 input_url 返回 400"
else
  bad "manual job 缺 input_url 应 400，实际 ${BAD_CODE}"
fi

# ── 7. 触达 / 回复 / 查询 API ───────────────────────────────────
echo ""
echo "[7/8] 触达队列 + 回复 API + 统计查询"

QUOTA="$(curl -fsS "${BASE}/api/douyin/quota")"
check_json "GET /api/douyin/quota 结构" "$QUOTA" \
  "import sys,json; d=json.load(sys.stdin); assert 'reply_count' in d and 'daily_limit' in d and 'remaining' in d"

STATS="$(curl -fsS "${BASE}/api/douyin/interaction/stats")"
check_json "GET /api/douyin/interaction/stats" "$STATS" \
  "import sys,json; d=json.load(sys.stdin); assert 'reply' in d and 'dm_used_today' in d"

JOBS_LIST="$(curl -fsS "${BASE}/api/douyin/jobs")"
check_json "GET /api/douyin/jobs 列表>=3" "$JOBS_LIST" \
  "import sys,json; assert len(json.load(sys.stdin))>=3"

OUT_TASK="$(curl -fsS -X POST "${BASE}/api/douyin/outreach/tasks" \
  -H 'Content-Type: application/json' \
  -d "{\"source_job_id\":\"${KW_ID}\",\"name\":\"sim-outreach\",\"reply_text\":\"模拟触达\",\"max_items\":3,\"interval_ms\":300,\"daily_quota\":20}")"
TASK_ID="$(echo "$OUT_TASK" | python3 -c "import sys,json; print(json.load(sys.stdin)['task']['id'])")"
INSERTED="$(echo "$OUT_TASK" | python3 -c "import sys,json; print(json.load(sys.stdin).get('inserted_items',0))")"
if [[ "$INSERTED" -ge 1 ]]; then
  ok "POST outreach/tasks inserted_items=${INSERTED}"
else
  bad "POST outreach/tasks inserted_items=${INSERTED}"
fi

curl -fsS -X POST "${BASE}/api/douyin/outreach/tasks/${TASK_ID}/start" >/dev/null
OT_STATUS="$(wait_outreach_task "$TASK_ID" 160)"
ITEMS="$(curl -fsS "${BASE}/api/douyin/outreach/tasks/${TASK_ID}/items?limit=20")"
DONE_ITEMS="$(echo "$ITEMS" | python3 -c "import sys,json; print(sum(1 for i in json.load(sys.stdin).get('items',[]) if i.get('status')=='completed'))")"
if [[ "$OT_STATUS" == "completed" && "$DONE_ITEMS" -ge 1 ]]; then
  ok "outreach task ${TASK_ID} completed done=${DONE_ITEMS}"
else
  bad "outreach task ${TASK_ID} status=${OT_STATUS} done=${DONE_ITEMS}"
fi

TASK_DETAIL="$(curl -fsS "${BASE}/api/douyin/outreach/tasks/${TASK_ID}")"
check_json "GET outreach task detail" "$TASK_DETAIL" \
  "import sys,json; t=json.load(sys.stdin); assert t.get('id')=='${TASK_ID}' and t.get('status') in ('completed','paused','failed')"

TASKS_LIST="$(curl -fsS "${BASE}/api/douyin/outreach/tasks")"
check_json "GET outreach tasks 列表" "$TASKS_LIST" \
  "import sys,json; assert len(json.load(sys.stdin))>=1"

# dry-run 回复
SAMPLE="$(curl -fsS "${BASE}/api/douyin/jobs/${KW_ID}/comments?limit=1" | python3 -c "import sys,json; c=json.load(sys.stdin).get('comments',[]); print(json.dumps(c[0] if c else {}))")"
if [[ "$SAMPLE" != "{}" ]]; then
  AWEME="$(echo "$SAMPLE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('aweme_id',''))")"
  CID="$(echo "$SAMPLE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('comment_id',''))")"
  CTEXT="$(echo "$SAMPLE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('content',''))")"
  REPLY_DRY="$(curl -fsS -X POST "${BASE}/api/douyin/reply" -H 'Content-Type: application/json' \
    -d "{\"aweme_id\":\"${AWEME}\",\"comment_id\":\"${CID}\",\"comment_text\":\"${CTEXT}\",\"reply_text\":\"dry\",\"dry_run\":true}")"
  check_json "POST /api/douyin/reply dry_run" "$REPLY_DRY" \
    "import sys,json; d=json.load(sys.stdin); assert d.get('ok') is True"

  # 真实回复（mock 插件模拟执行）
  REPLY_REAL="$(curl -fsS -X POST "${BASE}/api/douyin/reply" -H 'Content-Type: application/json' \
    -d "{\"aweme_id\":\"${AWEME}\",\"comment_id\":\"${CID}\",\"comment_text\":\"${CTEXT}\",\"reply_text\":\"模拟真实回复\",\"dry_run\":false}")"
  check_json "POST /api/douyin/reply 真实执行（mock）" "$REPLY_REAL" \
    "import sys,json; d=json.load(sys.stdin); assert d.get('ok') is True"
else
  bad "无 sample comment 用于 reply 测试"
fi

# ── 8. 日志审计：插件通信链路 ───────────────────────────────────
echo ""
echo "[8/8] 日志审计（WebSocket 命令/事件链路）"

MOCK_CONNECTED=$(grep -c "mock extension connected" "$MOCK_LOG" 2>/dev/null || echo 0)
MOCK_HANDLES=$(grep -c "mock handle" "$MOCK_LOG" 2>/dev/null || echo 0)
SVC_CAPTURED=$(grep -c "network.captured" "$SERVICE_LOG" 2>/dev/null || echo 0)
SVC_RESULTS=$(grep -c "result plugin_lab" "$SERVICE_LOG" 2>/dev/null || echo 0)
SVC_STORED=$(grep -c "stored.*comments" "$SERVICE_LOG" 2>/dev/null || echo 0)

if [[ "$MOCK_CONNECTED" -ge 1 ]]; then
  ok "mock 日志: WebSocket 连接成功"
else
  bad "mock 日志: 未见 bridge 连接"
fi

if [[ "$MOCK_HANDLES" -ge 30 ]]; then
  ok "mock 日志: 收到 ${MOCK_HANDLES} 条 plugin 命令"
else
  bad "mock 日志: 命令数不足 (${MOCK_HANDLES})"
fi

if [[ "$SVC_CAPTURED" -ge 5 ]]; then
  ok "service 日志: ${SVC_CAPTURED} 次 network.captured 事件"
else
  bad "service 日志: network.captured 不足 (${SVC_CAPTURED})"
fi

if [[ "$SVC_RESULTS" -ge 20 ]]; then
  ok "service 日志: ${SVC_RESULTS} 次 plugin_lab 命令回执"
else
  bad "service 日志: plugin_lab 回执不足 (${SVC_RESULTS})"
fi

if [[ "$SVC_STORED" -ge 3 ]]; then
  ok "service 日志: ${SVC_STORED} 次评论入库"
else
  bad "service 日志: 评论入库不足 (${SVC_STORED})"
fi

# ── 汇总 ────────────────────────────────────────────────────────
echo ""
echo "══════════════════════════════════════"
echo "PASS=${PASS}  FAIL=${FAIL}"
echo "日志: ${SERVICE_LOG}"
echo "      ${MOCK_LOG}"
if [[ "$FAIL" -gt 0 ]]; then
  echo "存在失败项，请查看上方 ✗ 与日志。"
  exit 1
fi
echo "全部详细模拟测试通过（未打开真实浏览器）。"
exit 0
