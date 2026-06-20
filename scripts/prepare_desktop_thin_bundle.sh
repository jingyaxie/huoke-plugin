#!/usr/bin/env bash
# Tauri 瘦壳打包：Vue 静态资源 + local-service + extension zip（无 Python）
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
FRONTEND_DIR="$ROOT/frontend"
EXTENSION_DIR="$ROOT/extension"
BUNDLE_DIR="$ROOT/desktop/bundle"
LOCAL_SERVICE_DIR="$ROOT/local-service"

echo "=== Huoke Desktop Thin Bundle ==="

echo ">>> 构建 Chrome 插件"
cd "$EXTENSION_DIR"
if [[ ! -d node_modules ]]; then
  npm install
fi
npm run build

echo ">>> 构建 local-service (release)"
cd "$LOCAL_SERVICE_DIR"
cargo build --release

echo ">>> 构建前端（插件架构）"
cd "$FRONTEND_DIR"
if [[ ! -d node_modules ]]; then
  if [[ -f package-lock.json ]]; then
    npm ci
  else
    npm install
  fi
fi
VITE_LOCAL_SERVICE_URL=http://127.0.0.1:18766 npm run build

if [[ ! -f "$FRONTEND_DIR/dist/index.html" ]]; then
  echo "frontend dist 缺失" >&2
  exit 1
fi

echo ">>> 组装 bundle"
rm -rf "$BUNDLE_DIR"
mkdir -p "$BUNDLE_DIR/runtime" "$BUNDLE_DIR/frontend-dist"

cp "$LOCAL_SERVICE_DIR/target/release/huoke-local-service" "$BUNDLE_DIR/runtime/"
chmod +x "$BUNDLE_DIR/runtime/huoke-local-service"

rsync -a "$FRONTEND_DIR/dist/" "$BUNDLE_DIR/frontend-dist/"

(
  cd "$EXTENSION_DIR/dist"
  zip -qr "$BUNDLE_DIR/huoke-extension.zip" .
)

cat > "$BUNDLE_DIR/BUNDLE_MANIFEST.json" <<EOF
{
  "kind": "huoke-desktop-thin-bundle",
  "runtime": "runtime/huoke-local-service",
  "frontend": "frontend-dist",
  "extension_zip": "huoke-extension.zip",
  "static_port": 18765,
  "local_service_port": 18766,
  "notes": "Thin desktop shell: Vue static + Rust local-service. Load huoke-extension.zip in Chrome."
}
EOF

echo "bundle 就绪: $BUNDLE_DIR"
echo "  - runtime/huoke-local-service"
echo "  - frontend-dist/"
echo "  - huoke-extension.zip"
