#!/usr/bin/env bash
# 不依赖 create-dmg，生成带「应用程序」快捷方式的 macOS 安装镜像
set -euo pipefail

if [[ $# -lt 2 ]]; then
  echo "用法: $0 <App.app> <输出.dmg> [卷标名称]" >&2
  exit 1
fi

APP_PATH="$1"
OUTPUT_DMG="$2"
VOLUME_NAME="${3:-盈小蚁}"

if [[ ! -d "$APP_PATH" ]]; then
  echo "错误: 找不到应用包: $APP_PATH" >&2
  exit 1
fi

OUTPUT_DIR="$(cd "$(dirname "$OUTPUT_DMG")" && pwd)"
OUTPUT_NAME="$(basename "$OUTPUT_DMG")"
STAGING="$(mktemp -d "${TMPDIR:-/tmp}/huoke-dmg.XXXXXX")"

cleanup() {
  rm -rf "$STAGING"
}
trap cleanup EXIT

cp -R "$APP_PATH" "$STAGING/"
ln -s /Applications "$STAGING/Applications"

rm -f "$OUTPUT_DIR/$OUTPUT_NAME"
hdiutil create \
  -volname "$VOLUME_NAME" \
  -srcfolder "$STAGING" \
  -ov \
  -format UDZO \
  "$OUTPUT_DIR/$OUTPUT_NAME"

# 去掉下载隔离标记，减少「无法打开」误报（用户侧仍可能需要右键打开一次）
xattr -cr "$OUTPUT_DIR/$OUTPUT_NAME" 2>/dev/null || true

echo "已生成 DMG: $OUTPUT_DIR/$OUTPUT_NAME"
