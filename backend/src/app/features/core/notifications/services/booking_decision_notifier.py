from collections.abc import Sequence
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.features.core.notifications.dto import DecisionNotice
from app.features.core.notifications.models import Notification
from app.features.core.notifications.repositories import NotificationRepository


class BookingDecisionNotifier:
    def __init__(self, session: AsyncSession) -> None:
        self._notifications = NotificationRepository(session)

    async def record(self, *, notices: Sequence[DecisionNotice], created_at: datetime) -> None:
        await self._notifications.add_all(
            notifications=[
                Notification(
                    user_id=recipient.user_id,
                    kind=notice.kind,
                    booking_id=notice.booking_id,
                    created_at=created_at,
                )
                for notice in notices
                for recipient in notice.recipients
            ]
        )
