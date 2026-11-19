import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.assistant.enums import AssistantActionStatus
from app.features.assistant.models import AssistantAction


class AssistantActionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, *, action: AssistantAction) -> None:
        self._session.add(action)
        await self._session.flush()

    async def flush(self) -> None:
        await self._session.flush()

    async def get_pending_for_session(self, *, session_id: uuid.UUID) -> AssistantAction | None:
        action: AssistantAction | None = await self._session.scalar(
            select(AssistantAction).where(
                AssistantAction.session_id == session_id,
                AssistantAction.status == AssistantActionStatus.PENDING,
            )
        )
        return action

    async def get_for_user(
        self,
        *,
        action_id: uuid.UUID,
        session_id: uuid.UUID,
        user_id: uuid.UUID,
        for_update: bool = False,
    ) -> AssistantAction | None:
        query = (
            select(AssistantAction)
            .where(
                AssistantAction.id == action_id,
                AssistantAction.session_id == session_id,
                AssistantAction.user_id == user_id,
            )
            .execution_options(populate_existing=True)
        )
        if for_update:
            query = query.with_for_update()
        action: AssistantAction | None = await self._session.scalar(query)
        return action

    async def list_for_messages(
        self, *, message_ids: Sequence[uuid.UUID]
    ) -> Sequence[AssistantAction]:
        if not message_ids:
            return []
        actions = await self._session.scalars(
            select(AssistantAction).where(AssistantAction.message_id.in_(message_ids))
        )
        return actions.all()

    async def supersede(
        self, *, action_id: uuid.UUID, status: AssistantActionStatus, now: datetime
    ) -> None:
        await self._session.execute(
            update(AssistantAction)
            .where(
                AssistantAction.id == action_id,
                AssistantAction.status == AssistantActionStatus.PENDING,
            )
            .values(status=status, resolved_at=now)
            .execution_options(synchronize_session=False)
        )

    async def claim(self, *, action_id: uuid.UUID, now: datetime) -> bool:
        claimed = await self._session.scalar(
            update(AssistantAction)
            .where(
                AssistantAction.id == action_id,
                AssistantAction.status == AssistantActionStatus.PENDING,
                AssistantAction.expires_at > now,
            )
            .values(status=AssistantActionStatus.APPLIED, resolved_at=now)
            .returning(AssistantAction.id)
            .execution_options(synchronize_session=False)
        )
        return claimed is not None
