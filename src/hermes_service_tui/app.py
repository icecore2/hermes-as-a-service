from __future__ import annotations

import asyncio

from textual import on
from textual.app import App, ComposeResult
from textual.containers import Horizontal
from textual.widgets import Button, DataTable, Footer, Header, Input, RichLog, Select, Static

from . import systemd


class HermesServiceApp(App):
    TITLE = "Hermes Service Manager"
    SUB_TITLE = "WSL2 / systemd --user"

    CSS = """
    Screen {
        layout: vertical;
    }

    #summary {
        height: 3;
        padding: 0 1;
        border: solid $primary;
    }

    #configuration, #actions {
        height: 3;
        align: center middle;
    }

    #configuration Select {
        width: 24;
    }

    #dashboard-port {
        width: 13;
        margin: 0 1;
    }

    #services {
        height: 10;
        margin-top: 1;
    }

    Button {
        margin: 0 1;
        min-width: 10;
    }

    #logs {
        height: 1fr;
        border: solid $secondary;
        padding: 0 1;
    }
    """

    BINDINGS = [
        ("r", "refresh", "Refresh"),
        ("s", "start", "Start"),
        ("x", "stop", "Stop"),
        ("e", "restart", "Restart"),
        ("i", "install", "Install units"),
        ("l", "live_logs", "Live logs"),
        ("p", "edit_port", "Edit port"),
        ("d", "diagnostics", "Diagnostics"),
        ("q", "quit", "Quit"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.selected_unit = systemd.GATEWAY_UNIT
        self.dashboard_port = systemd.DASHBOARD_PORT
        self._refreshing = False
        self._streaming_unit: str | None = None
        self._journal_worker = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static("Detecting Hermes / systemd…", id="summary")
        with Horizontal(id="configuration"):
            yield Static("Profile:")
            yield Select.from_values(systemd.available_profiles(), value="default", id="profile")
            yield Static("Dashboard port:")
            yield Input(str(systemd.DASHBOARD_PORT), id="dashboard-port", type="integer")
            yield Button("Apply Port", id="apply-port")
        table = DataTable(id="services", cursor_type="row")
        table.add_columns("Service", "State", "Enabled", "PID", "Endpoint / port owner")
        yield table
        with Horizontal(id="actions"):
            yield Button("Install/Update", id="install")
            yield Button("Start", id="start", variant="success")
            yield Button("Stop", id="stop", variant="error")
            yield Button("Restart", id="restart", variant="warning")
            yield Button("Live Logs", id="live-logs")
            yield Button("Diagnostics", id="diagnostics")
            yield Button("Refresh", id="refresh")
        yield RichLog(id="logs", wrap=True, highlight=True, markup=False)
        yield Footer()

    async def on_mount(self) -> None:
        self.dashboard_port, configured_profile = await asyncio.gather(
            systemd.configured_dashboard_port(), systemd.configured_service_profile()
        )
        self.query_one("#dashboard-port", Input).value = str(self.dashboard_port)
        profile_select = self.query_one("#profile", Select)
        if configured_profile in systemd.available_profiles():
            profile_select.value = configured_profile
        await self.refresh_all()
        self.set_interval(2.0, self.refresh_all)

    def current_unit(self) -> str:
        table = self.query_one("#services", DataTable)
        if table.row_count and table.cursor_row is not None:
            row_key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key
            if row_key is not None:
                return str(row_key.value)
        return self.selected_unit

    def current_profile(self) -> str:
        value = self.query_one("#profile", Select).value
        return str(value) if value is not Select.BLANK else "default"

    def _write(self, message: str, clear: bool = False) -> None:
        log = self.query_one("#logs", RichLog)
        if clear:
            log.clear()
        log.write(message)

    async def refresh_all(self) -> None:
        if self._refreshing:
            return
        self._refreshing = True
        try:
            profile = self.current_profile()
            info, states, port, unit_profile = await asyncio.gather(
                systemd.system_info(),
                systemd.all_states(self.dashboard_port),
                systemd.inspect_port(self.dashboard_port),
                systemd.configured_service_profile(),
            )
            telegram = systemd.telegram_config_health(profile)
            summary = self.query_one("#summary", Static)
            systemd_ok = info["init"] == "systemd"
            summary.update(
                f"Target profile: {profile} | installed profile: {unit_profile} | "
                f"port {self.dashboard_port}: {port.summary} | Telegram: {telegram.status} | "
                f"systemd: {'OK' if systemd_ok else 'required'}"
            )

            table = self.query_one("#services", DataTable)
            cursor_row = table.cursor_row
            table.clear()
            for state in states:
                table.add_row(
                    state.label,
                    state.active,
                    state.enabled,
                    state.pid,
                    state.endpoint,
                    key=state.unit,
                )
            if cursor_row is not None and table.row_count:
                table.move_cursor(row=min(cursor_row, table.row_count - 1))
        finally:
            self._refreshing = False

    async def _run_action(self, action: str) -> None:
        unit = self.current_unit()
        self._write(f"{action.upper()} {unit}", clear=True)
        code, out, err = await systemd.service_action(unit, action)
        if out:
            self._write(out)
        if err:
            self._write(err)
        self._write(f"exit={code}")
        await asyncio.sleep(0.25)
        await self.refresh_all()

    def _stop_live_logs(self, announce: bool = True) -> None:
        if self._journal_worker is not None:
            self._journal_worker.cancel()
        if announce and self._streaming_unit:
            self._write(f"Stopped live journal for {self._streaming_unit}.")
        self._journal_worker = None
        self._streaming_unit = None

    async def _stream_journal(self, unit: str) -> None:
        try:
            async for line in systemd.follow_journal(unit):
                self._write(line)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._write(f"Live journal failed: {exc}")
        finally:
            if self._streaming_unit == unit:
                self._streaming_unit = None
                self._journal_worker = None

    async def action_live_logs(self) -> None:
        unit = self.current_unit()
        if self._streaming_unit == unit:
            self._stop_live_logs()
            return
        self._stop_live_logs(announce=False)
        self._streaming_unit = unit
        self._write(f"Live journal: {unit} (press L again to stop)", clear=True)
        self._journal_worker = self.run_worker(
            self._stream_journal(unit), group="journal", exclusive=True, exit_on_error=False
        )

    async def _apply_dashboard_configuration(self, restart_dashboard: bool) -> bool:
        port_input = self.query_one("#dashboard-port", Input)
        try:
            requested_port = systemd.validate_port(port_input.value)
        except ValueError as exc:
            self._write(str(exc), clear=True)
            return False

        inspection, dashboard_pid, configured_port = await asyncio.gather(
            systemd.inspect_port(requested_port),
            systemd.unit_pid(systemd.DASHBOARD_UNIT),
            systemd.configured_dashboard_port(),
        )
        if (
            inspection.status == "occupied"
            and inspection.pid not in {"-", dashboard_pid}
            and requested_port != configured_port
        ):
            self._write(
                f"Port {requested_port} is occupied by {inspection.summary}. Choose another port.",
                clear=True,
            )
            return False

        try:
            paths = await systemd.install_units(requested_port, self.current_profile())
        except Exception as exc:
            self._write(f"Install failed: {exc}", clear=True)
            return False

        self.dashboard_port = requested_port
        self._write("Installed / updated units:", clear=True)
        for path in paths:
            self._write(path)
        self._write(f"Profile: {self.current_profile()} | Dashboard port: {requested_port}")

        if restart_dashboard:
            active = await systemd._simple_status(systemd.DASHBOARD_UNIT, "is-active")
            if active == "active":
                code, out, err = await systemd.service_action(systemd.DASHBOARD_UNIT, "restart")
                self._write(f"Dashboard restart exit={code}")
                if out:
                    self._write(out)
                if err:
                    self._write(err)
        await self.refresh_all()
        return True

    async def action_apply_port(self) -> None:
        await self._apply_dashboard_configuration(restart_dashboard=True)

    async def action_refresh(self) -> None:
        await self.refresh_all()

    async def action_start(self) -> None:
        await self._run_action("start")

    async def action_stop(self) -> None:
        await self._run_action("stop")

    async def action_restart(self) -> None:
        await self._run_action("restart")

    async def action_install(self) -> None:
        await self._apply_dashboard_configuration(restart_dashboard=False)

    async def action_edit_port(self) -> None:
        self.query_one("#dashboard-port", Input).focus()

    async def action_diagnostics(self) -> None:
        profile = self.current_profile()
        port, wsl = await asyncio.gather(
            systemd.inspect_port(self.dashboard_port), systemd.wsl_autostart_diagnostics()
        )
        telegram = systemd.telegram_config_health(profile)
        self._stop_live_logs(announce=False)
        self._write("Diagnostics", clear=True)
        self._write(f"Profile: {profile} ({systemd.profile_home(profile)})")
        self._write(f"Telegram config: {telegram.status} — {telegram.detail}")
        self._write(f"Dashboard port {self.dashboard_port}: {port.status} — {port.summary}")
        self._write(
            "WSL auto-start: "
            f"platform={wsl['platform']}, PID 1={wsl['pid_1']}, systemd={wsl['systemd']}, "
            f"user manager={wsl['user_manager']}, linger={wsl['linger']}, "
            f"wsl.conf systemd={wsl['wsl_conf_systemd']}"
        )
        self._write("No Telegram token values are displayed.")

    @on(DataTable.RowHighlighted, "#services")
    async def row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.row_key is not None:
            self.selected_unit = str(event.row_key.value)

    @on(Select.Changed, "#profile")
    async def profile_changed(self, event: Select.Changed) -> None:
        if event.value is not Select.BLANK:
            await self.refresh_all()

    @on(Button.Pressed)
    async def button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id
        if button_id == "install":
            await self.action_install()
        elif button_id == "start":
            await self.action_start()
        elif button_id == "stop":
            await self.action_stop()
        elif button_id == "restart":
            await self.action_restart()
        elif button_id == "live-logs":
            await self.action_live_logs()
        elif button_id == "apply-port":
            await self.action_apply_port()
        elif button_id == "diagnostics":
            await self.action_diagnostics()
        elif button_id == "refresh":
            await self.action_refresh()

    def on_unmount(self) -> None:
        self._stop_live_logs(announce=False)
