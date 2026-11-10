import uuid

from sqlalchemy import CheckConstraint, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.common.database import Base


class DiningTable(Base):
    __tablename__ = "dining_tables"
    __table_args__ = (
        UniqueConstraint("location_id", "label", name="uq_dining_tables_location_id_label"),
        CheckConstraint("capacity BETWEEN 2 AND 8", name="capacity_between_2_and_8"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, server_default=func.gen_random_uuid())
    location_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("locations.id", ondelete="CASCADE"))
    label: Mapped[str] = mapped_column(String(50))
    capacity: Mapped[int]
