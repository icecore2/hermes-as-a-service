from dataclasses import dataclass


@dataclass(slots=True)
class ServiceState:
    unit: str
    label: str
    active: str = "unknown"
    enabled: str = "unknown"
    pid: str = "-"
    endpoint: str = "-"


@dataclass(frozen=True, slots=True)
class PortInspection:
    port: int
    status: str
    address: str = "-"
    pid: str = "-"
    process: str = "-"

    @property
    def summary(self) -> str:
        if self.status == "free":
            return "free"
        if self.status == "unknown":
            return "unknown"
        details = f"{self.address} • {self.process}"
        if self.pid != "-":
            details += f" (PID {self.pid})"
        return details


@dataclass(frozen=True, slots=True)
class TelegramHealth:
    profile: str
    status: str
    detail: str
