#!/usr/bin/env bash
# 模拟真实关键词任务：POST /api/douyin/jobs → start → 走 run_keyword_search 编排
# 只验证搜索+筛选+入库阶段（video_count>0 后 pause，不等评论采完）
#
# 用法: bash scripts/test-search-filter-flow.sh [关键词] [publish_time_range]
#   publish_time_range: 1d | 3d | 7d | 180d | unlimited（默认 7d）
set -euo pipefail

PORT="${HUOKE_LOCAL_PORT:-18766}"
BASE="http://127.0.0.1:${PORT}"
KEYWORD="${1:-装修}"
PUBLISH_RANGE="${2:-7d}"
REPORT_DIR="${HUOKE_TEST_REPORT_DIR:-storage/test-reports}"
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
REPORT="${REPORT_DIR}/keyword-job-search-${TIMESTAMP}.log"

PASS=0
FAIL=0

mkdir -p "$REPORT_DIR"

log() {
  local line="[$(date '+%H:%M:%S')] $*"
  echo "$line" | tee -a "$REPORT"
}

ok()  { log "✓ $*"; PASS=$((PASS + 1)); }
bad() { log "✗ $*"; FAIL=$((FAIL + 1)); }

log "=== 关键词任务：搜索+筛选（真实编排）==="
log "BASE=${BASE} keyword=${KEYWORD} publish_time_range=${PUBLISH_RANGE}"
log "报告: ${REPORT}"

if ! curl -fsS "${BASE}/health" | jq -e '.ok == true' >/dev/null; then
  bad "local-service 不可用"
  exit 1
fi

CLIENTS="$(curl -fsS "${BASE}/bridge/status" | jq -r '.connected_clients')"
if [[ "$CLIENTS" == "0" ]]; then
  bad "插件未连接 — 请加载 extension/dist"
  exit 1
fi
ok "插件已连接 (clients=${CLIENTS})"

log ""
log ">>> 创建关键词任务（与前端创建任务相同 API）"
JOB_BODY="$(cat <<EOF
{
  "platform": "douyin",
  "keyword": "${KEYWORD}",
  "name": "test-search-filter-${TIMESTAMP}",
  "limit_videos": 1,
  "max_comments_per_video": 5,
  "target_count": 1,
  "publish_time_range": "${PUBLISH_RANGE}",
  "comment_days": 0,
  "auto_start": false,
  "auto_outreach": false
}
EOF
)"
CREATED="$(curl -fsS -X POST "${BASE}/api/douyin/jobs" \
  -H 'Content-Type: application/json' \
  -d "$JOB_BODY")"
echo "$CREATED" | jq '{job_id: .job.id, status: .job.status, publish_time_range: .job.publish_time_range}' | tee -a "$REPORT"
JOB_ID="$(echo "$CREATED" | jq -r '.job.id')"
[[ -n "$JOB_ID" && "$JOB_ID" != "null" ]] || { bad "创建任务失败"; exit 1; }
ok "任务已创建 job_id=${JOB_ID}"

log ""
log ">>> 启动任务（编排入口 run_keyword_job → run_keyword_search）"
curl -fsS -X POST "${BASE}/api/douyin/jobs/${JOB_ID}/start" | jq -c '{job_id, status}' | tee -a "$REPORT"

log ""
log ">>> 轮询至搜索阶段完成（video_count>0 或 failed，最多 5 分钟）"
JOB=""
for i in $(seq 1 60); do
  JOB="$(curl -fsS "${BASE}/api/douyin/jobs/${JOB_ID}")"
  STATUS="$(echo "$JOB" | jq -r '.status')"
  VIDEOS="$(echo "$JOB" | jq -r '.video_count // 0')"
  ERR="$(echo "$JOB" | jq -r '.error_message // empty')"
  log "  [${i}/60] status=${STATUS} videos=${VIDEOS}${ERR:+ err=${ERR}}"

  if [[ "$STATUS" == "failed" ]]; then
    bad "任务失败: ${ERR:-unknown}"
    echo "$JOB" | jq . | tee -a "$REPORT"
    exit 1
  fi

  if [[ "$VIDEOS" -ge 1 ]]; then
    ok "搜索阶段完成，已入库 ${VIDEOS} 条视频"
    curl -fsS -X POST "${BASE}/api/douyin/jobs/${JOB_ID}/pause" >/dev/null 2>&1 || true
    log "  已 pause，跳过后续评论采集"
    break
  fi

  if [[ "$STATUS" == "completed" ]]; then
    ok "任务已完成 videos=${VIDEOS}"
    break
  fi

  sleep 5
