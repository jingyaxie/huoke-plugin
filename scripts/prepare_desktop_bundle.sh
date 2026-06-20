#!/usr/bin/env bash
# [DEPRECATED] 旧版 Python + Playwright 桌面 bundle。默认请用 prepare_desktop_thin_bundle.sh
# 仅在 HUOKE_DESKTOP_LEGACY=1 时由 prepare-desktop-bundle.cjs 调用。
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
FRONTEND_DIR="$ROOT/frontend"
BUNDLE_DIR="$ROOT/desktop/bundle"
BACKEND_SRC="$ROOT/backend"
RUNTIME_DIR="$BUNDLE_DIR/runtime"
TARGET_BACKEND="$BUNDLE_DIR/backend"
PORTABLE_DIR="$RUNTIME_DIR/python"

echo "构建前端 (desktop /api 同源)..."
cd "$FRONTEND_DIR"
if [[ ! -d node_modules ]]; then
  if [[ -f package-lock.json ]]; then
    npm ci
  else
    npm install
  fi
fi
VITE_API_BASE_URL=/api npm run build

echo "校验前端静态资源..."
HUOKE_ROOT="$ROOT" PYTHONPATH="$BACKEND_SRC" python3 - <<'PY'
from pathlib import Path
import os
import sys

root = Path(os.environ["HUOKE_ROOT"])
sys.path.insert(0, str(root / "backend"))
from app.desktop_static import validate_desktop_frontend_dist

errors = validate_desktop_frontend_dist(root / "frontend" / "dist")
if errors:
    for err in errors:
        print(err, file=sys.stderr)
    raise SystemExit(1)
print("frontend dist ok")
PY

echo "清理旧 bundle..."
rm -rf "$BUNDLE_DIR"
mkdir -p "$TARGET_BACKEND" "$RUNTIME_DIR"

echo "复制后端代码..."
rsync -a \
  --exclude '.venv' \
  --exclude '__pycache__' \
  --exclude '.pytest_cache' \
  --exclude 'reports' \
  --exclude 'storage' \
  --exclude 'scripts' \
  --exclude 'tests' \
  --exclude 'pytest.ini' \
  --exclude 'requirements-dev.txt' \
  --exclude 'pyproject.toml' \
  "$BACKEND_SRC/" "$TARGET_BACKEND/"

# 内置 Skill / 规则定义必须打入 bundle（排除整个 storage 会漏掉）
for rel in skills rules; do
  src="$BACKEND_SRC/storage/$rel"
  dst="$TARGET_BACKEND/storage/$rel"
  if [[ ! -d "$src" ]]; then
    echo "missing backend storage/$rel (required for desktop bundle)" >&2
    exit 1
  fi
  mkdir -p "$dst"
  rsync -a "$src/" "$dst/"
done

if [[ -d "$FRONTEND_DIR/dist" ]]; then
  echo "复制前端静态资源..."
  rsync -a "$FRONTEND_DIR/dist/" "$BUNDLE_DIR/frontend-dist/"
fi

bash "$ROOT/scripts/install_portable_python_unix.sh" "$PORTABLE_DIR" "$TARGET_BACKEND/requirements.txt"

PYTHON_BIN=""
for candidate in \
  "$PORTABLE_DIR/bin/python3.12" \
  "$PORTABLE_DIR/bin/python3"; do
  if [[ -x "$candidate" ]]; then
    PYTHON_BIN="$candidate"
    break
  fi
done
if [[ -z "$PYTHON_BIN" ]]; then
  echo "portable python binary missing under $PORTABLE_DIR" >&2
  exit 1
fi

echo "验证 portable Python 可加载后端..."
PYTHONPATH="$TARGET_BACKEND" "$PYTHON_BIN" -c "from app.db.bootstrap import ensure_database_schema; print('backend import ok')"

cat > "$BUNDLE_DIR/BUNDLE_MANIFEST.json" <<EOF
{
  "kind": "huoke-desktop-bundle",
  "python": "runtime/python",
  "backend": "backend",
  "frontend": "frontend-dist",
  "notes": "Self-contained desktop runtime; requires system Google Chrome for browser automation."
}
EOF

echo "bundle 就绪: $BUNDLE_DIR"
