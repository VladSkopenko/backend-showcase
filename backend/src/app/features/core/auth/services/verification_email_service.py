import logging

from app.features.core.auth.dto import IssuedCode
from app.features.core.auth.services.verification_email_renderer import (
    VerificationEmailRenderer,
)
from app.infrastructure.email import EmailSender

logger = logging.getLogger(__name__)


class VerificationEmailService:
    def __init__(self, sender: EmailSender, renderer: VerificationEmailRenderer) -> None:
        self._sender = sender
        self._renderer = renderer

    async def send(self, *, issued: IssuedCode) -> None:
        # Runs as a background task after the response, so a failure is logged, never raised.
        to = issued.user.email
        try:
            email = self._renderer.render(
                purpose=issued.purpose,
                first_name=issued.user.first_name,
                email=to,
                code=issued.plain_code,
            )
            await self._sender.send(to=to, subject=email.subject, html=email.html, text=email.text)
        except Exception:
            logger.exception("Sending the %s email to %s failed", issued.purpose.value, to)
