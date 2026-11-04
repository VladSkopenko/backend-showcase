import logging

from app.config.settings import Environment

logger = logging.getLogger(__name__)


class LoggingEmailSender:
    # Logs only the recipient and subject: the body carries codes.

    def __init__(self, environment: Environment) -> None:
        self._level = logging.WARNING if environment == "local" else logging.ERROR

    async def send(self, *, to: str, subject: str, html: str, text: str) -> None:
        logger.log(
            self._level, "Email not sent, email is not configured: to=%s subject=%r", to, subject
        )
