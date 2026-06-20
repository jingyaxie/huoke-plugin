#!/usr/bin/env bash
# 开发脚本公共函数
set -euo pipefail

dev_repo_root() {
  local here="${BASH_SOURCE[1]:-${BASH_SOURCE[0]}}"
  while [[ -L "$here" ]]; do
    here="$(cd "$(dirname "$here")" && pwd)/$(readlink "$here")"
  done
  cd "$(dirname "$here")/.." && pwd
}

dev_port_listen() {
  lsof -iTCP:"$1" -sTCP:LISTEN -P -n >/dev/null 2>&1
}

dev_wait_health() {
  local url="$1"
  local label="$2"
  local log_file="${3:-}"
  for _ in $(seq 1 60); do
    if curl -sS -m 2 "$url" >/dev/null 2>&1; then
      echo "  ✓ ${label} 就绪"
      return 0
    fi
    sleep 1
  done
  if [[ -n "$log_file" ]]; then
    echo "  ✗ ${label} 启动超时，见 ${log_file}" >&2
  else
    echo "  ✗ ${label} 启动超时" >&2
  fi
  return 1
}

dev_wait_backend() {
  local port="${1:-8000}"
  local pid="$2"
  local timeout="${3:-90}"
  for _ in $(seq 1 "$timeout"); do
    if curl -fsS "http://127.0.0.1:${port}/api/health" >/dev/null 2>&1; then
      return 0
    fi
    if ! kill -0 "$pid" 2>/dev/null; then
      echo "后端进程异常退出" >&2
      return 1
    fi
    sleep 1
  done
  echo "后端启动超时" >&2
  return 1
}
