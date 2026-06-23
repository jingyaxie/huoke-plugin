#!/usr/bin/env bash
# macOS 桌面应用打包（Tauri NSIS/DMG）
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DESKTOP_DIR="$ROOT/desktop"

# shellcheck source=scripts/lib/common.sh
source "$ROOT/scripts/lib/common.sh"

if CHROME="$(find_chrome 2>/dev/null || true)" && [[ -n "$CHROME" ]]; then
  echo "Chrome: $("$CHROME" --version 2>/dev/null || true)"
else
  echo "警告: 未找到 Google Chrome。打包可继续，但用户需自行安装 Chrome 并加载插件。" >&2
fi

cd "$DESKTOP_DIR"
if [[ ! -d node_modules ]]; then
  if [[ -f package-lock.json ]]; then npm ci; else npm install; fi
fi

echo "打包 macOS 应用（Vue + local-service + extension.zip，无 Python）..."
npm run build

DMG_DIR="$DESKTOP_DIR/src-tauri/target/release/bundle/dmg"
APP_DIR="$DESKTOP_DIR/src-tauri/target/release/bundle/macos"

if ! compgen -G "$DMG_DIR/*.dmg" >/dev/null; then
  echo "错误: 未找到 DMG: $DMG_DIR/*.dmg" >&2
  exit 1
fi

echo ""
echo ">>> 发布版本化安装包到 dist/releases"
for dmg in "$DMG_DIR"/*.dmg; do
  node "$ROOT/scripts/publish-release-artifacts.mjs" --macos-dmg "$dmg"
done

echo ""
echo "构建完成。产物目录:"
echo "  Tauri: $APP_DIR/"
echo "  Tauri: $DMG_DIR/"
echo "  发布: $ROOT/dist/releases/"
ls -lh "$ROOT/dist/releases/"* 2>/dev/null || true
ls -lh "$DMG_DIR"/*.dmg "$APP_DIR"/*.app 2>/dev/null || true
