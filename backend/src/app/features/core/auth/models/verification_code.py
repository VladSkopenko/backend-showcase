import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.common.database import Base
from app.features.core.auth.enums import VerificationPurpose


class VerificationCode(Base):
    __tablename__ = "verification_codes"
    # Named explicitly: the ix naming convention would name it after the first column only.
    __table_args__ = (
        Index(
            "ix_verification_codes_user_id_purpose_created_at", "user_id", "purpose", "created_at"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, server_default=func.gen_random_uuid())
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    purpose: Mapped[VerificationPurpose] = mapped_column(
        Enum(VerificationPurpose, name="verification_purpose")
    )
    code_hash: Mapped[str] = mapped_column(String(64))
    attempts: Mapped[int] = mapped_column(default=0)
    # No server defaults: the timestamps come from app.common.clock, so tests can move time.
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
