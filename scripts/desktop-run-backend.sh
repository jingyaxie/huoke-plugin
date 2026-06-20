#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=scripts/desktop-common.sh
source "$ROOT/scripts/desktop-common.sh"
HUOKE_ROOT="$ROOT"
ensure_desktop_path

BUNDLE_DIR="$(resolve_huoke_bundle_dir)"
DATA_DIR="$(resolve_huoke_data_dir)"
BACKEND_PORT="${BACKEND_PORT:-$HUOKE_DESKTOP_PORT}"
STORAGE_DIR="$DATA_DIR/storage"
ENV_FILE="$DATA_DIR/.env.desktop"
LOG_FILE="${HUOKE_LOG_FILE:-$DATA_DIR/logs/AI获客平台.log}"
DB_FILE="$STORAGE_DIR/huoke_desktop.db"
mkdir -p "$DATA_DIR" "$STORAGE_DIR" "$STORAGE_DIR/douyin/profile" "$(dirname "$LOG_FILE")"
exec > >(tee -a "$LOG_FILE") 2>&1
echo "[backend] [$(date '+%F %T')] desktop-run-backend root=$ROOT bundle=$BUNDLE_DIR log=$LOG_FILE"

if [[ ! -f "$ENV_FILE" ]]; then
  cp "$ROOT/.env.desktop.example" "$ENV_FILE"
  echo "已创建桌面配置: $ENV_FILE"
  echo "请按需编辑 API Key 后重启应用。"
fi

resolve_portable_python() {
  local bundle_dir="$1"
  local candidate
  for candidate in \
    "$bundle_dir/runtime/python/bin/python3.12" \
    "$bundle_dir/runtime/python/bin/python3" \
    "$bundle_dir/runtime/python/python.exe"; do
    if [[ -x "$candidate" ]]; then
      printf '%s' "$candidate"
      return 0
    fi
  done
  return 1
}

PORTABLE_PYTHON=""
if PORTABLE_PYTHON="$(resolve_portable_python "$BUNDLE_DIR" 2>/dev/null || true)" && [[ -n "$PORTABLE_PYTHON" ]]; then
  BACKEND_DIR="$BUNDLE_DIR/backend"
  PYTHON="$PORTABLE_PYTHON"
elif [[ -d "$BUNDLE_DIR/runtime/.venv" ]]; then
  BACKEND_DIR="$BUNDLE_DIR/backend"
  PYTHON="$BUNDLE_DIR/runtime/.venv/bin/python"
else
  BACKEND_DIR="$ROOT/backend"
  if [[ -d "$BACKEND_DIR/.venv" ]]; then
    PYTHON="$BACKEND_DIR/.venv/bin/python"
  else
    PYTHON=""
    for candidate in python3.12 python3.11 python3; do
      if command -v "$candidate" >/dev/null 2>&1; then
        ver="$("$candidate" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
        major="${ver%%.*}"
        minor="${ver#*.}"
        if (( major >= 3 && minor >= 11 )); then
          PYTHON="$candidate"
          break
        fi
      fi
    done
  fi
fi

if [[ -z "${PYTHON:-}" || ! -x "$PYTHON" ]]; then
  echo "未找到可用的 Python 3.11+ 运行时" >&2
  exit 1
fi

if lsof -iTCP:"${BACKEND_PORT}" -sTCP:LISTEN -P -n 2>/dev/null | grep -qv '^COMMAND'; then
  echo "桌面版端口 ${BACKEND_PORT} 被占用，尝试回收残留 Huoke 后端..."
  PORT_GUARD="$ROOT/scripts/desktop_port_guard.py"
  if [[ -f "$PORT_GUARD" ]]; then
    "$PYTHON" "$PORT_GUARD" --port "${BACKEND_PORT}" --data-dir "$DATA_DIR" 2>/dev/null || true
  fi
fi

if lsof -iTCP:"${BACKEND_PORT}" -sTCP:LISTEN -P -n 2>/dev/null | grep -qv '^COMMAND'; then
  echo "桌面版端口 ${BACKEND_PORT} 已被占用，无法启动内置后端。" >&2
  lsof -iTCP:"${BACKEND_PORT}" -sTCP:LISTEN -P -n 2>/dev/null || true
  echo "请关闭占用该端口的进程后重开应用（勿与 dev 后端 8000 混淆）。" >&2
  exit 1
fi

cd "$BACKEND_DIR"
export DESKTOP_MODE=true
if [[ -d "$BUNDLE_DIR/frontend-dist" ]]; then
  export FRONTEND_DIST_DIR="$BUNDLE_DIR/frontend-dist"
else
  export FRONTEND_DIST_DIR="$ROOT/frontend/dist"
fi
export STORAGE_ROOT="$STORAGE_DIR"
export FRONTEND_ORIGIN="http://127.0.0.1:${BACKEND_PORT}"
export DATABASE_URL="sqlite+pysqlite:///${DB_FILE}"
export DOUYIN_PROFILE_DIR="${STORAGE_DIR}/douyin/profile"
export PYTHONPATH="$BACKEND_DIR"

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

export DESKTOP_MODE=true
export FRONTEND_ORIGIN="http://127.0.0.1:${BACKEND_PORT}"
if [[ -d "$BUNDLE_DIR/frontend-dist" ]]; then
  export FRONTEND_DIST_DIR="$BUNDLE_DIR/frontend-dist"
fi
export DATABASE_URL="sqlite+pysqlite:///${DB_FILE}"
export STORAGE_ROOT="$STORAGE_DIR"
export DOUYIN_PROFILE_DIR="${STORAGE_DIR}/douyin/profile"

CHROME="$(find_chrome_executable 2>/dev/null || true)"
if [[ -z "$CHROME" ]]; then
  echo "未安装 Google Chrome，无法执行浏览器自动化。请安装后重启应用。" >&2
  echo "下载: https://www.google.com/chrome/" >&2
  exit 1
fi
echo "Chrome: $($CHROME --version 2>/dev/null || true)"

echo "初始化数据库..."
"$PYTHON" - <<'PY'
from app.db.bootstrap import ensure_database_schema
ensure_database_schema()
print("数据库 schema 已就绪")
PY

echo "启动后端: $PYTHON (port ${BACKEND_PORT}, SQLite)"
exec "$PYTHON" -m uvicorn app.main:app --host 127.0.0.1 --port "${BACKEND_PORT}"
