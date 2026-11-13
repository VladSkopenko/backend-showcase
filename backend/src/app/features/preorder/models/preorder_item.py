import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Enum, ForeignKey, Index, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.common.database import Base
from app.features.preorder.enums import PreorderItemState


class PreorderItem(Base):
    __tablename__ = "preorder_items"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint(
            "(state = 'DRAFT') = (submission_id IS NULL) "
            "AND (submission_id IS NULL) = (submitted_at IS NULL)",
            name="submission_matches_state",
        ),
        Index(
            "ix_preorder_items_participant_id_dish_id_draft",
            "participant_id",
            "dish_id",
            unique=True,
            postgresql_where=text("state = 'DRAFT'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, server_default=func.gen_random_uuid())
    participant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("booking_participants.id", ondelete="CASCADE"), index=True
    )
    dish_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("dishes.id", ondelete="RESTRICT"))
    quantity: Mapped[int]
    note: Mapped[str | None] = mapped_column(String(200))
    state: Mapped[PreorderItemState] = mapped_column(
        Enum(PreorderItemState, name="preorder_item_state")
    )
    submission_id: Mapped[uuid.UUID | None]
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
