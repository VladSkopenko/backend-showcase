from app.features.core.auth.dto import RenderedEmail
from app.features.core.auth.enums import VerificationPurpose
from app.features.core.auth.services.verification_email_renderer import (
    VerificationEmailRenderer,
)

QUERY = "email=ada%2Btest%40example.com&code=012345"
LINK = f"https://front.example/verify-email?{QUERY}"
RESET_LINK = f"https://front.example/reset-password?{QUERY}"


def render(
    first_name: str = "Ada", purpose: VerificationPurpose = VerificationPurpose.EMAIL_VERIFICATION
) -> RenderedEmail:
    renderer = VerificationEmailRenderer(frontend_url="https://front.example", ttl_minutes=10)
    return renderer.render(
        purpose=purpose, first_name=first_name, email="ada+test@example.com", code="012345"
    )


def test_html_part_has_the_code_and_the_prefilled_link() -> None:
    email = render()

    assert email.subject == "Confirm your email"
    assert "012345" in email.html
    # Autoescape writes the query separator as &amp; inside the href attribute.
    assert LINK.replace("&", "&amp;") in email.html
    assert "Confirm email" in email.html


def test_text_part_has_the_code_and_the_link() -> None:
    email = render()

    assert "012345" in email.text
    assert LINK in email.text


def test_html_part_escapes_user_input() -> None:
    html = render(first_name="<b>Ada</b>").html

    assert "<b>Ada</b>" not in html
    assert "&lt;b&gt;Ada&lt;/b&gt;" in html


def test_reset_email_has_the_code_and_the_reset_link() -> None:
    email = render(purpose=VerificationPurpose.PASSWORD_RESET)

    assert email.subject == "Reset your password"
    assert "012345" in email.html
    assert RESET_LINK.replace("&", "&amp;") in email.html
    assert "Reset password" in email.html
    assert "/verify-email" not in email.html
    assert "012345" in email.text
    assert RESET_LINK in email.text


def test_both_emails_share_the_layout() -> None:
    verification = render().html
    reset = render(purpose=VerificationPurpose.PASSWORD_RESET).html

    code_block = "letter-spacing:8px"
    assert code_block in verification
    assert code_block in reset
    assert verification.split("<body", 1)[0].replace("Confirm your email", "") == reset.split(
        "<body", 1
    )[0].replace("Reset your password", "")
