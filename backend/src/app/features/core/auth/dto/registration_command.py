from dataclasses import dataclass


@dataclass(frozen=True)
class RegistrationCommand:
    first_name: str
    last_name: str
    email: str
    password: str
