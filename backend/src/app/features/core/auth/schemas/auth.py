import uuid
from datetime import datetime
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, EmailStr, Field, StringConstraints, model_validator

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


class RegisterRequest(BaseModel):
    first_name: Name
    last_name: Name
    email: EmailStr
    # The only server-side rule; any further rules from the design are enforced by the frontend.
    password: str = Field(min_length=8, max_length=128)
    password_confirmation: str = Field(max_length=128)

    @model_validator(mode="after")
    def passwords_match(self) -> Self:
        if self.password != self.password_confirmation:
            raise ValueError("Passwords do not match")
        return self


class RegisterResponse(BaseModel):
    id: uuid.UUID
    email: str
    # Set only in `local`, so local testing needs no inbox.
    debug_code: str | None = None


class VerifyEmailRequest(BaseModel):
    email: EmailStr
    code: str = Field(pattern=r"^\d{6}$")


class VerifyEmailResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    email_verified_at: datetime


class ResendCodeRequest(BaseModel):
    email: EmailStr


class ResendCodeResponse(BaseModel):
    debug_code: str | None = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(max_length=128)


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    first_name: str
    last_name: str
    email_verified_at: datetime | None
