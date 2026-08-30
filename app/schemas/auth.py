from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_serializer, field_validator
from pydantic.alias_generators import to_camel


def validate_password_strength(v: str) -> str:
    if not any(c.isalpha() for c in v) or not any(c.isdigit() for c in v):
        raise ValueError("Password must contain at least one letter and one number")
    return v


class CamelModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
    )


# --- Requests ---------------------------------------------------------------
class RegisterRequest(CamelModel):
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)

    _pw = field_validator("password")(validate_password_strength)


class LoginRequest(CamelModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class ForgotPasswordRequest(CamelModel):
    email: EmailStr


class ResetPasswordRequest(CamelModel):
    token: str = Field(min_length=1)
    password: str = Field(min_length=8, max_length=128)

    _pw = field_validator("password")(validate_password_strength)


# --- Responses -------------------------------------------------------------
class UserOut(CamelModel):
    id: str
    email: EmailStr
    first_name: str | None = None
    last_name: str | None = None
    full_name: str | None = None
    avatar_url: str | None = None
    created_at: datetime | None = None

    @field_serializer("created_at", when_used="json")
    def _ser_created_at(self, v: datetime | None) -> str | None:
        if v is None:
            return None
        if v.tzinfo is None:
            v = v.replace(tzinfo=UTC)
        return v.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class AuthResponse(CamelModel):
    token: str
    user: UserOut


class MessageResponse(CamelModel):
    message: str
