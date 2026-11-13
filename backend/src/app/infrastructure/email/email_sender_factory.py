from app.config.settings import EmailSettings, Environment
from app.infrastructure.email.email_sender import EmailSender
from app.infrastructure.email.logging_email_sender import LoggingEmailSender
from app.infrastructure.email.smtp_email_sender import SmtpEmailSender


def create_email_sender(*, settings: EmailSettings, environment: Environment) -> EmailSender:
    if settings.is_configured:
        return SmtpEmailSender(settings)
    return LoggingEmailSender(environment)
