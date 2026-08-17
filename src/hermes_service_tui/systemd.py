from __future__ import annotations

import asyncio
import contextlib
import os
import re
import shlex
import shutil
from collections.abc import AsyncIterator
from pathlib import Path

from .models import PortInspection, ServiceState, TelegramHealth


GATEWAY_UNIT = "hermes-gateway.service"
DASHBOARD_UNIT = "hermes-dashboard.service"
TARGET_UNIT = "hermes.target"
DASHBOARD_PORT = 9119
PROFILE_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")
PORT_RE = re.compile(r"--port\s+(\d+)")
PROCESS_RE = re.compile(r'users:\(\("(?P<process>[^"]+)".*?pid=(?P<pid>\d+)')
TELEGRAM_TOKEN_RE = re.compile(
    r"^\s*(?:export\s+)?(?P<key>[A-Z0-9_]*TELEGRAM[A-Z0-9_]*(?:TOKEN|API_KEY))\s*=\s*(?P<value>.*)$",
    re.IGNORECASE,
)


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


def validate_port(value: int | str) -> int:
    try:
        port = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Dashboard port must be a whole number from 1 to 65535.") from exc
    if not 1 <= port <= 65535:
        raise ValueError("Dashboard port must be between 1 and 65535.")
    return port


def hermes_binary() -> str:
    binary = shutil.which("hermes")
    if not binary:
        raise FileNotFoundError("Could not find 'hermes' in PATH")
    return str(Path(binary).resolve())


def user_unit_dir() -> Path:
    return Path.home() / ".config" / "systemd" / "user"


def base_hermes_home(home: Path | None = None) -> Path:
    return (home or Path.home()) / ".hermes"


def profile_home(profile: str = "default", home: Path | None = None) -> Path:
    base = base_hermes_home(home)
    if profile == "default":
        return base
    if not PROFILE_NAME_RE.fullmatch(profile):
        raise ValueError("Profile names may contain only letters, numbers, hyphens, and underscores.")
    return base / "profiles" / profile


def available_profiles(home: Path | None = None) -> list[str]:
    profiles = ["default"]
    profiles_dir = base_hermes_home(home) / "profiles"
    if profiles_dir.is_dir():
        profiles.extend(sorted(path.name for path in profiles_dir.iterdir() if path.is_dir()))
    return profiles


def build_gateway_unit(binary: str, home: Path, profile: str = "default") -> str:
    hermes_home = profile_home(profile, home)
    return f"""[Unit]
Description=Hermes Messaging Gateway ({profile})
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


def build_dashboard_unit(
    binary: str,
    home: Path,
    port: int = DASHBOARD_PORT,
    profile: str = "default",
) -> str:
    port = validate_port(port)
    hermes_home = profile_home(profile, home)
    return f"""[Unit]
Description=Hermes Web Dashboard ({profile})
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


