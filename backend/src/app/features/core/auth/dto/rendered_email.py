from dataclasses import dataclass


@dataclass(frozen=True)
class RenderedEmail:
    subject: str
    html: str
    text: str
