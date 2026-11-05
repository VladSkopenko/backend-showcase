from dataclasses import dataclass


@dataclass(frozen=True)
class HealthReport:
    database_ok: bool
