from typing import Literal
from uuid import UUID

from pydantic import AliasChoices, BaseModel, ConfigDict, EmailStr, Field, SecretStr, model_validator


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    email: EmailStr = Field(max_length=254)
    password: SecretStr = Field(min_length=1, max_length=4096)


class RefreshRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    refresh_token: SecretStr = Field(min_length=1, max_length=8192)

    @model_validator(mode="after")
    def validate_token(self):
        token = self.refresh_token.get_secret_value()
        if any(character.isspace() for character in token):
            raise ValueError("Refresh token must not contain whitespace.")
        return self


class LoginUser(BaseModel):
    id: UUID
    email: EmailStr
    is_active: bool
    is_super_admin: bool
    is_first_login: bool
    permissions: list[str]


class LoginData(BaseModel):
    access_token: str
    refresh_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int
    expires_at: int | None
    user: LoginUser


class LoginResponse(BaseModel):
    success: Literal[True] = True
    data: LoginData


class ChangePasswordRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    email: EmailStr = Field(max_length=254)
    current_password: SecretStr = Field(
        min_length=1, max_length=4096,
        validation_alias=AliasChoices("current_password", "currentPassword"),
    )
    new_password: SecretStr = Field(
        min_length=8, max_length=4096,
        validation_alias=AliasChoices("new_password", "newPassword"),
    )

    @model_validator(mode="after")
    def validate_passwords(self):
        new = self.new_password.get_secret_value()
        if not new.strip():
            raise ValueError("New password must not consist only of whitespace.")
        if new == self.current_password.get_secret_value():
            raise ValueError("New password must differ from current password.")
        return self


class ChangePasswordData(BaseModel):
    password_changed: Literal[True] = True
    is_first_login: Literal[False] = False
    requires_login: Literal[True] = True


class ChangePasswordResponse(BaseModel):
    success: Literal[True] = True
    message: str = "Password changed. Sign in with your new password."
    data: ChangePasswordData = Field(default_factory=ChangePasswordData)
