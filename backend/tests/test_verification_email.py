from app.features.core.auth.services.verification_email_renderer import (
    VerificationEmailRenderer,
)

LINK = "https://front.example/verify-email?email=ada%2Btest%40example.com&code=012345"


def render(first_name: str = "Ada") -> tuple[str, str]:
    renderer = VerificationEmailRenderer(frontend_url="https://front.example", ttl_minutes=10)
    email = renderer.render(first_name=first_name, email="ada+test@example.com", code="012345")
    assert email.subject
    return email.html, email.text


def test_html_part_has_the_code_and_the_prefilled_link() -> None:
    html, _ = render()

    assert "012345" in html
    # Autoescape writes the query separator as &amp; inside the href attribute.
    assert LINK.replace("&", "&amp;") in html
    assert "Confirm email" in html


def test_text_part_has_the_code_and_the_link() -> None:
    _, text = render()

    assert "012345" in text
    assert LINK in text


def test_html_part_escapes_user_input() -> None:
    html, _ = render(first_name="<b>Ada</b>")

    assert "<b>Ada</b>" not in html
    assert "&lt;b&gt;Ada&lt;/b&gt;" in html
