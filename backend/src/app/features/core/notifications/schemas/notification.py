import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.features.core.notifications.enums import NotificationKind


class NotificationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: NotificationKind
    booking_id: uuid.UUID
    created_at: datetime
    read_at: datetime | None


class NotificationPageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    items: list[NotificationResponse]
    total: int
    limit: int
    offset: int
