from datetime import datetime
from typing import Generic, Literal, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator
from app.schemas.lists import PaginationParams


class RequestFilters(PaginationParams):
    document_type_id: UUID | None = None
    search: str = Field(default="", max_length=200)

    @model_validator(mode="after")
    def trim_search(self):
        self.search = self.search.strip()
        return self


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class CreateRequest(Input):
    task_id: UUID
    title: str = Field(min_length=1, max_length=200)


class UpdateRequest(Input):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    status: Literal["draft", "archived"] | None = None

    @model_validator(mode="after")
    def nonempty(self):
        if not self.model_fields_set or any(getattr(self, k) is None for k in self.model_fields_set):
            raise ValueError("Provide non-null fields to update")
        return self


class CreateDocument(Input):
    document_type_id: UUID
    title: str = Field(min_length=1, max_length=200)


class ReorderFile(Input):
    sort_order: int = Field(strict=True, ge=1, le=10000)


class CatalogItem(BaseModel):
    id: UUID
    code: str
    name: str
    is_active: bool


class TemplateItem(BaseModel):
    id: UUID
    task_id: UUID
    name: str
    version: int
    output_format: str
    is_active: bool


class RequestItem(BaseModel):
    id: UUID
    task_id: UUID
    template_id: UUID | None
    title: str
    status: str
    created_by: UUID
    updated_by: UUID
    created_at: datetime
    updated_at: datetime


class DocumentItem(BaseModel):
    id: UUID
    request_id: UUID
    document_type_id: UUID
    title: str
    created_by: UUID
    created_at: datetime


class FileItem(BaseModel):
    id: UUID
    original_name: str
    content_type: str
    size_bytes: int
    status: Literal["uploading", "ready", "deleted"]
    created_by: UUID
    created_at: datetime
    updated_at: datetime


class LinkedFile(BaseModel):
    request_id: UUID
    document_id: UUID
    file_id: UUID
    sort_order: int
    file: FileItem


class FileOrder(BaseModel):
    request_id: UUID
    document_id: UUID
    file_id: UUID
    sort_order: int


class DownloadData(BaseModel):
    file_id: UUID
    download_url: str
    expires_in: int = 300


T = TypeVar("T")


class DocumentResponse(BaseModel, Generic[T]):
    success: Literal[True] = True
    data: T
