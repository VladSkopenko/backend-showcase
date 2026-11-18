import enum


class AssistantActionStatus(enum.Enum):
    PENDING = "PENDING"
    APPLIED = "APPLIED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"
    FAILED = "FAILED"
