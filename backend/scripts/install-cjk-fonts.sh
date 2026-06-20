#!/bin/sh
# VNC/Chromium 容器默认 CJK 字体不足时，中文会显示为方框或空白。启动时补齐并刷新 fontconfig。
set -e

FONT_DIR="/usr/share/fonts/truetype/wqy"
MARKER="/var/lib/huoke/cjk-fonts.ready"

has_cjk_fonts() {
  if command -v fc-list >/dev/null 2>&1; then
    fc-list :lang=zh family 2>/dev/null | head -n 1 | grep -q .
    return
  fi
  test -f "$FONT_DIR/wqy-microhei.ttc" \
    || test -f /usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc \
    || test -f /usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc
}

refresh_cache() {
  if command -v fc-cache >/dev/null 2>&1; then
    fc-cache -fv >/dev/null 2>&1 || fc-cache -f >/dev/null 2>&1 || true
  fi
}

if has_cjk_fonts; then
  mkdir -p "$(dirname "$MARKER")"
  date >"$MARKER" 2>/dev/null || true
  exit 0
fi

if [ -f "$MARKER" ]; then
  echo "[fonts] WARN: marker exists but no CJK fonts detected; retry install" >&2
  rm -f "$MARKER"
fi

install_via_apt() {
  if [ "$(id -u)" != "0" ]; then
    return 1
  fi
  if ! command -v apt-get >/dev/null 2>&1; then
    return 1
  fi
  echo "[fonts] trying apt: fonts-noto-cjk fonts-wqy-microhei..."
  apt-get update -qq \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      fonts-noto-cjk fonts-wqy-microhei fonts-wqy-zenhei fontconfig \
    && rm -rf /var/lib/apt/lists/*
}

download() {
  url="$1"
  dest="$2"
  if command -v curl >/dev/null 2>&1; then
    curl -fsSL --connect-timeout 15 --max-time 120 -o "$dest" "$url"
    return
  fi
  if command -v wget >/dev/null 2>&1; then
    wget -q -O "$dest" "$url"
    return
  fi
  echo "[fonts] curl/wget unavailable" >&2
  return 1
}

install_via_download() {
  mkdir -p "$FONT_DIR"
  echo "[fonts] downloading wqy-microhei..."
  for url in \
    "https://cdn.jsdelivr.net/gh/anthonyfok/fonts-wqy-microhei@master/wqy-microhei.ttc" \
    "https://ghproxy.net/https://cdn.jsdelivr.net/gh/anthonyfok/fonts-wqy-microhei@master/wqy-microhei.ttc" \
    "https://mirror.ghproxy.com/https://cdn.jsdelivr.net/gh/anthonyfok/fonts-wqy-microhei@master/wqy-microhei.ttc"
  do
    if download "$url" "$FONT_DIR/wqy-microhei.ttc"; then
      return 0
    fi
  done
  return 1
}

if install_via_apt || install_via_download; then
  refresh_cache
else
  echo "[fonts] WARN: CJK font install failed" >&2
  exit 1
fi

if ! has_cjk_fonts; then
  echo "[fonts] WARN: install finished but fc-list still shows no :lang=zh fonts" >&2
  exit 1
fi

mkdir -p "$(dirname "$MARKER")"
date >"$MARKER"
echo "[fonts] CJK fonts ready"
