#!/usr/bin/env bash
# 自动创建关键词任务、跟踪状态、失败时在同一任务上重试（不重复建任务）
# 用法: bash scripts/auto-run-keyword.sh [关键词] [地区名]
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PORT="${HUOKE_LOCAL_PORT:-18766}"
BASE="http://127.0.0.1:${PORT}"
DATA_DIR="${HUOKE_DATA_DIR:-$HOME/Library/Application Support/com.huoke.desktop}"
BIN="$ROOT/local-service/target/release/huoke-local-service"
LOG="/tmp/huoke-auto-keyword.log"
KEYWORD="${1:-上海健身}"
REGION="${2:-上海}"
MAX_ATTEMPTS="${HUOKE_AUTO_MAX_ATTEMPTS:-2}"
LS_PID=""

cleanup() {
  [[ -n "${LS_PID:-}" ]] && kill "$LS_PID" 2>/dev/null || true
}
trap cleanup EXIT

log() {
  local msg="[$(date '+%H:%M:%S')] $*"
  echo "$msg" >>"$LOG"
  echo "$msg" >&2
}

wait_http() {
  local path="$1" tries="${2:-40}"
  for _ in $(seq 1 "$tries"); do
    curl -fsS -m 2 "${BASE}${path}" >/dev/null 2>&1 && return 0
    sleep 0.3
  done
  return 1
}

wait_bridge() {
  for _ in $(seq 1 60); do
    local ext
    ext="$(curl -fsS "${BASE}/bridge/status" 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('extension_clients', d.get('connected_clients',0)))" 2>/dev/null || echo 0)"
    if [[ "$ext" != "0" ]]; then
      log "Bridge 就绪 extension_clients=${ext}"
      return 0
    fi
    sleep 0.5
  done
  return 1
}

ensure_service() {
  log "构建 local-service..."
  (cd "$ROOT/local-service" && cargo build --release -q --bin huoke-local-service)

  local need_restart=0
  if curl -fsS -m 2 "${BASE}/health" >/dev/null 2>&1; then
    local pid bin_mtime proc_start
    pid="$(lsof -tiTCP:"${PORT}" -sTCP:LISTEN 2>/dev/null || true)"
    bin_mtime="$(stat -f %m "$BIN" 2>/dev/null || stat -c %Y "$BIN" 2>/dev/null || echo 0)"
    if [[ -n "$pid" ]]; then
      proc_start="$(ps -p "$pid" -o lstart= 2>/dev/null | xargs -I{} date -j -f "%a %b %d %T %Y" "{}" +%s 2>/dev/null || echo 0)"
      if [[ "$bin_mtime" -gt "$proc_start" ]]; then
        log "检测到 local-service 二进制已更新，重启服务"
        need_restart=1
      else
        log "local-service 已在运行且为最新构建，跳过重启"
        return 0
      fi
    fi
  else
    need_restart=1
  fi

  if [[ "$need_restart" == "1" ]]; then
    local pid
    pid="$(lsof -tiTCP:"${PORT}" -sTCP:LISTEN 2>/dev/null || true)"
    [[ -n "$pid" ]] && kill "$pid" 2>/dev/null && sleep 1.5
  fi

  log "启动 local-service DATA=${DATA_DIR}"
  HUOKE_DATA_DIR="$DATA_DIR" HUOKE_LOCAL_PORT="$PORT" \
    "$BIN" >>"$LOG" 2>&1 &
  LS_PID=$!
  trap - EXIT
  wait_http "/health" || { log "local-service 启动失败"; tail -30 "$LOG"; exit 1; }
  log "local-service /health OK"
}

