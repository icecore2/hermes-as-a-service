# Hermes Service TUI

A small dynamic terminal UI for managing Hermes Agent's **Gateway / Telegram** and **Web Dashboard** as `systemd --user` services under WSL2 or Linux.

## Features

- Detects the current `hermes` executable automatically.
- Shows Gateway and Dashboard state, enablement, PID, and dashboard port state.
- Start / stop / restart the selected service.
- Generates and updates `~/.config/systemd/user/` unit files.
- Uses `hermes gateway run --external-supervisor` so systemd owns restart behavior.
- Uses `hermes dashboard --host 127.0.0.1 --port 9119 --no-open`.
- Shows recent `journalctl --user` logs inside the TUI.
- Refreshes service state automatically every 2 seconds.

## Prerequisites

WSL2 must be using systemd:

```bash
ps -p 1 -o comm=
```

Expected:

```text
systemd
```

Hermes must already be installed and available in PATH:

```bash
command -v hermes
```

## Quick start (recommended)

Run the staged launcher from the repository root:

```bash
./hermes-service-tui.sh
```

It validates the host **before changing anything**:

- Supports Linux and WSL2 only; it exits without installing on unsupported OSes.
- Requires `systemd` as PID 1 and an available `systemctl --user` manager.
- Requires Hermes in `PATH` and Python 3.10+.
- Creates a project-local `.venv` when missing and installs/updates the package dependencies there.
- Launches the TUI only after all checks succeed.

To remove this TUI's OS-level user services and its local virtual environment:

```bash
./hermes-service-tui.sh --uninstall
```

The uninstall command stops/disables and removes only these user unit files:

```text
~/.config/systemd/user/hermes-gateway.service
~/.config/systemd/user/hermes-dashboard.service
~/.config/systemd/user/hermes.target
```

It does **not** remove Hermes Agent or `~/.hermes`. Use `--yes` for a non-interactive uninstall.

## Manual development setup

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
python -m hermes_service_tui
```

## Controls

| Key | Action |
|---|---|
| `↑` / `↓` | Select Gateway or Dashboard |
| `i` | Install/update systemd units |
| `s` | Start selected service |
| `x` | Stop selected service |
| `e` | Restart selected service |
| `l` | Refresh selected service logs |
| `r` | Refresh status |
| `q` | Quit |

The same actions are available through buttons.

## How to: install and start the services

1. Launch the TUI:
   ```bash
   ./hermes-service-tui.sh
   ```
2. Select **Gateway / Telegram** or **Dashboard** with `↑` / `↓`.
3. Press `i` to create or update the three systemd user unit files.
4. Press `s` to start the selected service. Repeat for the other service.
5. Open the dashboard at [http://127.0.0.1:9119](http://127.0.0.1:9119).

The TUI writes these user-level units and does **not** edit Hermes configuration, `.env`, tokens, or `config.yaml`:

```text
~/.config/systemd/user/hermes-gateway.service
~/.config/systemd/user/hermes-dashboard.service
~/.config/systemd/user/hermes.target
```

## How to: manage services from the terminal

Use the target to control both services together:

```bash
# Start both
systemctl --user start hermes.target

# Stop both
systemctl --user stop hermes.target

# Show current state
systemctl --user status hermes.target
```

Manage one service when needed:

```bash
# Restart the dashboard after a problem
systemctl --user restart hermes-dashboard.service

# Follow Gateway / Telegram logs
journalctl --user -u hermes-gateway.service -f

# Read the latest dashboard logs
journalctl --user -u hermes-dashboard.service -n 80 --no-pager
```

## How to: run services after login / reboot

The TUI enables the units during **Install/Update**. Enable lingering if you also want the user service manager to run without an active interactive login:

```bash
sudo loginctl enable-linger "$USER"
```

Verify it:

```bash
loginctl show-user "$USER" -p Linger
```

## How to: uninstall safely

Remove only the systemd units managed by this project and the project-local Python environment:

```bash
./hermes-service-tui.sh --uninstall
```

For scripts or CI, bypass the confirmation prompt:

```bash
./hermes-service-tui.sh --uninstall --yes
```

This preserves the Hermes CLI and `~/.hermes` data. It does not delete tokens, profiles, or Hermes configuration.

## How to: troubleshoot

### WSL reports that systemd is unavailable

The launcher exits without making changes when PID 1 is not `systemd`. In your WSL distribution, add this to `/etc/wsl.conf`:

```ini
# /etc/wsl.conf
[boot]
systemd=true
```

Then run this **from Windows PowerShell**, not WSL:

```powershell
wsl --shutdown
```

Open a new WSL terminal and confirm:

```bash
ps -p 1 -o comm=
# expected: systemd
```

### `Hermes CLI is required but was not found`

Install or repair Hermes Agent, then open a new shell and confirm it is discoverable:

```bash
command -v hermes
hermes --help
```

### Dashboard does not open

Check its state, recent logs, and whether port 9119 listens locally:

```bash
systemctl --user status hermes-dashboard.service
journalctl --user -u hermes-dashboard.service -n 80 --no-pager
ss -ltnp | grep ':9119'
```

Restart it after resolving the reported issue:

```bash
systemctl --user restart hermes-dashboard.service
```

### Gateway / Telegram does not start

Read the service log first. Fix the Hermes configuration error it reports, then restart the service:

```bash
journalctl --user -u hermes-gateway.service -n 80 --no-pager
systemctl --user restart hermes-gateway.service
```

## How to: run tests

```bash
.venv/bin/python -m pytest -q
```

## Suggested v0.2

- Live streaming journal instead of snapshot logs.
- Port conflict inspector with PID/process details.
- Dashboard port editor.
- Hermes profile selector.
- Telegram configuration health check.
- WSL auto-start diagnostics.
- Package as a standalone binary with PyInstaller or Nuitka.
