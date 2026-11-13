import logging
from collections.abc import Sequence

from app.features.core.notifications.dto import DecisionNotice, NoticeRecipient
from app.features.core.notifications.services.decision_email_renderer import (
    DecisionEmailRenderer,
)
from app.infrastructure.email import EmailSender

logger = logging.getLogger(__name__)


class DecisionEmailService:
    def __init__(
        self,
        sender: EmailSender,
        renderer: DecisionEmailRenderer,
        *,
        skip_email_domains: Sequence[str],
    ) -> None:
        self._sender = sender
        self._renderer = renderer
        self._skipped_domains = frozenset(
            domain.strip().lstrip("@").lower() for domain in skip_email_domains
        )

    async def send(self, *, notices: Sequence[DecisionNotice]) -> None:
        for notice in notices:
            for recipient in notice.recipients:
                if not self._is_skipped(recipient.email):
                    await self._send_one(notice=notice, recipient=recipient)

    def _is_skipped(self, email: str) -> bool:
        return email.rpartition("@")[2].lower() in self._skipped_domains

    async def _send_one(self, *, notice: DecisionNotice, recipient: NoticeRecipient) -> None:
        # Runs after the decision is committed, so a failure is logged, never raised.
        try:
            email = self._renderer.render(notice=notice, recipient=recipient)
            await self._sender.send(
                to=recipient.email, subject=email.subject, html=email.html, text=email.text
            )
        except Exception:
            logger.exception(
                "Sending the %s email to %s failed", notice.kind.value, recipient.email
            )
