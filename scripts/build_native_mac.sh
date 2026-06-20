#!/usr/bin/env bash
# macOS 原生桌面应用一键打包（Tauri beforeBuildCommand 会自动执行 prepare_desktop_bundle.sh）
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DESKTOP_DIR="$ROOT/desktop"

CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
if [[ ! -x "$CHROME" ]]; then
  echo "警告: 未找到 Google Chrome。构建可继续，但目标机器运行获客自动化时需安装 Chrome。" >&2
else
  echo "Chrome: $("$CHROME" --version 2>/dev/null || true)"
fi

cd "$DESKTOP_DIR"
if [[ ! -d node_modules ]]; then
  if [[ -f package-lock.json ]]; then
    npm ci
  else
    npm install
  fi
fi

echo "打包 macOS 原生应用 (.app / .dmg)..."
echo "使用瘦壳 bundle（Vue + local-service + extension.zip），无 Python/Playwright..."
npm run build

DMG_DIR="$DESKTOP_DIR/src-tauri/target/release/bundle/dmg"
APP_DIR="$DESKTOP_DIR/src-tauri/target/release/bundle/macos"

echo ""
echo "构建完成。产物目录:"
echo "  $APP_DIR/"
echo "  $DMG_DIR/"

if ! compgen -G "$DMG_DIR/*.dmg" >/dev/null; then
  echo "错误: 未找到 DMG 安装包: $DMG_DIR/*.dmg" >&2
  exit 1
fi

ls -lh "$DMG_DIR"/*.dmg "$APP_DIR"/*.app 2>/dev/null || true
