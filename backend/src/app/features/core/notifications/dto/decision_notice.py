from dataclasses import dataclass
from datetime import datetime

from app.features.core.notifications.dto.notice_recipient import NoticeRecipient
from app.features.core.notifications.enums import NotificationKind


@dataclass(frozen=True)
class DecisionNotice:
    kind: NotificationKind
    starts_at: datetime
    location_address: str
    party_size: int
    recipients: list[NoticeRecipient]
