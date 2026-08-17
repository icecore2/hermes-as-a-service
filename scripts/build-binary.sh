#!/usr/bin/env bash
# Build a self-contained Linux/WSL executable with PyInstaller.
set -Eeuo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
PYTHON="${PYTHON:-$PROJECT_DIR/.venv/bin/python}"
DIST_DIR="$PROJECT_DIR/dist"
BUILD_DIR="$PROJECT_DIR/build/pyinstaller"

info() { printf '==> %s\n' "$*"; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

[[ "$(uname -s)" == "Linux" ]] || die "This PyInstaller target builds Linux/WSL binaries only. Build on each target OS."
[[ -x "$PYTHON" ]] || die "Python environment not found: $PYTHON. Run ./hermes-service-tui.sh first."
[[ -f "$PROJECT_DIR/pyproject.toml" ]] || die "Missing pyproject.toml."
[[ -d "$PROJECT_DIR/src/hermes_service_tui" ]] || die "Missing application source directory."

info "Installing the PyInstaller build dependency"
"$PYTHON" -m pip install --disable-pip-version-check --editable "$PROJECT_DIR[build]"

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
info "Built: $ARTIFACT"
info "Run: $ARTIFACT"
