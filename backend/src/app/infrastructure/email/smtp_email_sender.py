from email.message import EmailMessage

import aiosmtplib

from app.config.settings import EmailSettings


class SmtpEmailSender:
    def __init__(self, settings: EmailSettings) -> None:
        self._settings = settings

    async def send(self, *, to: str, subject: str, html: str, text: str) -> None:
        message = EmailMessage()
        message["From"] = self._settings.sender
        message["To"] = to
        message["Subject"] = subject
        message.set_content(text)
        message.add_alternative(html, subtype="html")
        await aiosmtplib.send(
            message,
            hostname=self._settings.smtp_host,
            port=self._settings.smtp_port,
            username=self._settings.username,
            password=self._settings.password.get_secret_value(),
            start_tls=True,
        )
