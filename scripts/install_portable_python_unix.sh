#!/usr/bin/env bash
# 下载 python-build-standalone 可移植 Python，并安装后端依赖（Mac/Linux 桌面完整包）
set -euo pipefail

TARGET_DIR="${1:?target dir required}"
REQUIREMENTS_FILE="${2:?requirements.txt required}"
PYTHON_VERSION="${PYTHON_VERSION:-3.12.9}"
RELEASE_TAG="${PYTHON_STANDALONE_RELEASE:-20250205}"

detect_platform_triple() {
  local os arch
  os="$(uname -s | tr '[:upper:]' '[:lower:]')"
  arch="$(uname -m)"
  case "$os" in
    darwin)
      case "$arch" in
        arm64) echo "aarch64-apple-darwin" ;;
        x86_64) echo "x86_64-apple-darwin" ;;
        *) echo "unsupported macOS arch: $arch" >&2; exit 1 ;;
      esac
      ;;
    linux)
      case "$arch" in
        x86_64) echo "x86_64-unknown-linux-gnu" ;;
        aarch64) echo "aarch64-unknown-linux-gnu" ;;
        *) echo "unsupported Linux arch: $arch" >&2; exit 1 ;;
      esac
      ;;
    *)
      echo "unsupported OS: $os" >&2
      exit 1
      ;;
  esac
}

find_python_bin() {
  local root="$1"
  local candidate
  for candidate in \
    "$root/bin/python3.12" \
    "$root/bin/python3" \
    "$root/python/bin/python3.12" \
    "$root/python/bin/python3"; do
    if [[ -x "$candidate" ]]; then
      printf '%s' "$candidate"
      return 0
    fi
  done
  return 1
}

PLATFORM="$(detect_platform_triple)"
TARBALL="cpython-${PYTHON_VERSION}+${RELEASE_TAG}-${PLATFORM}-install_only.tar.gz"
URL="https://github.com/astral-sh/python-build-standalone/releases/download/${RELEASE_TAG}/${TARBALL}"

tmpdir="$(mktemp -d)"
cleanup() { rm -rf "$tmpdir"; }
trap cleanup EXIT

echo "Downloading portable Python ${PYTHON_VERSION} (${PLATFORM})..."
curl -fsSL "$URL" -o "$tmpdir/python.tar.gz"
mkdir -p "$tmpdir/extract"
tar -xzf "$tmpdir/python.tar.gz" -C "$tmpdir/extract"

extract_root="$tmpdir/extract"
nested="$(find "$tmpdir/extract" -mindepth 1 -maxdepth 1 -type d | head -n 1 || true)"
if [[ -n "$nested" && -z "$(find_python_bin "$tmpdir/extract" 2>/dev/null || true)" ]]; then
  extract_root="$nested"
fi

python_bin="$(find_python_bin "$extract_root")"
if [[ -z "$python_bin" ]]; then
  echo "python binary not found in standalone archive" >&2
  exit 1
fi

runtime_home="$(cd "$(dirname "$python_bin")/.." && pwd)"
rm -rf "$TARGET_DIR"
mkdir -p "$TARGET_DIR"
rsync -a "$runtime_home/" "$TARGET_DIR/"

python_bin="$(find_python_bin "$TARGET_DIR")"
if [[ -z "$python_bin" ]]; then
  echo "failed to stage portable python under $TARGET_DIR" >&2
  exit 1
fi

echo "Installing pip + backend requirements into portable Python..."
"$python_bin" -m ensurepip --upgrade
"$python_bin" -m pip install --disable-pip-version-check -U pip setuptools wheel
"$python_bin" -m pip install --disable-pip-version-check -r "$REQUIREMENTS_FILE"
script_root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
echo "Verifying system Chrome via Playwright channel..."
"$python_bin" "$script_root/verify_playwright_bundle.py"

"$python_bin" -c "import uvicorn, fastapi, sqlalchemy, playwright; print('portable python smoke test ok')"

echo "Portable Python ready: $python_bin"
