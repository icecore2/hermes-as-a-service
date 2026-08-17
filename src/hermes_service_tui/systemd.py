from __future__ import annotations

import asyncio
import os
import shlex
import shutil
from pathlib import Path

from .models import ServiceState


GATEWAY_UNIT = "hermes-gateway.service"
DASHBOARD_UNIT = "hermes-dashboard.service"
TARGET_UNIT = "hermes.target"
DASHBOARD_PORT = 9119


async def run(*args: str, check: bool = False) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    out = stdout.decode(errors="replace").strip()
    err = stderr.decode(errors="replace").strip()
    if check and proc.returncode != 0:
        raise RuntimeError(err or out or f"Command failed: {shlex.join(args)}")
    return proc.returncode or 0, out, err


def hermes_binary() -> str:
    binary = shutil.which("hermes")
    if not binary:
        raise FileNotFoundError("Could not find 'hermes' in PATH")
    return str(Path(binary).resolve())


def user_unit_dir() -> Path:
    return Path.home() / ".config" / "systemd" / "user"


def build_gateway_unit(binary: str, home: Path) -> str:
    hermes_home = home / ".hermes"
    return f"""[Unit]
Description=Hermes Messaging Gateway
After=network.target
PartOf={TARGET_UNIT}

[Service]
Type=simple
WorkingDirectory={hermes_home}
Environment=HOME={home}
Environment=HERMES_HOME={hermes_home}
ExecStart={binary} gateway run --external-supervisor
Restart=always
RestartSec=5
KillMode=control-group
TimeoutStopSec=20

[Install]
WantedBy=default.target
"""


def build_dashboard_unit(binary: str, home: Path, port: int = DASHBOARD_PORT) -> str:
    hermes_home = home / ".hermes"
    return f"""[Unit]
Description=Hermes Web Dashboard
After=network.target
PartOf={TARGET_UNIT}

[Service]
Type=simple
WorkingDirectory={hermes_home}
Environment=HOME={home}
Environment=HERMES_HOME={hermes_home}
ExecStart={binary} dashboard --host 127.0.0.1 --port {port} --no-open
Restart=on-failure
RestartSec=5
KillMode=control-group
TimeoutStopSec=20

[Install]
WantedBy=default.target
"""


def build_target_unit() -> str:
    return f"""[Unit]
Description=Hermes Agent Services
Wants={GATEWAY_UNIT} {DASHBOARD_UNIT}
After=network.target

[Install]
WantedBy=default.target
"""


async def install_units(port: int = DASHBOARD_PORT) -> list[str]:
    binary = hermes_binary()
    home = Path.home()
    unit_dir = user_unit_dir()
    unit_dir.mkdir(parents=True, exist_ok=True)

    files = {
        GATEWAY_UNIT: build_gateway_unit(binary, home),
        DASHBOARD_UNIT: build_dashboard_unit(binary, home, port),
        TARGET_UNIT: build_target_unit(),
    }
    for name, content in files.items():
        (unit_dir / name).write_text(content, encoding="utf-8")

    await run("systemctl", "--user", "daemon-reload", check=True)
    await run("systemctl", "--user", "enable", GATEWAY_UNIT, DASHBOARD_UNIT, TARGET_UNIT, check=True)
    return [str(unit_dir / name) for name in files]


async def service_action(unit: str, action: str) -> tuple[int, str, str]:
    if action not in {"start", "stop", "restart"}:
        raise ValueError(f"Unsupported action: {action}")
    return await run("systemctl", "--user", action, unit)


async def _property(unit: str, prop: str) -> str:
    code, out, _ = await run(
        "systemctl", "--user", "show", unit, f"--property={prop}", "--value"
    )
    return out if code == 0 and out else "-"


async def _simple_status(unit: str, command: str) -> str:
    code, out, _ = await run("systemctl", "--user", command, unit)
    if out:
        return out
    return "unknown" if code else "-"


async def dashboard_listener(port: int = DASHBOARD_PORT) -> str:
    code, out, _ = await run("ss", "-ltnp")
    if code != 0:
        return "unknown"
    needle = f":{port}"
    for line in out.splitlines():
        if needle in line and "LISTEN" in line:
            return f"127.0.0.1:{port}"
    return "free"


async def service_state(unit: str, label: str, endpoint: str = "-") -> ServiceState:
    active, enabled, pid = await asyncio.gather(
        _simple_status(unit, "is-active"),
        _simple_status(unit, "is-enabled"),
        _property(unit, "MainPID"),
    )
    if pid == "0":
        pid = "-"
    return ServiceState(unit=unit, label=label, active=active, enabled=enabled, pid=pid, endpoint=endpoint)


async def all_states(port: int = DASHBOARD_PORT) -> list[ServiceState]:
    listener = await dashboard_listener(port)
    gateway, dashboard = await asyncio.gather(
        service_state(GATEWAY_UNIT, "Gateway / Telegram"),
        service_state(DASHBOARD_UNIT, "Dashboard", listener),
    )
    return [gateway, dashboard]


async def recent_logs(unit: str, lines: int = 80) -> str:
    _, out, err = await run(
        "journalctl",
        "--user",
        "-u",
        unit,
        "-n",
        str(lines),
        "--no-pager",
        "-o",
        "short-iso",
    )
    return out or err or "No journal output."


async def system_info() -> dict[str, str]:
    _, init_name, _ = await run("ps", "-p", "1", "-o", "comm=")
    return {
        "user": os.environ.get("USER", "?"),
        "home": str(Path.home()),
        "init": init_name or "?",
        "hermes": shutil.which("hermes") or "not found",
    }
