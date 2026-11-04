from urllib.parse import urlencode

from jinja2 import Environment, PackageLoader, select_autoescape

from app.features.core.auth.dto import RenderedEmail


class VerificationEmailRenderer:
    SUBJECT = "Confirm your email"

    def __init__(self, *, frontend_url: str, ttl_minutes: int) -> None:
        self._frontend_url = frontend_url.rstrip("/")
        self._ttl_minutes = ttl_minutes
        self._templates = Environment(
            loader=PackageLoader("app.features.core.auth", "templates"),
            autoescape=select_autoescape(enabled_extensions=("html",), default_for_string=True),
        )

    def render(self, *, first_name: str, email: str, code: str) -> RenderedEmail:
        query = urlencode({"email": email, "code": code})
        context = {
            "first_name": first_name,
            "code": code,
            "confirm_url": f"{self._frontend_url}/verify-email?{query}",
            "ttl_minutes": self._ttl_minutes,
        }
        return RenderedEmail(
            subject=self.SUBJECT,
            html=self._templates.get_template("verification_email.html").render(context),
            text=self._templates.get_template("verification_email.txt").render(context),
        )