done

if [[ -z "$JOB" ]] || [[ "$(echo "$JOB" | jq -r '.video_count // 0')" -lt 1 ]]; then
  bad "超时：搜索阶段未入库任何视频"
  echo "$JOB" | jq . | tee -a "$REPORT" || true
  exit 1
fi

log ""
log ">>> 校验入库视频"
VIDEOS_JSON="$(curl -fsS "${BASE}/api/douyin/jobs/${JOB_ID}/videos")"
echo "$VIDEOS_JSON" | jq '{count: (.videos | length), samples: [.videos[0:3][] | {aweme_id, title, author, create_time: (try (.raw_json | fromjson | .create_time) catch null)}]}' | tee -a "$REPORT"

COUNT="$(echo "$VIDEOS_JSON" | jq '.videos | length')"
[[ "$COUNT" -ge 1 ]] && ok "GET /videos 返回 ${COUNT} 条" || bad "视频列表为空"

if [[ "$PUBLISH_RANGE" != "unlimited" && "$PUBLISH_RANGE" != "" ]]; then
  DAYS="$(python3 - <<PY
r = "${PUBLISH_RANGE}".strip().lower()
print({"1d":1,"3d":3,"7d":7,"180d":180}.get(r, 0))
PY
)"
  if [[ "$DAYS" -gt 0 ]]; then
    CHECK="$(echo "$VIDEOS_JSON" | python3 -c "
import json, sys, time
days = int('${DAYS}')
cutoff = int(time.time()) - days * 86400
data = json.load(sys.stdin)
rows = data.get('videos') or []
with_ts = []
outside = []
for v in rows:
    raw = v.get('raw_json') or ''
    ct = None
    if raw:
        try:
            ct = json.loads(raw).get('create_time')
        except Exception:
            pass
    if ct is None:
        continue
    ts = int(ct)
    if ts > 1_000_000_000_000:
        ts //= 1000
    with_ts.append({'aweme_id': v.get('aweme_id'), 'create_time': ts})
    if ts < cutoff:
        outside.append({'aweme_id': v.get('aweme_id'), 'create_time': ts, 'age_days': (int(time.time())-ts)//86400})
print(json.dumps({'total': len(rows), 'with_create_time': len(with_ts), 'outside': outside}, ensure_ascii=False))
")"
    echo "$CHECK" | jq . | tee -a "$REPORT"
    OUTSIDE="$(echo "$CHECK" | jq '.outside | length')"
    WITH_TS="$(echo "$CHECK" | jq '.with_create_time')"
    if [[ "$WITH_TS" -gt 0 && "$OUTSIDE" -eq 0 ]]; then
      ok "全部 ${WITH_TS} 条含 create_time 的视频均在 ${DAYS} 天内"
    elif [[ "$WITH_TS" -eq 0 ]]; then
      log "  提示: 视频 raw_json 无 create_time（可能为 DOM 兜底 poster_* id），无法校验发布时间"
    else
      bad "${OUTSIDE}/${WITH_TS} 条视频超出 ${PUBLISH_RANGE} 筛选"
    fi
  fi
fi

log ""
log "=== 汇总 PASS=${PASS} FAIL=${FAIL} job_id=${JOB_ID} ==="
log "报告: ${REPORT}"
[[ "$FAIL" -eq 0 ]]
