from dataclasses import dataclass

from app.features.preorder.dto.submitted_part_view import SubmittedPartView


@dataclass(frozen=True)
class MyPreorderView:
    parts: list[SubmittedPartView]
    total_cents: int
