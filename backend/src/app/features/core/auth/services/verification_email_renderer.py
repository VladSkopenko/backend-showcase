from urllib.parse import urlencode

from jinja2 import Environment, PackageLoader, select_autoescape

from app.features.core.auth.dto import RenderedEmail
from app.features.core.auth.enums import VerificationPurpose


class VerificationEmailRenderer:
    SUBJECTS = {
        VerificationPurpose.EMAIL_VERIFICATION: "Confirm your email",
        VerificationPurpose.PASSWORD_RESET: "Reset your password",
    }
    TEMPLATE_NAMES = {
        VerificationPurpose.EMAIL_VERIFICATION: "verification_email",
        VerificationPurpose.PASSWORD_RESET: "password_reset_email",
    }
    FRONTEND_PATHS = {
        VerificationPurpose.EMAIL_VERIFICATION: "/verify-email",
        VerificationPurpose.PASSWORD_RESET: "/reset-password",
    }

    def __init__(self, *, frontend_url: str, ttl_minutes: int) -> None:
        self._frontend_url = frontend_url.rstrip("/")
        self._ttl_minutes = ttl_minutes
        self._templates = Environment(
            loader=PackageLoader("app.features.core.auth", "templates"),
            autoescape=select_autoescape(enabled_extensions=("html",), default_for_string=True),
        )

    def render(
        self, *, purpose: VerificationPurpose, first_name: str, email: str, code: str
    ) -> RenderedEmail:
        query = urlencode({"email": email, "code": code})
        subject = self.SUBJECTS[purpose]
        context = {
            "subject": subject,
            "first_name": first_name,
            "code": code,
            "action_url": f"{self._frontend_url}{self.FRONTEND_PATHS[purpose]}?{query}",
            "ttl_minutes": self._ttl_minutes,
        }
        template_name = self.TEMPLATE_NAMES[purpose]
        return RenderedEmail(
            subject=subject,
            html=self._templates.get_template(f"{template_name}.html").render(context),
            text=self._templates.get_template(f"{template_name}.txt").render(context),
        )
