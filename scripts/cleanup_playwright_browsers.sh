#!/usr/bin/env bash
# 清理 Playwright 内置 Chromium 缓存（项目已改为仅使用系统 Chrome）
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
FREED_KB=0

measure_kb() {
  local path="$1"
  if [[ -e "$path" ]]; then
    du -sk "$path" 2>/dev/null | cut -f1
  else
    echo 0
  fi
}

remove_dir() {
  local path="$1"
  local label="$2"
  if [[ ! -e "$path" ]]; then
    return 0
  fi
  local before
  before="$(measure_kb "$path")"
  echo "删除 $label: $path (${before}KB)"
  rm -rf "$path"
  FREED_KB=$((FREED_KB + before))
}

echo "==> 检查项目内 playwright-browsers 目录"
while IFS= read -r dir; do
  [[ -n "$dir" ]] || continue
  remove_dir "$dir" "bundled playwright-browsers"
done < <(find "$ROOT" -type d -name 'playwright-browsers' 2>/dev/null)

echo "==> 卸载 Playwright 内置浏览器缓存"
PY=""
for candidate in \
  "$ROOT/backend/.venv/bin/python" \
  "$ROOT/desktop/bundle/runtime/python/bin/python3.12" \
  "$ROOT/desktop/bundle/runtime/python/bin/python3" \
  python3; do
  if [[ -x "$candidate" ]] && "$candidate" -c "import playwright" >/dev/null 2>&1; then
    PY="$candidate"
    break
  fi
done

if [[ -n "$PY" ]]; then
  for cache in \
    "${HOME}/Library/Caches/ms-playwright" \
    "${HOME}/.cache/ms-playwright"; do
    if [[ -d "$cache" ]]; then
      before="$(measure_kb "$cache")"
      echo "Playwright uninstall via $PY (cache was ${before}KB)"
      "$PY" -m playwright uninstall --all || true
      if [[ -d "$cache" ]]; then
        after="$(measure_kb "$cache")"
        FREED_KB=$((FREED_KB + before - after))
      else
        FREED_KB=$((FREED_KB + before))
      fi
    fi
  done
else
  echo "未找到带 playwright 的 Python，跳过 uninstall"
  for cache in \
    "${HOME}/Library/Caches/ms-playwright" \
    "${HOME}/.cache/ms-playwright"; do
    remove_dir "$cache" "Playwright cache"
  done
fi

FREED_MB=$(( (FREED_KB + 1023) / 1024 ))
echo "==> 完成，约释放 ${FREED_MB} MB"
