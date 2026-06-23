#!/usr/bin/env bash
# Tauri 桌面打包资源：Vue 静态 + local-service + Chrome 插件 zip（无 Python）
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
FRONTEND_DIR="$ROOT/frontend"
EXTENSION_DIR="$ROOT/extension"
BUNDLE_DIR="$ROOT/desktop/bundle"
LOCAL_SERVICE_DIR="$ROOT/local-service"

echo "=== Huoke Desktop Bundle ==="

echo ">>> 构建 Chrome 插件"
cd "$EXTENSION_DIR"
if [[ ! -d node_modules ]]; then npm install; fi
npm run build

echo ">>> 构建 local-service (release)"
cd "$LOCAL_SERVICE_DIR"
cargo build --release

echo ">>> 构建前端"
cd "$FRONTEND_DIR"
if [[ ! -d node_modules ]]; then
  if [[ -f package-lock.json ]]; then npm ci; else npm install; fi
fi
VITE_LOCAL_SERVICE_URL=http://127.0.0.1:18766 npm run build

if [[ ! -f "$FRONTEND_DIR/dist/index.html" ]]; then
  echo "frontend dist 缺失" >&2
  exit 1
fi

echo ">>> 组装 desktop/bundle"
rm -rf "$BUNDLE_DIR"
mkdir -p "$BUNDLE_DIR/runtime" "$BUNDLE_DIR/frontend-dist"

cp "$LOCAL_SERVICE_DIR/target/release/huoke-local-service" "$BUNDLE_DIR/runtime/"
chmod +x "$BUNDLE_DIR/runtime/huoke-local-service"

rsync -a "$FRONTEND_DIR/dist/" "$BUNDLE_DIR/frontend-dist/"

rsync -a "$EXTENSION_DIR/dist/" "$BUNDLE_DIR/extension/"

(
  cd "$EXTENSION_DIR/dist"
  zip -qr "$BUNDLE_DIR/huoke-extension.zip" .
)

APP_VERSION="$(node -p "require('$ROOT/package.json').version")"
EXT_VERSION="$(node -p "require('$EXTENSION_DIR/manifest.json').version")"
LS_VERSION="$(grep '^version' "$LOCAL_SERVICE_DIR/Cargo.toml" | head -1 | sed 's/.*\"\(.*\)\".*/\1/')"

cat > "$BUNDLE_DIR/BUNDLE_MANIFEST.json" <<EOF
{
  "kind": "huoke-desktop-bundle",
  "app_version": "$APP_VERSION",
  "extension_version": "$EXT_VERSION",
  "local_service_version": "$LS_VERSION",
  "runtime": "runtime/huoke-local-service",
  "frontend": "frontend-dist",
  "extension": "extension",
  "extension_zip": "huoke-extension.zip",
  "static_port": 18765,
  "local_service_port": 18766,
  "notes": "Vue static + Rust local-service + Chrome extension (auto-loaded on first run)."
}
EOF

echo ">>> 发布版本化产物到 dist/releases"
node "$ROOT/scripts/publish-release-artifacts.mjs" \
  --extension "$BUNDLE_DIR/huoke-extension.zip" \
  --local-service-macos "$BUNDLE_DIR/runtime/huoke-local-service"

echo "bundle 就绪: $BUNDLE_DIR"
echo "  - runtime/huoke-local-service"
echo "  - frontend-dist/"
echo "  - extension/"
echo "  - huoke-extension.zip"
echo "发布目录: $ROOT/dist/releases/"
echo "  - huoke-extension-v${EXT_VERSION}.zip"
echo "  - huoke-local-service-v${LS_VERSION}-macos"
echo "  - index.html"
