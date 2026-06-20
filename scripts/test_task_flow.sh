#!/usr/bin/env bash
# 任务创建 → 编排 → 执行 全流程自动化测试
# 用法: bash scripts/test_task_flow.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BACKEND="${ROOT}/backend"

pick_python() {
  for candidate in \
    "${BACKEND}/.venv/bin/python" \
    python3.12 python3.11 python3; do
    if [[ -x "$candidate" || "$(command -v "$candidate" 2>/dev/null)" == "$candidate" ]] \
      && "$candidate" -c "import pytest" 2>/dev/null; then
      if [[ "$candidate" != python3.* ]] && [[ ! -x "$candidate" ]]; then
        candidate="$(command -v "$candidate")"
      fi
      echo "$candidate"
      return
    fi
  done
  echo python3
}

PY="$(pick_python)"

echo "=== 任务流程自动化测试 ==="
echo "python=$PY"
echo ""

if ! "$PY" -c "import pytest_asyncio" 2>/dev/null; then
  echo "安装测试依赖..."
  "$PY" -m pip install -r "$BACKEND/requirements-dev.txt" -q
fi
if ! "$PY" -c "import pymysql, multipart" 2>/dev/null; then
  echo "安装运行时测试依赖..."
  (cd "$BACKEND" && "$PY" -m pip install pymysql python-multipart pytest-asyncio -q)
fi

cd "$BACKEND"
"$PY" -m pytest \
  tests/test_task_form_orchestration_audit.py \
  tests/test_task_planned_execution_simulation.py \
  tests/test_task_orchestration_flow.py \
  tests/test_external_task_agent_e2e.py \
  tests/test_external_task_preflight.py \
  tests/test_external_task_service.py \
  tests/test_frontend_payload_alignment.py \
  tests/test_agent_orchestration_job.py \
  tests/test_agent_job_plan.py \
  tests/test_task_execution_plan.py \
  -q --tb=short

echo ""
echo "全部通过"
