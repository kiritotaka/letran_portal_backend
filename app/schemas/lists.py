from datetime import datetime
from typing import Generic, Literal, TypeVar
from uuid import UUID

from pydantic import BaseModel, Field


class PaginationParams(BaseModel):
    page: int = Field(default=1, ge=1, le=1000000)
    page_size: int = Field(default=20, ge=1, le=100)

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


class Pagination(BaseModel):
    page: int
    page_size: int
    total: int
    total_pages: int
    has_next: bool
    has_previous: bool


class PermissionGroup(BaseModel):
    id: int
    group_name: str
    description: str | None = None


class PermissionItem(BaseModel):
    id: int
    permission_code: str
    permission_name: str
    group_id: int | None
    group: PermissionGroup | None = None


class UserItem(BaseModel):
    id: UUID
    email: str
    is_super_admin: bool
    is_first_login: bool
    created_at: datetime | None = None
    updated_at: datetime | None = None
    permissions: list[str]


T = TypeVar("T")


class PageData(BaseModel, Generic[T]):
    items: list[T]
    pagination: Pagination


class ListResponse(BaseModel, Generic[T]):
    success: Literal[True] = True
    data: PageData[T]

