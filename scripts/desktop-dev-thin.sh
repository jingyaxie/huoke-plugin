#!/usr/bin/env bash
# Tauri 瘦壳开发：启动 static(18765) + local-service(18766)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PORT_STATIC="${HUOKE_DESKTOP_PORT:-18765}"
PORT_LOCAL="${HUOKE_LOCAL_PORT:-18766}"

# shellcheck source=scripts/dev-common.sh
source "$ROOT/scripts/dev-common.sh"

kill_port_if_huoke_backend() {
  local port="$1"
  if [[ -f "$ROOT/scripts/desktop_port_guard.py" ]]; then
    python3 "$ROOT/scripts/desktop_port_guard.py" --port "$port" --kill || true
  fi
}

kill_port_if_huoke_backend "$PORT_STATIC"
kill_port_if_huoke_backend "$PORT_LOCAL"

if [[ ! -f "$ROOT/frontend/dist/index.html" ]]; then
  echo "构建前端 dist..."
  cd "$ROOT/frontend"
  VITE_LOCAL_SERVICE_URL="http://127.0.0.1:${PORT_LOCAL}" npm run build
fi

if [[ ! -x "$ROOT/local-service/target/debug/huoke-local-service" ]] \
  && [[ ! -x "$ROOT/local-service/target/release/huoke-local-service" ]]; then
  echo "编译 local-service..."
  (cd "$ROOT/local-service" && cargo build)
fi

LS_BIN="$ROOT/local-service/target/debug/huoke-local-service"
if [[ ! -x "$LS_BIN" ]]; then
  LS_BIN="$ROOT/local-service/target/release/huoke-local-service"
fi

HUOKE_DATA_DIR="${HUOKE_DATA_DIR:-$ROOT/storage/local-service}" \
  HUOKE_LOCAL_PORT="$PORT_LOCAL" \
  "$LS_BIN" &
LS_PID=$!

python3 - <<PY &
import http.server
import os
import socketserver
from pathlib import Path

root = Path("${ROOT}/frontend/dist")
os.chdir(root)
port = int("${PORT_STATIC}")

class Handler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        path = self.path.split("?", 1)[0]
        target = root / path.lstrip("/")
        if path != "/" and target.is_file():
            return super().do_GET()
        self.path = "/index.html"
        return super().do_GET()

    def log_message(self, format, *args):
        return

with socketserver.TCPServer(("127.0.0.1", port), Handler) as httpd:
    print(f"desktop static dev server on http://127.0.0.1:{port}")
    httpd.serve_forever()
PY
STATIC_PID=$!

cleanup() {
  kill "$LS_PID" "$STATIC_PID" 2>/dev/null || true
}
trap cleanup EXIT

echo "等待服务就绪..."
for _ in $(seq 1 60); do
  if curl -fsS "http://127.0.0.1:${PORT_STATIC}/" >/dev/null 2>&1 \
    && curl -fsS "http://127.0.0.1:${PORT_LOCAL}/health" >/dev/null 2>&1; then
    echo "瘦壳 dev 就绪: UI=${PORT_STATIC} local-service=${PORT_LOCAL}"
    exit 0
  fi
  if ! kill -0 "$LS_PID" 2>/dev/null; then
    echo "local-service 启动失败" >&2
    exit 1
  fi
  sleep 0.5
done

echo "瘦壳 dev 启动超时" >&2
exit 1
