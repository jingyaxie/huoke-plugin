#!/usr/bin/env bash
# Huoke 脚本公共函数（插件架构，无 Python 依赖）
set -euo pipefail

huoke_root() {
  local here="${BASH_SOURCE[1]:-${BASH_SOURCE[0]}}"
  while [[ -L "$here" ]]; do
    here="$(cd "$(dirname "$here")" && pwd)/$(readlink "$here")"
  done
  cd "$(dirname "$here")/.." && pwd
}

port_listening() {
  lsof -iTCP:"$1" -sTCP:LISTEN -P -n >/dev/null 2>&1
}

kill_port() {
  local port="$1"
  local pids
  pids="$(lsof -tiTCP:"${port}" -sTCP:LISTEN 2>/dev/null || true)"
  if [[ -n "$pids" ]]; then
    # shellcheck disable=SC2086
    kill $pids 2>/dev/null || true
    sleep 0.3
  fi
}

wait_url() {
  local url="$1"
  local label="${2:-$url}"
  local attempts="${3:-60}"
  for _ in $(seq 1 "$attempts"); do
    if curl -fsS -m 2 "$url" >/dev/null 2>&1; then
      echo "  ✓ ${label} 就绪"
      return 0
    fi
    sleep 0.5
  done
  echo "  ✗ ${label} 启动超时 (${url})" >&2
  return 1
}

find_chrome() {
  local candidate
  case "$(uname -s)" in
    Darwin)
      candidate="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
      if [[ -x "$candidate" ]]; then
        echo "$candidate"
        return 0
      fi
      ;;
    Linux)
      for candidate in google-chrome google-chrome-stable chromium chromium-browser; do
        if command -v "$candidate" >/dev/null 2>&1; then
          echo "$candidate"
          return 0
        fi
      done
      ;;
  esac
  return 1
}
