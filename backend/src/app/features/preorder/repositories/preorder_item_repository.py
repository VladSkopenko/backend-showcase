import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.preorder.enums import PreorderItemState
from app.features.preorder.models import PreorderItem


class PreorderItemRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_drafts(self, *, participant_id: uuid.UUID) -> Sequence[PreorderItem]:
        items = await self._session.scalars(
            select(PreorderItem)
            .where(
                PreorderItem.participant_id == participant_id,
                PreorderItem.state == PreorderItemState.DRAFT,
            )
            .order_by(PreorderItem.created_at, PreorderItem.id)
        )
        return items.all()

    async def list_submitted(self, *, participant_id: uuid.UUID) -> Sequence[PreorderItem]:
        items = await self._session.scalars(
            select(PreorderItem)
            .where(
                PreorderItem.participant_id == participant_id,
                PreorderItem.state == PreorderItemState.SUBMITTED,
            )
            .order_by(
                PreorderItem.submitted_at,
                PreorderItem.submission_id,
                PreorderItem.created_at,
                PreorderItem.id,
            )
        )
        return items.all()

    async def get_draft(
        self, *, participant_id: uuid.UUID, dish_id: uuid.UUID
    ) -> PreorderItem | None:
        item: PreorderItem | None = await self._session.scalar(
            select(PreorderItem).where(
                PreorderItem.participant_id == participant_id,
                PreorderItem.dish_id == dish_id,
                PreorderItem.state == PreorderItemState.DRAFT,
            )
        )
        return item

    async def add(self, *, item: PreorderItem) -> None:
        self._session.add(item)
        await self._session.flush()

    async def delete(self, *, item: PreorderItem) -> None:
        await self._session.delete(item)
        await self._session.flush()

    async def flush(self) -> None:
        await self._session.flush()
