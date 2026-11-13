from jinja2 import Environment, PackageLoader, select_autoescape

from app.features.core.auth.dto import RenderedEmail
from app.features.core.notifications.dto import DecisionNotice, NoticeRecipient
from app.features.core.notifications.enums import NotificationKind


class DecisionEmailRenderer:
    SUBJECTS = {
        NotificationKind.BOOKING_REQUEST_APPROVED: "Your booking request is approved",
        NotificationKind.BOOKING_REQUEST_REJECTED: "Your booking request is rejected",
    }
    TEMPLATE_NAMES = {
        NotificationKind.BOOKING_REQUEST_APPROVED: "booking_request_approved",
        NotificationKind.BOOKING_REQUEST_REJECTED: "booking_request_rejected",
    }
    RESERVATIONS_PATH = "/reservations"

    def __init__(self, *, frontend_url: str) -> None:
        self._frontend_url = frontend_url.rstrip("/")
        self._templates = Environment(
            loader=PackageLoader("app.features.core.notifications", "templates"),
            autoescape=select_autoescape(enabled_extensions=("html",), default_for_string=True),
        )

    def render(self, *, notice: DecisionNotice, recipient: NoticeRecipient) -> RenderedEmail:
        subject = self.SUBJECTS[notice.kind]
        starts_at = notice.starts_at
        context = {
            "subject": subject,
            "first_name": recipient.first_name,
            "date": f"{starts_at:%A}, {starts_at.day} {starts_at:%B %Y}",
            "time": f"{starts_at:%H:%M}",
            "location": notice.location_address,
            "party_size": notice.party_size,
            "action_url": f"{self._frontend_url}{self.RESERVATIONS_PATH}",
        }
        template_name = self.TEMPLATE_NAMES[notice.kind]
        return RenderedEmail(
            subject=subject,
            html=self._templates.get_template(f"{template_name}.html").render(context),
            text=self._templates.get_template(f"{template_name}.txt").render(context),
        )
