#!/usr/bin/env bash
# 编排任务自动化测试：pytest 单元/集成 + 可选本地 API 联调
# 用法：
#   bash scripts/test_orchestration.sh
#   LIVE=1 bash scripts/test_orchestration.sh   # 后端已启动时额外打 API
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BACKEND="${ROOT}/backend"
BACKEND_PORT="${BACKEND_PORT:-8000}"
BASE="http://127.0.0.1:${BACKEND_PORT}"
TENANT="${HUOKE_TENANT_ID:-default}"
PASS=0
FAIL=0

ok()  { echo "  ✓ $*"; PASS=$((PASS + 1)); }
bad() { echo "  ✗ $*" >&2; FAIL=$((FAIL + 1)); }

pick_python() {
  if [[ -x "${BACKEND}/.venv/bin/python" ]] && "${BACKEND}/.venv/bin/python" -c "import pytest" 2>/dev/null; then
    echo "${BACKEND}/.venv/bin/python"
    return
  fi
  for candidate in python3.12 python3.11 python3; do
    if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c "import pytest" 2>/dev/null; then
      echo "$(command -v "$candidate")"
      return
    fi
  done
  for candidate in python3.12 python3.11 python3; do
    if command -v "$candidate" >/dev/null 2>&1; then
      echo "$(command -v "$candidate")"
      return
    fi
  done
  echo python3
}

PY="$(pick_python)"

echo "=== Huoke 编排任务自动化测试 ==="
echo "python=$PY"
echo ""

echo "[1/2] pytest 编排相关用例"
if ! "$PY" -c "import pymysql, multipart" 2>/dev/null; then
  echo "  安装测试依赖 pymysql python-multipart pytest-asyncio ..."
  (cd "$BACKEND" && "$PY" -m pip install pymysql python-multipart pytest-asyncio -q)
fi
if (cd "$BACKEND" && "$PY" -m pytest \
  tests/test_task_orchestration_flow.py \
  tests/test_agent_job_plan.py \
  tests/test_agent_orchestration_job.py \
  tests/test_task_supervisor_service.py \
  tests/test_task_form_orchestration_audit.py \
  tests/test_full_create_orchestrate_simulate_pipeline.py \
  tests/test_task_planned_execution_simulation.py \
  tests/test_orchestration_resilience_scale.py \
  tests/test_page_diagnosis.py \
  tests/test_page_diagnosis_settings_service.py \
  tests/test_page_diagnosis_settings_api.py \
  tests/test_xhs_create_orchestrate_simulate_pipeline.py \
  tests/test_xhs_comment_follow_e2e_mock.py \
  -q --tb=line); then
  ok "pytest 全部通过"
else
  bad "pytest 失败"
  echo ""
  echo "结果: ${PASS} 通过, ${FAIL} 失败"
  exit 1
fi

echo ""
echo "[2/3] LIVE 编排联调（ORCHESTRATION_LIVE=1，dry_run 不真抓）"
if [[ "${ORCHESTRATION_LIVE:-0}" != "1" ]]; then
  echo "  ~ 跳过 LIVE（设置 ORCHESTRATION_LIVE=1 启用真实 LLM + dry_run Supervisor）"
else
  HUOKE_ENV="${HUOKE_ENV:-/Users/macbook/project/ai/huoke/.env}"
  if ORCHESTRATION_LIVE=1 HUOKE_ENV="$HUOKE_ENV" "${BACKEND}/.venv/bin/python" "$BACKEND/scripts/test_orchestration_live.py"; then
    ok "LIVE 编排 + Supervisor dry_run"
  else
    bad "LIVE 编排测试失败"
  fi
fi

echo ""
echo "[3/3] 编排 API 快速检查（LIVE=1 时由上方脚本覆盖）"
if [[ "${LIVE:-0}" != "1" || "${ORCHESTRATION_LIVE:-0}" == "1" ]]; then
  if [[ "${ORCHESTRATION_LIVE:-0}" == "1" ]]; then
    echo "  ~ 已由 test_orchestration_live.py 覆盖 API dry_run"
  else
    echo "  ~ 跳过（LIVE=1 或 ORCHESTRATION_LIVE=1）"
  fi
else
  if ! curl -sS -m 5 "${BASE}/api/health" | grep -q '"status":"ok"'; then
    bad "后端未运行 — 先执行: bash scripts/dev-native.sh"
  else
    ok "后端 health"
    PAYLOAD="$(cat <<'EOF'
{
  "message": "深圳餐饮线索：抖音关键词团餐配送，目标30条，分多天触达",
  "provider": "deepseek",
  "run_mode": "dry_run",
  "auto_execute": false,
  "timeout_seconds": 120
}
EOF
)"
    SUBMIT="$(curl -sS -m 30 -X POST "${BASE}/api/agent/jobs" \
      -H "Content-Type: application/json" \
      -H "X-Tenant-Id: ${TENANT}" \
      -H "X-Platform-Id: douyin" \
      -H "X-Account-Id: default" \
      -d "$PAYLOAD" 2>/dev/null || echo '{}')"
    JOB_ID="$(echo "$SUBMIT" | "$PY" -c "import sys,json; print(json.load(sys.stdin).get('job_id',''))" 2>/dev/null || echo "")"
    EXEC_MODE="$(echo "$SUBMIT" | "$PY" -c "import sys,json; d=json.load(sys.stdin); print((d.get('result') or {}).get('execution_mode',''))" 2>/dev/null || echo "")"
    ORCH_SOURCE="$(echo "$SUBMIT" | "$PY" -c "import sys,json; d=json.load(sys.stdin); print(((d.get('result') or {}).get('orchestration') or {}).get('source',''))" 2>/dev/null || echo "")"
    HAS_BRIEF="$(echo "$SUBMIT" | "$PY" -c "import sys,json; d=json.load(sys.stdin); print(bool(((d.get('result') or {}).get('orchestration') or {}).get('task_brief',{}).get('brief_md')))" 2>/dev/null || echo "False")"
    if [[ -n "$JOB_ID" && "$EXEC_MODE" == "supervisor" && "$HAS_BRIEF" == "True" ]]; then
      ok "POST /api/agent/jobs job_id=${JOB_ID} mode=supervisor source=${ORCH_SOURCE}"
      EXEC_RESP="$(curl -sS -m 10 -X POST "${BASE}/api/agent/jobs/${JOB_ID}/execute" \
        -H "X-Tenant-Id: ${TENANT}" 2>/dev/null || echo '{}')"
      EXEC_STATUS="$(echo "$EXEC_RESP" | "$PY" -c "import sys,json; print(json.load(sys.stdin).get('status',''))" 2>/dev/null || echo "")"
      if [[ "$EXEC_STATUS" == "queued" || "$EXEC_STATUS" == "running" ]]; then
        ok "POST /api/agent/jobs/${JOB_ID}/execute status=${EXEC_STATUS}"
      else
        bad "启动编排任务异常 status=${EXEC_STATUS:-?}"
      fi
    else
      bad "提交编排任务失败 job_id=${JOB_ID:-?} execution_mode=${EXEC_MODE:-?}"
    fi
  fi
fi

echo ""
echo "=== 结果: ${PASS} 通过, ${FAIL} 失败 ==="
if [[ "$FAIL" -gt 0 ]]; then
  exit 1
fi
exit 0
