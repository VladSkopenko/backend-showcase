from dataclasses import dataclass

from app.features.core.notifications.dto.notification_view import NotificationView


@dataclass(frozen=True)
class NotificationPage:
    items: list[NotificationView]
    total: int
    limit: int
    offset: int
