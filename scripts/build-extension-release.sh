#!/usr/bin/env bash
# 仅构建 Chrome 插件并发布到 dist/releases/
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
EXTENSION_DIR="$ROOT/extension"
STAGING_ZIP="$ROOT/dist/.staging/huoke-extension.zip"

echo "=== Huoke Extension Release ==="

cd "$EXTENSION_DIR"
if [[ ! -d node_modules ]]; then npm install; fi
npm run build

mkdir -p "$(dirname "$STAGING_ZIP")"
rm -f "$STAGING_ZIP"
(
  cd "$EXTENSION_DIR/dist"
  zip -qr "$STAGING_ZIP" .
)

node "$ROOT/scripts/publish-release-artifacts.mjs" --extension "$STAGING_ZIP"

echo ""
echo "插件发布完成: dist/releases/huoke-extension-v*.zip"
echo "下载页: dist/releases/index.html"
