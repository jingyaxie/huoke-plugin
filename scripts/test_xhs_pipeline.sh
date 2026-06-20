#!/usr/bin/env bash
# 小红书：任务创建 → 编排 → 模拟执行 自动化测试
# 用法: bash scripts/test_xhs_pipeline.sh
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

echo "=== 小红书任务流水线自动化测试 ==="
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
  tests/test_xhs_create_orchestrate_simulate_pipeline.py \
  tests/test_xhs_profile_videos.py \
  tests/test_xhs_comment_days_filter.py \
  tests/test_xhs_note_url_resolution.py \
  tests/test_xhs_search_api_match.py \
  tests/test_xhs_search_searchbar_only.py \
  tests/test_task_form_orchestration_audit.py \
  tests/test_full_create_orchestrate_simulate_pipeline.py \
  tests/test_task_planned_execution_simulation.py \
  tests/test_agent_strategy_registry.py \
  tests/test_skill_platform_routing.py \
  -k 'xhs or xiaohongshu or auto_xhs' \
  -v --tb=short

echo ""
echo "全部通过"
