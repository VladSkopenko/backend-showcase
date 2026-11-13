import uuid
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.common import clock
from app.features.core.notifications.dto import NotificationPage, NotificationView
from app.features.core.notifications.models import Notification
from app.features.core.notifications.repositories import NotificationRepository
from app.features.core.notifications.services.exceptions import NotificationNotFoundError


class NotificationService:
    def __init__(self, session: AsyncSession, *, timezone: ZoneInfo) -> None:
        self._notifications = NotificationRepository(session)
        self._timezone = timezone

    async def list_page(
        self, *, user_id: uuid.UUID, unread_only: bool, limit: int, offset: int
    ) -> NotificationPage:
        notifications = await self._notifications.list_for_user(
            user_id=user_id, unread_only=unread_only, limit=limit, offset=offset
        )
        return NotificationPage(
            items=[self._to_view(notification) for notification in notifications],
            total=await self._notifications.count_for_user(
                user_id=user_id, unread_only=unread_only
            ),
            limit=limit,
            offset=offset,
        )

    async def mark_read(
        self, *, user_id: uuid.UUID, notification_id: uuid.UUID
    ) -> NotificationView:
        notification = await self._notifications.get_for_user(
            notification_id=notification_id, user_id=user_id, for_update=True
        )
        if notification is None:
            raise NotificationNotFoundError()
        if notification.read_at is None:
            notification.read_at = clock.now()
            await self._notifications.flush()
        return self._to_view(notification)

    def _to_view(self, notification: Notification) -> NotificationView:
        return NotificationView(
            id=notification.id,
            kind=notification.kind,
            booking_id=notification.booking_id,
            created_at=notification.created_at.astimezone(self._timezone),
            read_at=None
            if notification.read_at is None
            else notification.read_at.astimezone(self._timezone),
        )