async def install_units(port: int = DASHBOARD_PORT, profile: str = "default") -> list[str]:
    port = validate_port(port)
    # Reject malformed profile names before writing any systemd unit.
    profile_home(profile)
    binary = hermes_binary()
    home = Path.home()
    unit_dir = user_unit_dir()
    unit_dir.mkdir(parents=True, exist_ok=True)

    files = {
        GATEWAY_UNIT: build_gateway_unit(binary, home, profile),
        DASHBOARD_UNIT: build_dashboard_unit(binary, home, port, profile),
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


async def unit_pid(unit: str) -> str:
    pid = await _property(unit, "MainPID")
    return "-" if pid == "0" else pid


async def _simple_status(unit: str, command: str) -> str:
    code, out, _ = await run("systemctl", "--user", command, unit)
    if out:
        return out
    return "unknown" if code else "-"


def _address_port(address: str) -> int | None:
    _, separator, tail = address.rpartition(":")
    if not separator or not tail.isdigit():
        return None
    return int(tail)


def parse_port_inspections(ss_output: str, port: int) -> list[PortInspection]:
    inspections: list[PortInspection] = []
    for line in ss_output.splitlines():
        columns = line.split(maxsplit=5)
        if len(columns) < 5 or _address_port(columns[3]) != port:
            continue
        process_match = PROCESS_RE.search(line)
        inspections.append(
            PortInspection(
                port=port,
                status="occupied",
                address=columns[3],
                pid=process_match.group("pid") if process_match else "-",
                process=process_match.group("process") if process_match else "unavailable",
            )
        )
    return inspections


async def inspect_port(port: int) -> PortInspection:
    port = validate_port(port)
    code, out, _ = await run("ss", "-H", "-ltnp")
    if code != 0:
        return PortInspection(port=port, status="unknown")
    inspections = parse_port_inspections(out, port)
    return inspections[0] if inspections else PortInspection(port=port, status="free")


async def dashboard_listener(port: int = DASHBOARD_PORT) -> str:
    return (await inspect_port(port)).summary


async def configured_dashboard_port() -> int:
    unit_path = user_unit_dir() / DASHBOARD_UNIT
    try:
        content = unit_path.read_text(encoding="utf-8")
    except OSError:
        return DASHBOARD_PORT
    match = PORT_RE.search(content)
    return validate_port(match.group(1)) if match else DASHBOARD_PORT


async def configured_service_profile() -> str:
    unit_path = user_unit_dir() / DASHBOARD_UNIT
    try:
        content = unit_path.read_text(encoding="utf-8")
    except OSError:
        return "default"
    match = re.search(r"^Environment=HERMES_HOME=(.+)$", content, re.MULTILINE)
    if not match:
        return "default"
    configured_home = Path(match.group(1)).expanduser()
    for profile in available_profiles():
        if configured_home == profile_home(profile):
            return profile
    return "custom"


async def service_state(unit: str, label: str, endpoint: str = "-") -> ServiceState:
    active, enabled, pid = await asyncio.gather(
        _simple_status(unit, "is-active"),
        _simple_status(unit, "is-enabled"),
        unit_pid(unit),
    )
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


async def follow_journal(unit: str, lines: int = 80) -> AsyncIterator[str]:
    """Yield journal entries until the consumer cancels the stream."""
    proc = await asyncio.create_subprocess_exec(
        "journalctl",
        "--user",
        "-u",
        unit,
        "-n",
        str(lines),
        "-f",
        "--no-pager",
        "-o",
        "short-iso",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    assert proc.stdout is not None
    try:
        while True:
            line = await proc.stdout.readline()
            if not line:
                break
            yield line.decode(errors="replace").rstrip()
        if proc.stderr is not None:
            error = (await proc.stderr.read()).decode(errors="replace").strip()
            if error:
                yield f"journalctl: {error}"
    finally:
        if proc.returncode is None:
            proc.terminate()
            with contextlib.suppress(ProcessLookupError, asyncio.TimeoutError):
                await asyncio.wait_for(proc.wait(), timeout=2)
        if proc.returncode is None:
            proc.kill()
            with contextlib.suppress(ProcessLookupError):
                await proc.wait()


def telegram_config_health(profile: str = "default", home: Path | None = None) -> TelegramHealth:
    profile_path = profile_home(profile, home)
    if not profile_path.is_dir():
        return TelegramHealth(profile, "missing", "Profile directory does not exist.")

    env_path = profile_path / ".env"
    if not env_path.is_file():
        return TelegramHealth(profile, "missing", "No profile .env file found.")

    try:
        lines = env_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        return TelegramHealth(profile, "unknown", f"Could not read .env: {exc}")

    for line in lines:
        match = TELEGRAM_TOKEN_RE.match(line)
        if not match:
            continue
        value = match.group("value").strip().strip("'\"")
        if value and not value.startswith("#"):
            return TelegramHealth(profile, "configured", "Telegram credential is configured (value hidden).")
    return TelegramHealth(profile, "missing", "No Telegram token variable is configured in .env.")


def wsl_systemd_enabled(wsl_conf: str) -> bool:
    in_boot_section = False
    for raw_line in wsl_conf.splitlines():
        line = raw_line.strip()
        if not line or line.startswith(("#", ";")):
            continue
        if line.startswith("[") and line.endswith("]"):
            in_boot_section = line.lower() == "[boot]"
            continue
        if in_boot_section and re.fullmatch(r"systemd\s*=\s*true", line, re.IGNORECASE):
            return True
    return False


async def wsl_autostart_diagnostics() -> dict[str, str]:
    proc_version = Path("/proc/version")
    kernel = proc_version.read_text(encoding="utf-8", errors="replace") if proc_version.exists() else ""
    is_wsl = "microsoft" in kernel.lower() or bool(os.environ.get("WSL_INTEROP"))
    _, init, _ = await run("ps", "-p", "1", "-o", "comm=")
    state_code, user_manager, _ = await run("systemctl", "--user", "is-system-running")
    linger_code, linger, linger_error = await run("loginctl", "show-user", os.environ.get("USER", ""), "-p", "Linger")

    wsl_conf = Path("/etc/wsl.conf")
    try:
        configured = wsl_systemd_enabled(wsl_conf.read_text(encoding="utf-8"))
    except OSError:
        configured = False

    return {
        "platform": "WSL2" if is_wsl else "Linux",
        "pid_1": init or "unknown",
        "systemd": "ready" if init == "systemd" else "required",
        "user_manager": user_manager if state_code == 0 else "unavailable",
        "linger": linger.removeprefix("Linger=") if linger_code == 0 else (linger_error or "unknown"),
        "wsl_conf_systemd": "enabled" if configured else ("not configured" if is_wsl else "n/a"),
    }


async def system_info() -> dict[str, str]:
    _, init_name, _ = await run("ps", "-p", "1", "-o", "comm=")
    return {
        "user": os.environ.get("USER", "?"),
        "home": str(Path.home()),
        "init": init_name or "?",
        "hermes": shutil.which("hermes") or "not found",
    }
