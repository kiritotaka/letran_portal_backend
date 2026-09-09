from typing import Literal, Annotated
from pydantic import BaseModel, ConfigDict, EmailStr, Field, SecretStr, model_validator
from app.schemas.lists import UserItem

PermissionId = Annotated[int, Field(strict=True, gt=0)]


class CreateUserRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    email: EmailStr = Field(max_length=254)
    password: SecretStr = Field(min_length=8, max_length=4096)
    permission_ids: list[PermissionId] = Field(default_factory=list, max_length=500)
    is_super_admin: bool = Field(default=False, strict=True)

    @model_validator(mode="after")
    def validate_password(self):
        if not self.password.get_secret_value().strip():
            raise ValueError("Password must not consist only of whitespace.")
        return self


class UpdateUserRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    email: EmailStr | None = Field(default=None, max_length=254)
    permission_ids: list[PermissionId] | None = Field(default=None, max_length=500)
    is_super_admin: bool | None = Field(default=None, strict=True)
    is_active: bool | None = Field(default=None, strict=True)

    @model_validator(mode="after")
    def validate_patch(self):
        if not self.model_fields_set or any(getattr(self, key) is None for key in self.model_fields_set):
            raise ValueError("Supply at least one non-null field.")
        return self


class UserResponse(BaseModel):
    success: Literal[True] = True
    data: UserItem
