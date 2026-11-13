import uuid
from dataclasses import dataclass


@dataclass(frozen=True)
class NoticeRecipient:
    user_id: uuid.UUID
    email: str
    first_name: str
