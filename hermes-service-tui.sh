#!/usr/bin/env bash
# Bootstrap, run, or uninstall Hermes Service TUI on Linux/WSL2.
set -Eeuo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
VENV_DIR="$PROJECT_DIR/.venv"
PYTHON="${PYTHON:-python3}"
APP_MODULE="hermes_service_tui"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
UNITS=(
  "hermes-gateway.service"
  "hermes-dashboard.service"
  "hermes.target"
)

usage() {
  cat <<'EOF'
Usage: ./hermes-service-tui.sh [OPTION]

Bootstrap and launch Hermes Service TUI from this checkout.

Options:
  --uninstall  Stop and remove the TUI-managed user services and local .venv.
  --yes        Do not ask for confirmation with --uninstall.
  -h, --help   Show this help.
EOF
}

info() { printf '==> %s\n' "$*"; }
warn() { printf 'WARNING: %s\n' "$*" >&2; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

require_supported_platform() {
  local kernel init
  kernel="$(uname -s)"
  if [[ "$kernel" != "Linux" ]]; then
    die "Unsupported OS: $kernel. Hermes Service TUI supports Linux and WSL2 only; no changes were made."
  fi

  init="$(ps -p 1 -o comm= 2>/dev/null | tr -d '[:space:]' || true)"
  if [[ "$init" != "systemd" ]]; then
    die "systemd is required (PID 1 is '${init:-unknown}'). Enable systemd, then restart WSL/Linux. No changes were made."
  fi

  command -v systemctl >/dev/null 2>&1 || die "systemctl is required but was not found. No changes were made."
  systemctl --user show-environment >/dev/null 2>&1 || die "The systemd user manager is unavailable. Start a user systemd session, then retry. No changes were made."
}

python_is_supported() {
  command -v "$PYTHON" >/dev/null 2>&1 || return 1
  "$PYTHON" -c 'import sys; raise SystemExit(not (sys.version_info >= (3, 10)))' >/dev/null 2>&1
}

ensure_python() {
  if python_is_supported; then
    return
  fi

  die "Python 3.10+ is required but '${PYTHON}' is unavailable or too old. Install Python 3.10+ and its venv module, then retry."
}

ensure_hermes() {
  command -v hermes >/dev/null 2>&1 || die "Hermes CLI is required but was not found in PATH. Install/configure Hermes Agent, then retry."
}

ensure_project_files() {
  [[ -f "$PROJECT_DIR/pyproject.toml" ]] || die "Missing required file: $PROJECT_DIR/pyproject.toml"
  [[ -d "$PROJECT_DIR/src/$APP_MODULE" ]] || die "Missing required application directory: $PROJECT_DIR/src/$APP_MODULE"
}

create_or_update_environment() {
  if [[ ! -x "$VENV_DIR/bin/python" ]]; then
    info "Creating isolated Python environment in .venv"
    "$PYTHON" -m venv "$VENV_DIR" || die "Could not create .venv. Install the Python venv module and retry."
  fi

  info "Installing/updating project dependencies"
  "$VENV_DIR/bin/python" -m pip install --disable-pip-version-check --editable "$PROJECT_DIR" \
    || die "Dependency installation failed. Check network access and Python pip, then retry."
}

confirm_uninstall() {
  [[ "${ASSUME_YES:-false}" == "true" ]] && return
  [[ -t 0 ]] || die "--uninstall requires an interactive terminal; use --yes to confirm non-interactively."

  printf 'Remove TUI-managed user services and %s? [y/N] ' "$VENV_DIR"
  local answer
  read -r answer
  [[ "$answer" =~ ^[Yy]([Ee][Ss])?$ ]] || {
    info "Uninstall cancelled."
    exit 0
  }
}

uninstall() {
  require_supported_platform
  confirm_uninstall

  info "Stopping and disabling TUI-managed user services"
  systemctl --user stop hermes.target 2>/dev/null || true
  systemctl --user disable "${UNITS[@]}" 2>/dev/null || true

  local unit
  for unit in "${UNITS[@]}"; do
    rm -f -- "$UNIT_DIR/$unit"
  done
  systemctl --user daemon-reload
  systemctl --user reset-failed 2>/dev/null || true

  if [[ -d "$VENV_DIR" ]]; then
    rm -rf -- "$VENV_DIR"
  fi

  info "Uninstall complete. Hermes itself and its configuration were not removed."
}

main() {
  local uninstall_requested=false
  while (($#)); do
    case "$1" in
      --uninstall) uninstall_requested=true ;;
      --yes) ASSUME_YES=true ;;
      -h|--help) usage; exit 0 ;;
      *) usage >&2; die "Unknown option: $1" ;;
    esac
    shift
  done

  if [[ "$uninstall_requested" == "true" ]]; then
    uninstall
    exit 0
  fi

  # Validate the OS before creating files or installing any dependency.
  require_supported_platform
  ensure_project_files
  ensure_python
  ensure_hermes
  create_or_update_environment

  info "Launching Hermes Service TUI"
  exec "$VENV_DIR/bin/python" -m "$APP_MODULE"
}

main "$@"
