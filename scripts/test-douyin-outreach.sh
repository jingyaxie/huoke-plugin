#!/usr/bin/env bash
# 抖音评论触达 API 冒烟测试（需采集任务已有评论 + Chrome 插件已连接）
set -euo pipefail

PORT="${HUOKE_LOCAL_PORT:-18766}"
BASE="http://127.0.0.1:${PORT}"
COLLECT_JOB_ID="${1:-}"
REPLY_TEXT="${2:-您好，感谢关注！}"

if [[ -z "$COLLECT_JOB_ID" ]]; then
  echo "用法: bash scripts/test-douyin-outreach.sh <collect_job_id> [reply_text]" >&2
  exit 1
fi

echo "=== Douyin Outreach Smoke Test ==="
curl -fsS "${BASE}/api/douyin/quota" | jq .

TASK_JSON=$(curl -fsS -X POST "${BASE}/api/douyin/outreach/tasks" \
  -H 'Content-Type: application/json' \
  -d "{\"source_job_id\":\"${COLLECT_JOB_ID}\",\"reply_text\":\"${REPLY_TEXT}\",\"max_items\":3}")
echo "$TASK_JSON" | jq .
TASK_ID=$(echo "$TASK_JSON" | jq -r '.task.id')

echo ""
echo ">>> 启动触达 task_id=${TASK_ID}"
curl -fsS -X POST "${BASE}/api/douyin/outreach/tasks/${TASK_ID}/start" | jq .

echo ""
echo ">>> 轮询触达状态（最多 3 分钟）"
for _ in $(seq 1 36); do
  TASK=$(curl -fsS "${BASE}/api/douyin/outreach/tasks/${TASK_ID}")
  STATUS=$(echo "$TASK" | jq -r '.status')
  DONE=$(echo "$TASK" | jq -r '.completed_count')
  FAIL=$(echo "$TASK" | jq -r '.failed_count')
  PENDING=$(echo "$TASK" | jq -r '.pending_count')
  echo "  status=${STATUS} done=${DONE} fail=${FAIL} pending=${PENDING}"
  if [[ "$STATUS" == "completed" || "$STATUS" == "failed" || "$STATUS" == "paused" ]]; then
    echo "$TASK" | jq .
    break
  fi
  sleep 5
done

echo ""
curl -fsS "${BASE}/api/douyin/outreach/tasks/${TASK_ID}/items?limit=5" | jq '.items | length, .[0]'
