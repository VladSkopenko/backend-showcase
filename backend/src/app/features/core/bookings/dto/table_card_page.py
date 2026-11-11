from dataclasses import dataclass

from app.features.core.bookings.dto.table_card_view import TableCardView


@dataclass(frozen=True)
class TableCardPage:
    items: list[TableCardView]
    total: int
    limit: int
    offset: int
