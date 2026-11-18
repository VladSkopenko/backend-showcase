import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.common.database import Base


class AssistantModelCall(Base):
    __tablename__ = "assistant_model_calls"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, server_default=func.gen_random_uuid())
    model: Mapped[str] = mapped_column(String(100))
    input_tokens: Mapped[int]
    cached_input_tokens: Mapped[int]
    output_tokens: Mapped[int]
    cost_micro_usd: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
