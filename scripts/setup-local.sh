#!/usr/bin/env bash
# 本地环境初始化：安装依赖 + 可选启动开发服务
# 用法:
#   bash scripts/setup-local.sh           # 仅安装依赖
#   bash scripts/setup-local.sh --start   # 安装后启动前后端
#   bash scripts/setup-local.sh --check   # 仅检查环境，不安装
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BACKEND_DIR="$ROOT/backend"
FRONTEND_DIR="$ROOT/frontend"
START_AFTER_SETUP=0
CHECK_ONLY=0

for arg in "$@"; do
  case "$arg" in
    --start) START_AFTER_SETUP=1 ;;
    --check) CHECK_ONLY=1 ;;
    -h|--help)
      cat <<'EOF'
本地测试环境脚本

  bash scripts/setup-local.sh           安装 Python / 前端依赖（旧版 Playwright 栈）
  bash scripts/setup-local.sh --start   安装完成后启动旧版前后端
  bash scripts/setup-local.sh --check   仅检查环境

推荐改用插件架构: bash scripts/setup-extension.sh --install

首次使用请先编辑 .env.local，填入 DEEPSEEK_API_KEY（仅旧版 Agent 需要）。
启动后访问:
  插件栈  bash scripts/dev-extension.sh
  旧版    前端 http://127.0.0.1:5173  API http://127.0.0.1:8000/docs
EOF
      exit 0
      ;;
    *)
      echo "未知参数: $arg (可用 --start / --check / --help)" >&2
      exit 1
      ;;
  esac
done

echo "=== Huoke 本地环境初始化 ==="
echo "项目目录: ${ROOT}"
echo ""

find_python() {
  local candidate ver major minor
  for candidate in \
    /opt/homebrew/bin/python3.12 \
    /opt/homebrew/bin/python3.11 \
    /usr/local/bin/python3.12 \
    /usr/local/bin/python3.11 \
    python3.12 \
    python3.11; do
    if command -v "$candidate" >/dev/null 2>&1; then
      ver="$("$candidate" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
      major="${ver%%.*}"
      minor="${ver#*.}"
      if (( major >= 3 && minor >= 11 )); then
        echo "$candidate"
        return 0
      fi
    fi
  done
  return 1
}

check_prerequisites() {
  local failed=0

  if PYTHON="$(find_python)"; then
    echo "  ✓ Python: $("$PYTHON" --version)"
  else
    echo "  ✗ 未找到 Python 3.11+ (brew install python@3.11)" >&2
    failed=1
  fi

  if command -v node >/dev/null 2>&1 && command -v npm >/dev/null 2>&1; then
    echo "  ✓ Node: $(node --version)  npm: $(npm --version)"
  else
    echo "  ✗ 未找到 node/npm (brew install node)" >&2
    failed=1
  fi

  if [[ "$(uname -s)" == "Darwin" ]]; then
    local chrome="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    if [[ -x "$chrome" ]]; then
      echo "  ✓ Chrome: $("$chrome" --version 2>/dev/null || echo "已安装")"
    else
      echo "  ✗ 未找到 Google Chrome: ${chrome}" >&2
      failed=1
    fi
  fi

  if [[ ! -f "$ROOT/.env.local" ]]; then
    echo "  ! 未找到 .env.local，将从 .env.local.example 复制"
  elif ! grep -qE '^DEEPSEEK_API_KEY=.+$' "$ROOT/.env.local" 2>/dev/null; then
    echo "  ! .env.local 中 DEEPSEEK_API_KEY 为空，Agent 功能将无法调用大模型"
  else
    echo "  ✓ .env.local 已配置"
  fi

  return "$failed"
}

ensure_env_file() {
  if [[ -f "$ROOT/.env.local" ]]; then
    return 0
  fi
  if [[ ! -f "$ROOT/.env.local.example" ]]; then
    echo "缺少 .env.local.example，无法生成 .env.local" >&2
    exit 1
  fi
  cp "$ROOT/.env.local.example" "$ROOT/.env.local"
  echo "  ✓ 已创建 .env.local（请编辑并填入 DEEPSEEK_API_KEY）"
}

setup_backend() {
  echo ""
  echo ">>> 安装后端依赖"
  PYTHON="$(find_python)"
  cd "$BACKEND_DIR"

  local need_install=0
  if [[ ! -d .venv ]]; then
    echo "  · 创建 Python 虚拟环境..."
    "$PYTHON" -m venv .venv
    need_install=1
  else
    local venv_py
    venv_py="$(.venv/bin/python -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || echo "0.0")"
    local venv_major="${venv_py%%.*}"
    local venv_minor="${venv_py#*.}"
    if (( venv_major < 3 || venv_minor < 11 )); then
      echo "  · 重建 Python 虚拟环境 (${venv_py} -> 3.11+)..."
      rm -rf .venv
      "$PYTHON" -m venv .venv
      need_install=1
    fi
  fi

  # shellcheck disable=SC1091
  source .venv/bin/activate

  if [[ "$need_install" == 1 ]] || ! python -c "import uvicorn" >/dev/null 2>&1; then
    echo "  · pip install -r requirements.txt ..."
    pip install -U pip setuptools wheel
    pip install -r requirements.txt
  else
    echo "  ✓ 后端依赖已就绪"
  fi
}

setup_frontend() {
  echo ""
  echo ">>> 安装前端依赖"
  cd "$FRONTEND_DIR"
  if [[ ! -d node_modules ]] || [[ ! -f node_modules/.package-lock.json ]]; then
    echo "  · npm install ..."
    npm install
  else
    echo "  ✓ 前端依赖已就绪"
  fi
}

if ! check_prerequisites; then
  echo ""
  echo "环境检查未通过，请先安装缺失项。" >&2
  exit 1
fi

if [[ "$CHECK_ONLY" == 1 ]]; then
  echo ""
  echo "环境检查通过。"
  exit 0
fi

ensure_env_file
setup_backend
setup_frontend

echo ""
echo "=== 安装完成 ==="
echo "  后端: backend/.venv"
echo "  前端: frontend/node_modules"
echo ""
echo "下一步:"
echo "  推荐（插件架构）:"
echo "    bash scripts/setup-extension.sh --install"
echo "    bash scripts/dev-extension.sh"
echo "  旧版 Playwright（仅实验）:"
echo "    编辑 .env.local，填入 DEEPSEEK_API_KEY"
echo "    bash scripts/dev.sh"
echo ""

if [[ "$START_AFTER_SETUP" == 1 ]]; then
  echo ">>> 启动前后端..."
  exec bash "$ROOT/scripts/dev.sh"
fi
