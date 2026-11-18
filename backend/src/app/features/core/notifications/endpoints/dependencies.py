from typing import Annotated

from fastapi import Depends

from app.config.settings import Settings, get_settings
from app.features.core.auth.endpoints.dependencies import EmailSenderDep
from app.features.core.notifications.services.decision_email_renderer import (
    DecisionEmailRenderer,
)
from app.features.core.notifications.services.decision_email_service import DecisionEmailService

SettingsDep = Annotated[Settings, Depends(get_settings)]


def get_decision_email_renderer(settings: SettingsDep) -> DecisionEmailRenderer:
    return DecisionEmailRenderer(frontend_url=settings.app.frontend_url)


DecisionEmailRendererDep = Annotated[DecisionEmailRenderer, Depends(get_decision_email_renderer)]


def get_decision_email_service(
    sender: EmailSenderDep, renderer: DecisionEmailRendererDep, settings: SettingsDep
) -> DecisionEmailService:
    return DecisionEmailService(
        sender, renderer, skip_email_domains=settings.notifications.skip_email_domains
    )


DecisionEmailServiceDep = Annotated[DecisionEmailService, Depends(get_decision_email_service)]
