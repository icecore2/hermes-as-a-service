from dataclasses import dataclass


@dataclass(slots=True)
class ServiceState:
    unit: str
    label: str
    active: str = "unknown"
    enabled: str = "unknown"
    pid: str = "-"
    endpoint: str = "-"
