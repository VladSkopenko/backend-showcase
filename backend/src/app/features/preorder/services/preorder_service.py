import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import cast
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.common import clock
from app.features.core.bookings.dto import ParticipantAccess
from app.features.core.bookings.services.participant_service import ParticipantService
from app.features.core.menu.dto import DishView
from app.features.core.menu.services.dish_catalog_service import DishCatalogService
from app.features.preorder.dto import CartLineView, CartView, MyPreorderView, SubmittedPartView
from app.features.preorder.enums import PreorderItemState
from app.features.preorder.models import PreorderItem
from app.features.preorder.repositories import PreorderItemRepository
from app.features.preorder.services.exceptions import (
    CartEmptyError,
    CartItemNotFoundError,
    DishUnavailableError,
    PreorderClosedError,
    QuantityTooLargeError,
)


class PreorderService:
    def __init__(
        self,
        session: AsyncSession,
        participants: ParticipantService,
        dishes: DishCatalogService,
        *,
        max_item_quantity: int,
        timezone: ZoneInfo,
    ) -> None:
        self._items = PreorderItemRepository(session)
        self._participants = participants
        self._dishes = dishes
        self._max_item_quantity = max_item_quantity
        self._timezone = timezone

    async def get_cart(
        self, *, booking_id: uuid.UUID, user_id: uuid.UUID | None, guest_token: str | None
    ) -> CartView:
        participant = await self._participants.get_participant(
            booking_id=booking_id, user_id=user_id, guest_token=guest_token
        )
        return await self._cart(participant_id=participant.participant_id)

    async def set_item(
        self,
        *,
        booking_id: uuid.UUID,
        user_id: uuid.UUID | None,
        guest_token: str | None,
        dish_id: uuid.UUID,
        quantity: int,
        note: str | None,
    ) -> CartView:
        participant = await self._lock_open(
            booking_id=booking_id, user_id=user_id, guest_token=guest_token
        )
        if quantity > self._max_item_quantity:
            raise QuantityTooLargeError()
        dish = await self._dishes.get(dish_id=dish_id)
        item = await self._items.get_draft(
            participant_id=participant.participant_id, dish_id=dish_id
        )
        if not dish.is_available and (item is None or quantity > item.quantity):
            raise DishUnavailableError()
        now = clock.now()
        if item is None:
            await self._items.add(
                item=PreorderItem(
                    participant_id=participant.participant_id,
                    dish_id=dish_id,
                    quantity=quantity,
                    note=note or None,
                    state=PreorderItemState.DRAFT,
                    created_at=now,
                    updated_at=now,
                )
            )
        else:
            item.quantity = quantity
            item.note = note or None
            item.updated_at = now
            await self._items.flush()
        return await self._cart(participant_id=participant.participant_id)

    async def remove_item(
        self,
        *,
        booking_id: uuid.UUID,
        user_id: uuid.UUID | None,
        guest_token: str | None,
        dish_id: uuid.UUID,
    ) -> CartView:
        participant = await self._lock_open(
            booking_id=booking_id, user_id=user_id, guest_token=guest_token
        )
        item = await self._items.get_draft(
            participant_id=participant.participant_id, dish_id=dish_id
        )
        if item is None:
            raise CartItemNotFoundError()
        await self._items.delete(item=item)
        return await self._cart(participant_id=participant.participant_id)

    async def submit(
        self, *, booking_id: uuid.UUID, user_id: uuid.UUID | None, guest_token: str | None
    ) -> SubmittedPartView:
        participant = await self._lock_open(
            booking_id=booking_id, user_id=user_id, guest_token=guest_token
        )
        items = await self._items.list_drafts(participant_id=participant.participant_id)
        if not items:
            raise CartEmptyError()
        dishes = await self._dishes.get_many(dish_ids={item.dish_id for item in items})
        if not all(dishes[item.dish_id].is_available for item in items):
            raise DishUnavailableError()
        submission_id = uuid.uuid4()
        now = clock.now()
        for item in items:
            item.state = PreorderItemState.SUBMITTED
            item.submission_id = submission_id
            item.submitted_at = now
            item.updated_at = now
        await self._items.flush()
        lines = self._lines(items, dishes)
        return SubmittedPartView(
            id=submission_id,
            submitted_at=now.astimezone(self._timezone),
            items=lines,
            total_cents=self._total(lines),
        )

    async def get_my_preorder(
        self, *, booking_id: uuid.UUID, user_id: uuid.UUID | None, guest_token: str | None
    ) -> MyPreorderView:
        participant = await self._participants.get_participant(
            booking_id=booking_id, user_id=user_id, guest_token=guest_token
        )
        items = await self._items.list_submitted(participant_id=participant.participant_id)
        dishes = await self._dishes.get_many(dish_ids={item.dish_id for item in items})
        grouped: dict[uuid.UUID, list[PreorderItem]] = {}
        for item in items:
            grouped.setdefault(cast(uuid.UUID, item.submission_id), []).append(item)
        parts = []
        for submission_id, part_items in grouped.items():
            lines = self._lines(part_items, dishes)
            parts.append(
                SubmittedPartView(
                    id=submission_id,
                    submitted_at=cast(datetime, part_items[0].submitted_at).astimezone(
                        self._timezone
                    ),
                    items=lines,
                    total_cents=self._total(lines),
                )
            )
        return MyPreorderView(parts=parts, total_cents=sum(part.total_cents for part in parts))

    async def _lock_open(
        self, *, booking_id: uuid.UUID, user_id: uuid.UUID | None, guest_token: str | None
    ) -> ParticipantAccess:
        participant = await self._participants.lock_participant(
            booking_id=booking_id, user_id=user_id, guest_token=guest_token
        )
        if not participant.preorder_open:
            raise PreorderClosedError()
        return participant

    async def _cart(self, *, participant_id: uuid.UUID) -> CartView:
        items = await self._items.list_drafts(participant_id=participant_id)
        dishes = await self._dishes.get_many(dish_ids={item.dish_id for item in items})
        lines = self._lines(items, dishes)
        return CartView(items=lines, total_cents=self._total(lines))

    @staticmethod
    def _lines(
        items: Sequence[PreorderItem], dishes: dict[uuid.UUID, DishView]
    ) -> list[CartLineView]:
        return [
            CartLineView(
                id=item.id,
                dish=dishes[item.dish_id],
                quantity=item.quantity,
                note=item.note,
                line_total_cents=dishes[item.dish_id].price_cents * item.quantity,
            )
            for item in items
        ]

    @staticmethod
    def _total(lines: Sequence[CartLineView]) -> int:
        return sum(line.line_total_cents for line in lines)
