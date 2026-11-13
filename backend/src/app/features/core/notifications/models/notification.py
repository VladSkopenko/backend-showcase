import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Index, func
from sqlalchemy.orm import Mapped, mapped_column

from app.common.database import Base
from app.features.core.notifications.enums import NotificationKind


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (
        Index("ix_notifications_user_id_created_at_id", "user_id", "created_at", "id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, server_default=func.gen_random_uuid())
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    kind: Mapped[NotificationKind] = mapped_column(Enum(NotificationKind, name="notification_kind"))
    booking_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("bookings.id", ondelete="CASCADE"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
