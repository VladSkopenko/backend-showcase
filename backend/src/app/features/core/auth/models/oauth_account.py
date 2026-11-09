import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.common.database import Base
from app.features.core.auth.enums import OAuthProvider


class OAuthAccount(Base):
    __tablename__ = "user_oauth_accounts"
    # Named explicitly: the uq naming convention would name them after the first column only.
    __table_args__ = (
        UniqueConstraint("provider", "subject", name="uq_user_oauth_accounts_provider_subject"),
        UniqueConstraint("user_id", "provider", name="uq_user_oauth_accounts_user_id_provider"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, server_default=func.gen_random_uuid())
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    provider: Mapped[OAuthProvider] = mapped_column(Enum(OAuthProvider, name="oauth_provider"))
    subject: Mapped[str] = mapped_column(String(255))
    # No server default: the timestamp comes from app.common.clock, so tests can move time.
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
