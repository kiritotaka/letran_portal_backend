from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, SecretStr


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    email: EmailStr = Field(max_length=254)
    password: SecretStr = Field(min_length=1, max_length=4096)


class LoginUser(BaseModel):
    id: UUID
    email: EmailStr
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

