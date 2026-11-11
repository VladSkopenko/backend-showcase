import uuid
from datetime import datetime
from typing import Annotated

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    StringConstraints,
    ValidationInfo,
    field_validator,
)

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


class RegisterRequest(BaseModel):
    first_name: Name
    last_name: Name
    email: EmailStr
    # The only server-side rule; any further rules from the design are enforced by the frontend.
    password: str = Field(min_length=8, max_length=128)
    password_confirmation: str = Field(max_length=128)

    # A password that failed its own checks is absent from info.data, so it gets one error only.
    @field_validator("password_confirmation")
    @classmethod
    def passwords_match(cls, value: str, info: ValidationInfo) -> str:
        if "password" in info.data and value != info.data["password"]:
            raise ValueError("Passwords do not match.")
        return value


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


class PasswordResetRequest(BaseModel):
    email: EmailStr


class PasswordResetCodeRequest(BaseModel):
    email: EmailStr
    code: str = Field(pattern=r"^\d{6}$")


class PasswordResetConfirmRequest(BaseModel):
    email: EmailStr
    code: str = Field(pattern=r"^\d{6}$")
    password: str = Field(min_length=8, max_length=128)
    password_confirmation: str = Field(max_length=128)

    # A password that failed its own checks is absent from info.data, so it gets one error only.
    @field_validator("password_confirmation")
    @classmethod
    def passwords_match(cls, value: str, info: ValidationInfo) -> str:
        if "password" in info.data and value != info.data["password"]:
            raise ValueError("Passwords do not match.")
        return value


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
