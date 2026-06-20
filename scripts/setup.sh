#!/usr/bin/env bash
# 环境初始化：Rust local-service + Chrome 插件 + 前端依赖
# 用法:
#   bash scripts/setup.sh              # 检查 + 安装 + 构建
#   bash scripts/setup.sh --install    # 同上（npm run setup）
#   bash scripts/setup.sh --check      # 仅检查
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=scripts/lib/common.sh
source "$ROOT/scripts/lib/common.sh"

EXTENSION_DIR="$ROOT/extension"
FRONTEND_DIR="$ROOT/frontend"
LOCAL_SERVICE_DIR="$ROOT/local-service"
PORT="${HUOKE_LOCAL_PORT:-18766}"
CHECK_ONLY=0
DO_INSTALL=0

for arg in "$@"; do
  case "$arg" in
    --install) DO_INSTALL=1 ;;
    --check) CHECK_ONLY=1 ;;
    -h|--help)
      cat <<'EOF'
Huoke 插件架构环境脚本

  bash scripts/setup.sh              检查并安装依赖、构建插件与 local-service
  bash scripts/setup.sh --install    同上
  bash scripts/setup.sh --check      仅检查环境

启动开发: npm run dev
打包桌面: npm run bundle  或  npm run build:mac / build:win
EOF
      exit 0
      ;;
    *)
      echo "未知参数: $arg (可用 --install / --check / --help)" >&2
      exit 1
      ;;
  esac
done

if [[ "$CHECK_ONLY" == "0" ]]; then
  DO_INSTALL=1
fi

echo "=== Huoke 环境初始化 ==="
echo "项目目录: ${ROOT}"
echo ""

PASS=0
FAIL=0

ok()   { echo "  ✓ $*"; PASS=$((PASS + 1)); }
bad()  { echo "  ✗ $*" >&2; FAIL=$((FAIL + 1)); }
skip() { echo "  ~ $*"; }

echo "[检查] 基础工具"

if command -v cargo >/dev/null 2>&1; then
  ok "Rust: $(rustc --version 2>/dev/null | head -1)"
else
  bad "未找到 cargo — 安装: https://rustup.rs"
fi

if command -v node >/dev/null 2>&1 && command -v npm >/dev/null 2>&1; then
  ok "Node: $(node --version)  npm: $(npm --version)"
else
  bad "未找到 node/npm"
fi

if CHROME="$(find_chrome 2>/dev/null || true)" && [[ -n "$CHROME" ]]; then
  ok "Chrome: $("$CHROME" --version 2>/dev/null | head -1)"
else
  skip "未检测到 Chrome（插件需在 Chrome 中加载 extension/dist）"
fi

if [[ -f "$ROOT/.env.local" ]]; then
  ok ".env.local 存在"
else
  skip ".env.local 缺失 — 可选: cp .env.local.example .env.local"
fi

echo ""

if [[ "$CHECK_ONLY" == "1" ]]; then
  echo "检查完成: ${PASS} 通过, ${FAIL} 失败"
  [[ "$FAIL" -eq 0 ]]
  exit $?
fi

if [[ "$FAIL" -gt 0 ]]; then
  echo "请先解决上述失败项后再运行 --install" >&2
  exit 1
fi

if [[ "$DO_INSTALL" == "1" ]]; then
  echo "[安装] Chrome 插件 (extension/)"
  cd "$EXTENSION_DIR"
  if [[ ! -d node_modules ]]; then npm install; fi
  npm run build
  ok "extension/dist 已构建"
  echo ""

  echo "[安装] 前端依赖 (frontend/)"
  cd "$FRONTEND_DIR"
  if [[ ! -d node_modules ]]; then
    if [[ -f package-lock.json ]]; then npm ci; else npm install; fi
  fi
  ok "frontend node_modules 就绪"
  echo ""

  echo "[构建] local-service (debug)"
  cd "$LOCAL_SERVICE_DIR"
  cargo build
  ok "local-service debug 二进制已构建"
  echo ""
fi

mkdir -p "$ROOT/storage/extension-dev"

echo "下一步:"
echo "  1. npm run dev"
echo "  2. Chrome → chrome://extensions → 加载 ${EXTENSION_DIR}/dist"
echo "  3. 打开抖音页面，curl http://127.0.0.1:${PORT}/bridge/status"
echo ""
echo "验证: npm run verify"
