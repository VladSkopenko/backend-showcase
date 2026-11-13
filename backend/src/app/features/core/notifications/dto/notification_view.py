import uuid
from dataclasses import dataclass
from datetime import datetime

from app.features.core.notifications.enums import NotificationKind


@dataclass(frozen=True)
class NotificationView:
    id: uuid.UUID
    kind: NotificationKind
    booking_id: uuid.UUID
    created_at: datetime
    read_at: datetime | None
