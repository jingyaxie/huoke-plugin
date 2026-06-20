#!/usr/bin/env bash
# 解析 Huoke 工程根目录（开发 / .app 打包后均可用）
set -euo pipefail

# 桌面版专用端口，避免与本地 dev 后端 (8000) 冲突导致 WebView 加载 API 404
HUOKE_DESKTOP_PORT="${HUOKE_DESKTOP_PORT:-18765}"
export HUOKE_DESKTOP_PORT

ensure_desktop_path() {
  export PATH="/usr/local/bin:/opt/homebrew/bin:$PATH"
}

resolve_huoke_root() {
  if [[ -n "${HUOKE_ROOT:-}" ]]; then
    if [[ -f "$HUOKE_ROOT/scripts/desktop-run-backend.sh" ]]; then
      echo "$HUOKE_ROOT"
      return
    fi
    if [[ -f "$HUOKE_ROOT/desktop-run-backend.sh" ]]; then
      echo "$HUOKE_ROOT"
      return
    fi
  fi
  local here="${BASH_SOURCE[1]:-${BASH_SOURCE[0]}}"
  while [[ -L "$here" ]]; do
    here="$(cd "$(dirname "$here")" && pwd)/$(readlink "$here")"
  done
  local dir
  dir="$(cd "$(dirname "$here")" && pwd)"
  if [[ -f "$dir/desktop-run-backend.sh" ]]; then
    echo "$dir"
    return
  fi
  if [[ -f "$dir/scripts/desktop-run-backend.sh" ]]; then
    echo "$dir"
    return
  fi
  if [[ -f "$dir/../scripts/desktop-run-backend.sh" ]]; then
    echo "$(cd "$dir/.." && pwd)"
    return
  fi
  echo "无法定位 Huoke 工程根目录" >&2
  exit 1
}

resolve_huoke_data_dir() {
  if [[ -n "${HUOKE_DATA_DIR:-}" ]]; then
    echo "$HUOKE_DATA_DIR"
    return
  fi
  local home="${HOME:-/tmp}"
  if [[ "$(uname -s)" == "Darwin" ]]; then
    echo "$home/Library/Application Support/com.huoke.desktop"
    return
  fi
  echo "$home/.local/share/huoke"
}

resolve_huoke_bundle_dir() {
  if [[ -n "${HUOKE_BUNDLE_DIR:-}" && -d "$HUOKE_BUNDLE_DIR/runtime" ]]; then
    echo "$HUOKE_BUNDLE_DIR"
    return
  fi
  local root
  root="$(resolve_huoke_root)"
  if [[ -d "$root/desktop/bundle/runtime" ]]; then
    echo "$root/desktop/bundle"
    return
  fi
  if [[ -d "$root/bundle/runtime" ]]; then
    echo "$root/bundle"
    return
  fi
  echo "$root"
}

# macOS / Linux 桌面启动脚本用；Windows 打包走 desktop-run-backend.ps1
find_chrome_executable() {
  local candidate
  case "$(uname -s)" in
    Darwin)
      candidate="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
      if [[ -x "$candidate" ]]; then
        printf '%s' "$candidate"
        return 0
      fi
      ;;
    Linux)
      for candidate in google-chrome google-chrome-stable chromium chromium-browser; do
        if command -v "$candidate" >/dev/null 2>&1; then
          printf '%s' "$candidate"
          return 0
        fi
      done
      ;;
  esac
  return 1
}
