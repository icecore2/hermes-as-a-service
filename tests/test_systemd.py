from pathlib import Path

import pytest

from hermes_service_tui.models import PortInspection
from hermes_service_tui.systemd import (
    build_dashboard_unit,
    build_gateway_unit,
    build_target_unit,
    parse_port_inspections,
    profile_home,
    telegram_config_health,
    validate_port,
    wsl_systemd_enabled,
)


def test_gateway_unit_uses_external_supervisor() -> None:
    unit = build_gateway_unit("/home/dima/.local/bin/hermes", Path("/home/dima"))
    assert "gateway run --external-supervisor" in unit
    assert "Restart=always" in unit
    assert "HERMES_HOME=/home/dima/.hermes" in unit


def test_profile_aware_units_scope_hermes_home() -> None:
    home = Path("/home/dima")
    gateway = build_gateway_unit("/usr/bin/hermes", home, profile="coder")
    dashboard = build_dashboard_unit("/usr/bin/hermes", home, 9120, profile="coder")
    assert profile_home("coder", home) == Path("/home/dima/.hermes/profiles/coder")
    assert "HERMES_HOME=/home/dima/.hermes/profiles/coder" in gateway
    assert "HERMES_HOME=/home/dima/.hermes/profiles/coder" in dashboard
    assert "--port 9120 --no-open" in dashboard


def test_dashboard_unit_is_headless_on_9119() -> None:
    unit = build_dashboard_unit("/usr/bin/hermes", Path("/home/dima"), 9119)
    assert "dashboard --host 127.0.0.1 --port 9119 --no-open" in unit
    assert "Restart=on-failure" in unit


def test_target_wants_both_services() -> None:
    unit = build_target_unit()
    assert "hermes-gateway.service" in unit
    assert "hermes-dashboard.service" in unit


@pytest.mark.parametrize("value", [0, 65536, "abc", "1.5"])
def test_invalid_dashboard_ports_are_rejected(value: int | str) -> None:
    with pytest.raises(ValueError):
        validate_port(value)


def test_port_inspector_extracts_process_and_pid() -> None:
    output = (
        'LISTEN 0 4096 127.0.0.1:9119 0.0.0.0:* users:(("python",pid=4242,fd=6))\n'
        'LISTEN 0 4096 127.0.0.1:9120 0.0.0.0:* users:(("node",pid=5252,fd=7))\n'
    )
    inspections = parse_port_inspections(output, 9119)
    assert inspections == [
        PortInspection(9119, "occupied", "127.0.0.1:9119", "4242", "python")
    ]
    assert inspections[0].summary == "127.0.0.1:9119 • python (PID 4242)"


def test_telegram_health_hides_the_token(tmp_path: Path) -> None:
    profile_dir = tmp_path / ".hermes" / "profiles" / "bot"
    profile_dir.mkdir(parents=True)
    secret = "123456:ABC-not-for-output"
    (profile_dir / ".env").write_text(f"TELEGRAM_BOT_TOKEN={secret}\n", encoding="utf-8")

    health = telegram_config_health("bot", tmp_path)

    assert health.status == "configured"
    assert "hidden" in health.detail
    assert secret not in health.detail


def test_telegram_health_reports_missing_token(tmp_path: Path) -> None:
    profile_dir = tmp_path / ".hermes"
    profile_dir.mkdir(parents=True)
    (profile_dir / ".env").write_text("MODEL_PROVIDER=test\n", encoding="utf-8")

    health = telegram_config_health("default", tmp_path)

    assert health.status == "missing"


def test_wsl_conf_systemd_parser() -> None:
    assert wsl_systemd_enabled("[boot]\nsystemd=true\n")
    assert wsl_systemd_enabled("[boot]\nSystemd = TRUE\n")
    assert not wsl_systemd_enabled("[network]\nsystemd=true\n")
    assert not wsl_systemd_enabled("[boot]\nsystemd=false\n")
