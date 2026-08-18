#!/usr/bin/env bash
# Build a self-contained Linux/WSL executable with PyInstaller.
set -Eeuo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
PYTHON="${PYTHON:-$PROJECT_DIR/.venv/bin/python}"
DIST_DIR="$PROJECT_DIR/dist"
BUILD_DIR="$PROJECT_DIR/build/pyinstaller"
RELEASE_DIR="$PROJECT_DIR/release"

info() { printf '==> %s\n' "$*"; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

[[ "$(uname -s)" == "Linux" ]] || die "This PyInstaller target builds Linux/WSL binaries only. Build on each target OS."
[[ -x "$PYTHON" ]] || die "Python environment not found: $PYTHON. Run ./hermes-service-tui.sh first."
[[ -f "$PROJECT_DIR/pyproject.toml" ]] || die "Missing pyproject.toml."
[[ -d "$PROJECT_DIR/src/hermes_service_tui" ]] || die "Missing application source directory."
VERSION="$("$PYTHON" -c 'import sys, tomllib; print(tomllib.load(open(sys.argv[1], "rb"))["project"]["version"])' "$PROJECT_DIR/pyproject.toml")"
[[ -n "$VERSION" ]] || die "Could not read the project version from pyproject.toml."

if [[ "${SKIP_BUILD_INSTALL:-0}" != "1" ]]; then
  info "Installing the PyInstaller build dependency"
  "$PYTHON" -m pip install --disable-pip-version-check --editable "$PROJECT_DIR[build]"
else
  info "Using the existing build environment"
fi

info "Building hermes-service-tui"
rm -rf -- "$BUILD_DIR" "$DIST_DIR"
"$PYTHON" -m PyInstaller \
  --noconfirm \
  --clean \
  --onefile \
  --name hermes-service-tui \
  --paths "$PROJECT_DIR/src" \
  --collect-all textual \
  --distpath "$DIST_DIR" \
  --workpath "$BUILD_DIR" \
  "$PROJECT_DIR/scripts/pyinstaller_entry.py"

ARTIFACT="$DIST_DIR/hermes-service-tui"
[[ -x "$ARTIFACT" ]] || die "PyInstaller did not produce an executable: $ARTIFACT"
PACKAGE_NAME="hermes-service-tui-${VERSION}-linux-x86_64"
PACKAGE_DIR="$RELEASE_DIR/$PACKAGE_NAME"
ARCHIVE="$RELEASE_DIR/$PACKAGE_NAME.tar.gz"

rm -rf -- "$PACKAGE_DIR"
mkdir -p -- "$PACKAGE_DIR"
install -m 0755 "$ARTIFACT" "$PACKAGE_DIR/hermes-service-tui"
install -m 0644 "$PROJECT_DIR/README.md" "$PROJECT_DIR/LICENSE" "$PACKAGE_DIR/"
tar -C "$RELEASE_DIR" -czf "$ARCHIVE" "$PACKAGE_NAME"
sha256sum "$ARCHIVE" > "$ARCHIVE.sha256"
rm -rf -- "$PACKAGE_DIR"

info "Built: $ARTIFACT"
info "Packaged: $ARCHIVE"
info "Checksum: $ARCHIVE.sha256"
