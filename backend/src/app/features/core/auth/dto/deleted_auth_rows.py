from dataclasses import dataclass


@dataclass(frozen=True)
class DeletedAuthRows:
    refresh_tokens: int
    verification_codes: int