poll_job() {
  local job_id="$1" max="${2:-240}"
  for i in $(seq 1 "$max"); do
    local job status videos comments err
    job="$(curl -fsS "${BASE}/api/douyin/jobs/${job_id}")"
    status="$(echo "$job" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status',''))" 2>/dev/null || echo "")"
    videos="$(echo "$job" | python3 -c "import sys,json; print(json.load(sys.stdin).get('video_count',0))")"
    comments="$(echo "$job" | python3 -c "import sys,json; print(json.load(sys.stdin).get('comment_count',0))")"
    err="$(echo "$job" | python3 -c "import sys,json; print(json.load(sys.stdin).get('error_message') or '')")"
    log "  [${i}] status=${status} videos=${videos} comments=${comments}${err:+ err=${err}}"
    if [[ "$status" == "completed" || "$status" == "failed" ]]; then
      echo "$job"
      return 0
    fi
    sleep 5
  done
  log "任务超时 job_id=${job_id}"
  curl -fsS "${BASE}/api/douyin/jobs/${job_id}" || true
  return 1
}

create_job() {
  local keyword="$1" region="$2"
  local region_json="null"
  [[ -n "$region" ]] && region_json="\"${region}\""

  local body
  body="$(cat <<EOF
{
  "keyword": "${keyword}",
  "name": "auto-test-${keyword}",
  "limit_videos": 5,
  "max_comments_per_video": 30,
  "target_count": 50,
  "region_name": ${region_json},
  "publish_time_range": "unlimited",
  "comment_days": 7,
  "auto_start": false,
  "auto_outreach": false
}
EOF
)"
  curl -fsS -X POST "${BASE}/api/douyin/jobs" -H 'Content-Type: application/json' -d "$body"
}

start_job() {
  local job_id="$1"
  curl -fsS -X POST "${BASE}/api/douyin/jobs/${job_id}/start" >/dev/null
}

main() {
  : >"$LOG"
  log "=== 自动关键词测试 keyword=${KEYWORD} region=${REGION}（单任务，最多 ${MAX_ATTEMPTS} 次启动）==="

  ensure_service

  if ! wait_bridge; then
    log "⚠ 插件未连接，等待 30s..."
    sleep 30
    wait_bridge || { log "仍无插件连接，退出"; exit 1; }
  fi

  local region="$REGION"
  local job_id=""
  local attempt=1

  while [[ "$attempt" -le "$MAX_ATTEMPTS" ]]; do
    if [[ -z "$job_id" ]]; then
      log ">>> 创建任务（仅一次）attempt=${attempt} region=${region:-无}"
      job_id="$(create_job "$KEYWORD" "$region" | python3 -c "import sys,json; print(json.load(sys.stdin)['job']['id'])")"
      log "job_id=${job_id}"
    else
      log ">>> 在同一任务上重试 attempt=${attempt} job_id=${job_id}"
    fi

    start_job "$job_id"
    local result status err
    result="$(poll_job "$job_id" 240)"
    status="$(echo "$result" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status',''))")"
    err="$(echo "$result" | python3 -c "import sys,json; print(json.load(sys.stdin).get('error_message') or '')")"

    if [[ "$status" == "completed" ]]; then
      local v c
      v="$(echo "$result" | python3 -c "import sys,json; print(json.load(sys.stdin).get('video_count',0))")"
      c="$(echo "$result" | python3 -c "import sys,json; print(json.load(sys.stdin).get('comment_count',0))")"
      log "✓ 成功 videos=${v} comments=${c}"
      echo "$result" | python3 -m json.tool
      exit 0
    fi

    log "✗ 失败: ${err}"
    if [[ "$err" == *"none matched region"* && "$attempt" -lt "$MAX_ATTEMPTS" ]]; then
      region=""
      attempt=$((attempt + 1))
      sleep 3
      continue
    fi
    if [[ "$attempt" -lt "$MAX_ATTEMPTS" ]]; then
      attempt=$((attempt + 1))
      sleep 5
      continue
    fi

    echo "$result" | python3 -m json.tool
    log "日志: ${LOG}"
    exit 1
  done
}

set +e
main "$@"
