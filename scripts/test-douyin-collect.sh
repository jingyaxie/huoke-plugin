#!/usr/bin/env bash
# 抖音关键词采集 API 冒烟测试（需 Chrome 已加载插件并打开抖音页）
set -euo pipefail

PORT="${HUOKE_LOCAL_PORT:-18766}"
BASE="http://127.0.0.1:${PORT}"
KEYWORD="${1:-装修}"

echo "=== Douyin Collect Smoke Test ==="
echo "keyword: ${KEYWORD}"
echo ""

curl -fsS "${BASE}/health" | jq .
echo ""

STATUS_JSON=$(curl -fsS "${BASE}/bridge/status")
echo "$STATUS_JSON" | jq .
CLIENTS=$(echo "$STATUS_JSON" | jq -r '.connected_clients')
if [[ "$CLIENTS" == "0" ]]; then
  echo "⚠ 插件未连接。请先在 Chrome 加载 extension/dist 并打开抖音页面。" >&2
  exit 1
fi

JOB_JSON=$(curl -fsS -X POST "${BASE}/api/douyin/jobs" \
  -H 'Content-Type: application/json' \
  -d "{\"keyword\":\"${KEYWORD}\",\"limit_videos\":3,\"max_comments_per_video\":30}")
echo "$JOB_JSON" | jq .
JOB_ID=$(echo "$JOB_JSON" | jq -r '.job.id')

echo ""
echo ">>> 启动采集 job_id=${JOB_ID}"
curl -fsS -X POST "${BASE}/api/douyin/jobs/${JOB_ID}/start" | jq .

echo ""
echo ">>> 轮询任务状态（最多 3 分钟）"
for _ in $(seq 1 36); do
  JOB=$(curl -fsS "${BASE}/api/douyin/jobs/${JOB_ID}")
  STATUS=$(echo "$JOB" | jq -r '.status')
  VIDEOS=$(echo "$JOB" | jq -r '.video_count')
  COMMENTS=$(echo "$JOB" | jq -r '.comment_count')
  echo "  status=${STATUS} videos=${VIDEOS} comments=${COMMENTS}"
  if [[ "$STATUS" == "completed" || "$STATUS" == "failed" ]]; then
    echo "$JOB" | jq .
    break
  fi
  sleep 5
done

echo ""
echo ">>> 视频列表"
curl -fsS "${BASE}/api/douyin/jobs/${JOB_ID}/videos" | jq '.videos | length, .[0]'

echo ""
echo ">>> 评论样例"
curl -fsS "${BASE}/api/douyin/jobs/${JOB_ID}/comments?limit=5" | jq '.comments | length, .[0]'
