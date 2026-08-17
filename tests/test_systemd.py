from pathlib import Path

from hermes_service_tui.systemd import build_dashboard_unit, build_gateway_unit, build_target_unit


def test_gateway_unit_uses_external_supervisor() -> None:
    unit = build_gateway_unit("/home/dima/.local/bin/hermes", Path("/home/dima"))
    assert "gateway run --external-supervisor" in unit
    assert "Restart=always" in unit
    assert "HERMES_HOME=/home/dima/.hermes" in unit


def test_dashboard_unit_is_headless_on_9119() -> None:
    unit = build_dashboard_unit("/usr/bin/hermes", Path("/home/dima"), 9119)
    assert "dashboard --host 127.0.0.1 --port 9119 --no-open" in unit
    assert "Restart=on-failure" in unit


def test_target_wants_both_services() -> None:
    unit = build_target_unit()
    assert "hermes-gateway.service" in unit
    assert "hermes-dashboard.service" in unit
