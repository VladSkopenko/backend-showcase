import uuid
from collections.abc import Sequence

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.core.notifications.models import Notification


class NotificationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add_all(self, *, notifications: Sequence[Notification]) -> None:
        self._session.add_all(notifications)
        await self._session.flush()

    async def list_for_user(
        self, *, user_id: uuid.UUID, unread_only: bool, limit: int, offset: int
    ) -> Sequence[Notification]:
        notifications = await self._session.scalars(
            select(Notification)
            .where(*self._owned(user_id=user_id, unread_only=unread_only))
            .order_by(Notification.created_at.desc(), Notification.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return notifications.all()

    async def count_for_user(self, *, user_id: uuid.UUID, unread_only: bool) -> int:
        total = await self._session.scalar(
            select(func.count())
            .select_from(Notification)
            .where(*self._owned(user_id=user_id, unread_only=unread_only))
        )
        return total or 0

    async def get_for_user(
        self, *, notification_id: uuid.UUID, user_id: uuid.UUID, for_update: bool = False
    ) -> Notification | None:
        statement = select(Notification).where(
            Notification.id == notification_id, Notification.user_id == user_id
        )
        if for_update:
            statement = statement.with_for_update().execution_options(populate_existing=True)
        notification: Notification | None = await self._session.scalar(statement)
        return notification

    async def flush(self) -> None:
        await self._session.flush()

    @staticmethod
    def _owned(*, user_id: uuid.UUID, unread_only: bool) -> tuple[ColumnElement[bool], ...]:
        unread = (Notification.read_at.is_(None),) if unread_only else ()
        return (Notification.user_id == user_id, *unread)
