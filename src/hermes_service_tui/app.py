from __future__ import annotations

import asyncio

from textual import on
from textual.app import App, ComposeResult
from textual.containers import Horizontal
from textual.widgets import Button, DataTable, Footer, Header, RichLog, Static

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

    #services {
        height: 10;
        margin-top: 1;
    }

    #actions {
        height: 3;
        align: center middle;
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
        ("l", "logs", "Logs"),
        ("q", "quit", "Quit"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.selected_unit = systemd.GATEWAY_UNIT
        self._refreshing = False

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static("Detecting Hermes / systemd…", id="summary")
        table = DataTable(id="services", cursor_type="row")
        table.add_columns("Service", "State", "Enabled", "PID", "Endpoint")
        yield table
        with Horizontal(id="actions"):
            yield Button("Install/Update", id="install")
            yield Button("Start", id="start", variant="success")
            yield Button("Stop", id="stop", variant="error")
            yield Button("Restart", id="restart", variant="warning")
            yield Button("Logs", id="show-logs")
            yield Button("Refresh", id="refresh")
        yield RichLog(id="logs", wrap=True, highlight=True, markup=True)
        yield Footer()

    async def on_mount(self) -> None:
        await self.refresh_all()
        self.set_interval(2.0, self.refresh_all)

    def current_unit(self) -> str:
        table = self.query_one("#services", DataTable)
        if table.row_count and table.cursor_row is not None:
            row_key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key
            if row_key is not None:
                return str(row_key.value)
        return self.selected_unit

    async def refresh_all(self) -> None:
        if self._refreshing:
            return
        self._refreshing = True
        try:
            info, states = await asyncio.gather(systemd.system_info(), systemd.all_states())
            summary = self.query_one("#summary", Static)
            systemd_ok = info["init"] == "systemd"
            summary.update(
                f"Hermes: {info['hermes']}   |   init: {info['init']} "
                f"({'OK' if systemd_ok else 'systemd required'})   |   user: {info['user']}"
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
        log = self.query_one("#logs", RichLog)
        log.write(f"[bold]{action.upper()}[/bold] {unit}")
        code, out, err = await systemd.service_action(unit, action)
        if out:
            log.write(out)
        if err:
            log.write(f"[red]{err}[/red]")
        log.write(f"exit={code}")
        await asyncio.sleep(0.25)
        await self.refresh_all()
        await self.show_logs(unit)

    async def show_logs(self, unit: str | None = None) -> None:
        unit = unit or self.current_unit()
        log = self.query_one("#logs", RichLog)
        log.clear()
        log.write(f"[bold]journal: {unit}[/bold]")
        log.write(await systemd.recent_logs(unit))

    async def action_refresh(self) -> None:
        await self.refresh_all()

    async def action_start(self) -> None:
        await self._run_action("start")

    async def action_stop(self) -> None:
        await self._run_action("stop")

    async def action_restart(self) -> None:
        await self._run_action("restart")

    async def action_install(self) -> None:
        log = self.query_one("#logs", RichLog)
        try:
            paths = await systemd.install_units()
            log.clear()
            log.write("[green]Installed / updated units:[/green]")
            for path in paths:
                log.write(path)
            log.write("\nUse Start on each row, or run: systemctl --user start hermes.target")
        except Exception as exc:
            log.write(f"[red]Install failed: {exc}[/red]")
        await self.refresh_all()

    async def action_logs(self) -> None:
        await self.show_logs()

    @on(DataTable.RowHighlighted, "#services")
    async def row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.row_key is not None:
            self.selected_unit = str(event.row_key.value)

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
        elif button_id == "show-logs":
            await self.action_logs()
        elif button_id == "refresh":
            await self.action_refresh()
