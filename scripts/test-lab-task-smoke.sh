#!/usr/bin/env bash
# 轻量化任务冒烟：通过采集任务 API 驱动 plugin-lab 步骤（非直接调实验室 API）
# 顺序：抖音 → 小红书 → 快手
# 用法: bash scripts/test-lab-task-smoke.sh [抖音关键词] [小红书关键词] [快手关键词]
# 前置: local-service 已启动 + Chrome 已加载 extension/dist 且已登录对应平台
set -euo pipefail

PORT="${HUOKE_LOCAL_PORT:-18766}"
BASE="http://127.0.0.1:${PORT}"
DY_KEYWORD="${1:-健身}"
XHS_KEYWORD="${2:-护肤}"
KS_KEYWORD="${3:-美食}"
PASS=0
FAIL=0

ok()  { echo "  ✓ $*"; PASS=$((PASS + 1)); }
bad() { echo "  ✗ $*" >&2; FAIL=$((FAIL + 1)); }

wait_job() {
  local job_id="$1" label="$2" max="${3:-72}"
  local job=""
  for i in $(seq 1 "$max"); do
    job="$(curl -fsS "${BASE}/api/douyin/jobs/${job_id}")"
    local status videos comments err
    status="$(echo "$job" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status',''))")"
    videos="$(echo "$job" | python3 -c "import sys,json; print(json.load(sys.stdin).get('video_count',0))")"
    comments="$(echo "$job" | python3 -c "import sys,json; print(json.load(sys.stdin).get('comment_count',0))")"
    err="$(echo "$job" | python3 -c "import sys,json; print(json.load(sys.stdin).get('error_message') or '')")"
    printf "  [%s/%s] %s status=%s videos=%s comments=%s" "$i" "$max" "$label" "$status" "$videos" "$comments" >&2
    [[ -n "$err" ]] && printf " err=%s" "$err" >&2
    echo "" >&2
    if [[ "$status" == "completed" || "$status" == "failed" ]]; then
      echo "$job"
      return 0
    fi
    sleep 5
  done
  bad "${label} 轮询超时 job_id=${job_id}" >&2
  curl -fsS "${BASE}/api/douyin/jobs/${job_id}" || true
  return 1
}

run_platform_job() {
  local platform="$1" keyword="$2" label="$3"
  echo ""
  echo ">>> ${label}（platform=${platform} keyword=${keyword}）"

  local body
  body="$(cat <<EOF
{
  "platform": "${platform}",
  "keyword": "${keyword}",
  "name": "lab-task-smoke-${platform}",
  "limit_videos": 1,
  "max_comments_per_video": 8,
  "target_count": 3,
  "publish_time_range": "unlimited",
  "comment_days": 0,
  "auto_start": false,
  "auto_outreach": false
}
EOF
)"

  local created job_id result status videos comments err
  created="$(curl -fsS -X POST "${BASE}/api/douyin/jobs" \
    -H 'Content-Type: application/json' \
    -d "$body")"
  job_id="$(echo "$created" | python3 -c "import sys,json; print(json.load(sys.stdin)['job']['id'])")"
  echo "  job_id=${job_id}"

  curl -fsS -X POST "${BASE}/api/douyin/jobs/${job_id}/start" >/dev/null
  echo "  已启动，轮询中…"

  result="$(wait_job "$job_id" "$label" 90)"
  status="$(echo "$result" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status',''))")"
  videos="$(echo "$result" | python3 -c "import sys,json; print(json.load(sys.stdin).get('video_count',0))")"
  comments="$(echo "$result" | python3 -c "import sys,json; print(json.load(sys.stdin).get('comment_count',0))")"
  err="$(echo "$result" | python3 -c "import sys,json; print(json.load(sys.stdin).get('error_message') or '')")"

  if [[ "$status" == "completed" && "$videos" -ge 1 && "$comments" -ge 1 ]]; then
    ok "${label} completed videos=${videos} comments=${comments}"
    echo "  样例视频:"
    curl -fsS "${BASE}/api/douyin/jobs/${job_id}/videos" \
      | python3 -c "import sys,json; v=json.load(sys.stdin).get('videos',[]); print(json.dumps(v[0] if v else {}, ensure_ascii=False, indent=2))"
    echo "  样例评论:"
    curl -fsS "${BASE}/api/douyin/jobs/${job_id}/comments?limit=1" \
      | python3 -c "import sys,json; c=json.load(sys.stdin).get('comments',[]); print(json.dumps(c[0] if c else {}, ensure_ascii=False, indent=2))"
    return 0
  fi

  if [[ "$videos" -ge 1 ]]; then
    ok "${label} 搜索阶段通过 videos=${videos}（实验室 open/search/fetch 正常）"
  else
    bad "${label} 搜索阶段失败 videos=${videos}${err:+ — ${err}}"
    return 1
  fi

  if [[ "$comments" -ge 1 ]]; then
    ok "${label} 评论阶段通过 comments=${comments}"
    return 0
  fi

  bad "${label} 评论阶段失败 comments=0 status=${status}${err:+ — ${err}}"
  echo "  提示: 搜索链路已通，请确认已登录且视频页评论区可正常打开"
  return 1
}

echo "=== 实验室任务驱动冒烟（抖音 → 小红书 → 快手）==="
echo "BASE=${BASE}"
echo "dy_keyword=${DY_KEYWORD}  xhs_keyword=${XHS_KEYWORD}  ks_keyword=${KS_KEYWORD}"
echo ""

echo "[1/4] 检查 local-service"
if ! curl -fsS -m 3 "${BASE}/health" >/dev/null 2>&1; then
  bad "local-service 未响应 ${BASE}/health"
  exit 1
fi
ok "local-service /health"

echo ""
echo "[2/4] 初始化插件会话"
curl -fsS -X POST "${BASE}/bridge/command" \
  -H 'Content-Type: application/json' \
  -d '{"action":"huoke.runtime.init","payload":{},"wait":true,"timeout_ms":60000}' >/dev/null
ok "lab session cleared"

echo ""
echo "[3/4] 检查插件连接"
CLIENTS="$(curl -fsS "${BASE}/bridge/status" \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('extension_clients', d.get('connected_clients',0)))")"
if [[ "$CLIENTS" == "0" ]]; then
  bad "插件未连接 — 请加载 extension/dist 并确保角标 OK"
  exit 1
fi
ok "extension connected (clients=${CLIENTS})"

echo ""
echo "[4/4] 创建并运行轻量化采集任务"
set +e
run_platform_job "douyin" "$DY_KEYWORD" "抖音"
DY_RC=$?
run_platform_job "xiaohongshu" "$XHS_KEYWORD" "小红书"
XHS_RC=$?
run_platform_job "kuaishou" "$KS_KEYWORD" "快手"
KS_RC=$?
set -e

echo ""
echo "========== 汇总 =========="
echo "PASS=${PASS}  FAIL=${FAIL}"
echo "抖音 RC=${DY_RC}  小红书 RC=${XHS_RC}  快手 RC=${KS_RC}"
if [[ "$FAIL" -gt 0 ]]; then
  echo "部分阶段未通过。搜索阶段通过即表示任务已成功驱动实验室 open/search/fetch 流程。"
  exit 1
fi
echo "抖音、小红书、快手任务驱动实验室流程均通过。"
